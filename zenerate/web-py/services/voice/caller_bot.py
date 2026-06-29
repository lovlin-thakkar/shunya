"""
Synthetic caller bot for audio-fidelity scenario testing.

Joins a Daily room already occupied by the agent bot, speaks each scenario step
via ElevenLabs TTS, waits for the agent to respond, then transcribes the response
via ElevenLabs Scribe v2 (STT).

Caller is responsible for Daily.init() before instantiating this class.

Recording approach — true real-time capture, not reconstruction:
  _caller_frames: list of (call_offset_secs, pcm) — exact timestamp when each
      chunk of caller TTS audio was injected into the Daily mic device.
  _agent_frames:  list of (call_offset_secs, pcm) — exact timestamp when each
      chunk of agent audio arrived on the Daily speaker device, including silence
      frames. Because frames are timestamped at arrival, the gaps between them
      represent real silence in the call — no silence is invented or estimated.
  _write_recording() mixes both lists onto a shared PCM timeline.

All ts_ms values in the transcript are milliseconds from call start (joined event),
so consecutive turns can be diffed to derive real pipeline latency.
"""
import array
import asyncio
import collections
import io
import logging
import os
import struct
import time
import uuid
import wave
from dataclasses import dataclass, field

import httpx

from config import DEFAULT_VOICE_ID

logger = logging.getLogger(__name__)

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"


class ElevenLabsQuotaError(Exception):
    """Raised when ElevenLabs API credits are exhausted — fail the run immediately."""

RESPONSE_TIMEOUT = 30
# After agent starts speaking, collect this many seconds before transcribing
AGENT_COLLECT_WINDOW = 10.0
MIN_AUDIO_DURATION = 0.3
# Energy threshold — WebRTC-encoded audio is quiet, so set low
SILENCE_RMS_THRESHOLD = 20
# 16 kHz mono 16-bit: 1 second = 32 000 bytes
BYTES_PER_SEC = 32_000
# Pre-roll: capture this many 20ms frames before speech crosses threshold,
# so the very first syllable of each agent turn is never lost.
PREROLL_FRAMES = 15  # 15 × 20ms = 300ms look-back window


@dataclass
class Turn:
    speaker: str   # "caller" | "agent"
    text: str
    ts_ms: int = 0       # ms from call-joined to when this turn STARTED speaking
    quirks: list = field(default_factory=list)


class ScenarioCallerBot:
    """
    Drives a full scenario as real audio in a Daily.co room.
    Call Daily.init() before instantiating. Uses daily-python 0.30.0 API.
    """

    def __init__(
        self,
        room_url: str,
        room_token: str,
        steps: list[dict],
        elevenlabs_api_key: str = "",
        voice_id: str = DEFAULT_VOICE_ID,
        recording_id: str = "",
    ):
        self.room_url = room_url
        self.room_token = room_token
        self.steps = steps
        self.voice_id = voice_id or DEFAULT_VOICE_ID
        self.recording_id = recording_id
        self._el_key = elevenlabs_api_key or os.environ["ELEVENLABS_API_KEY"]
        self._device_id = uuid.uuid4().hex[:8]  # unique per call so devices don't collide
        self._transcript: list[Turn] = []
        # For transcription logic only (non-silent agent audio chunks)
        self._agent_audio_buf: list[bytes] = []
        # Rolling look-back of recent frames prepended when speech is detected
        self._preroll: collections.deque[bytes] = collections.deque(maxlen=PREROLL_FRAMES)
        self._last_audio_ts: float = 0.0
        self._agent_speaking = False
        self._speech_start_ts: float = 0.0
        self._call_client = None
        self._mic = None
        self._joined = asyncio.Event()
        self._agent_participant_id: str | None = None
        # Real-time capture — timestamped audio chunks from both sides
        # Each entry: (call_offset_secs, pcm_bytes)
        self._caller_frames: list[tuple[float, bytes]] = []
        self._agent_frames: list[tuple[float, bytes]] = []
        self._call_start_ts: float = 0.0  # monotonic time at call-joined
        self._caller_done_ts: float = 0.0  # monotonic time after each caller turn ends
        self.recording_file: str | None = None

    async def run(self) -> list[dict]:
        from daily import CallClient, EventHandler

        caller_bot = self

        class Handler(EventHandler):
            def on_call_state_updated(self, state):
                if state == "joined":
                    try:
                        participants = caller_bot._call_client.participants()
                        caller_bot._local_participant_id = (
                            participants.get("local", {}).get("id")
                        )
                    except (RuntimeError, AttributeError, KeyError):
                        caller_bot._local_participant_id = None
                    logger.info(f"Caller bot joined room (local={caller_bot._local_participant_id})")
                    caller_bot._joined.set()
                elif state in ("left", "error"):
                    logger.info(f"Caller bot call state: {state}")

            def on_participant_joined(self, participant):
                pid = participant.get("id", "")
                if pid and pid != caller_bot._local_participant_id:
                    logger.info(f"Agent participant joined: {pid}")
                    caller_bot._agent_participant_id = pid
                    # Register audio callback so we receive the agent's TTS output.
                    # VirtualSpeakerDevice.read_frames() returns empty in 0.30.0 without
                    # explicit subscriptions; set_audio_renderer is the reliable path.
                    try:
                        caller_bot._call_client.set_audio_renderer(
                            pid,
                            caller_bot._on_agent_audio,
                            audio_source="microphone",
                            sample_rate=16000,
                            callback_interval_ms=20,
                        )
                        logger.info(f"Registered audio renderer for agent {pid}")
                    except Exception as e:
                        logger.error(f"Failed to register audio renderer: {e}")

            def on_participant_left(self, participant, reason):
                logger.info(f"Participant left: {participant.get('id', '')} reason={reason}")

            def on_error(self, message):
                logger.error(f"Daily call error: {message}")

        from daily import Daily
        # non_blocking so write_frames can be called from the event-loop thread
        # without freezing it; daily devices are thread-affine, so we must NOT
        # write from a worker thread (that silently injected nothing).
        mic_name = f"caller-mic-{self._device_id}"
        self._mic = Daily.create_microphone_device(
            mic_name, sample_rate=16000, channels=1, non_blocking=True
        )

        self._call_client = CallClient(event_handler=Handler())
        self._local_participant_id: str | None = None

        # daily-python 0.30.0 requires deviceId nested under "settings".
        client_settings = {
            "inputs": {
                "microphone": {"isEnabled": True, "settings": {"deviceId": mic_name}},
                "camera": {"isEnabled": False},
            },
        }
        self._call_client.join(
            self.room_url,
            meeting_token=self.room_token,
            client_settings=client_settings,
        )

        await asyncio.wait_for(self._joined.wait(), timeout=30)
        # Record exact call-start time after join so all offsets are from this point
        self._call_start_ts = time.monotonic()

        # Wait for the agent's opening greeting (if any) before sending step 1.
        # Poll up to GREETING_WAIT_SECS for agent audio to start, then finish.
        greeting_text = await self._wait_for_greeting()
        if greeting_text:
            agent_ts_ms = int((self._speech_start_ts - self._call_start_ts) * 1000)
            self._transcript.append(Turn("agent", greeting_text, agent_ts_ms))
            logger.info("Agent greeting captured: %s", greeting_text[:60])

        # Agent audio arrives via _on_agent_audio() callback (set_audio_renderer)
        # registered in on_participant_joined — no polling task needed.
        try:
            await self._speak_loop()
        finally:
            self._call_client.leave()
            self._write_recording()

        return [
            {"speaker": t.speaker, "text": t.text, "ts_ms": t.ts_ms, "quirks": t.quirks}
            for t in self._transcript
        ]

    def _write_recording(self):
        """
        Build the WAV from the real-time-captured frames.

        Both _caller_frames and _agent_frames are lists of (offset_secs, pcm).
        offset_secs is the monotonic wall-clock offset from call-joined, captured
        at the moment each chunk was sent to / received from the Daily room.
        Gaps between chunks stay as silence (zeros) — they represent real pipeline
        pauses, agent think time, etc. Nothing is invented.
        """
        if not self.recording_id:
            return
        all_chunks = self._caller_frames + self._agent_frames
        if not all_chunks:
            return

        # Determine total WAV duration from the last received chunk
        total_secs = max(off + len(pcm) / BYTES_PER_SEC for off, pcm in all_chunks)
        total_bytes = int(total_secs * BYTES_PER_SEC) + BYTES_PER_SEC  # +1s tail
        # 16-bit samples → total_bytes must be even; start with silence (zeros)
        buf = array.array("h", [0] * (total_bytes // 2))

        for offset_secs, pcm in all_chunks:
            start_sample = int(offset_secs * 16000)
            # Normalize to int16 array
            n = len(pcm) // 2
            chunk = array.array("h", pcm[:n * 2])
            for i, s in enumerate(chunk):
                idx = start_sample + i
                if idx >= len(buf):
                    break
                # Half-duplex — caller and agent shouldn't overlap, but clamp anyway
                buf[idx] = max(-32768, min(32767, buf[idx] + s))

        try:
            os.makedirs("/recordings", exist_ok=True)
            path = f"/recordings/{self.recording_id}.wav"
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(buf.tobytes())
            self.recording_file = f"{self.recording_id}.wav"
            logger.info(
                "Wrote recording %s (%.1fs, %d caller chunks, %d agent chunks)",
                path, total_secs, len(self._caller_frames), len(self._agent_frames),
            )
        except OSError as e:
            logger.error(f"Failed to write recording: {e}")

    def _on_agent_audio(self, participant_id: str, audio_data, audio_source: str = "microphone") -> None:
        """
        Called from the Daily SDK thread (not the asyncio event loop) when the
        agent sends audio. Replaces the VirtualSpeakerDevice polling approach
        which returns empty bytes in daily-python 0.30.0 without explicit
        subscriptions.

        Only non-silent frames are stored in _agent_audio_buf (for STT). ALL
        frames including silence are stored in _agent_frames for the WAV recording
        so gap timing is accurate.
        """
        raw = bytes(audio_data.audio_frames) if hasattr(audio_data, "audio_frames") else bytes(audio_data)
        if not raw or len(raw) < 2:
            return

        # Thread-safe: list.append is atomic under the GIL
        if self._call_start_ts:
            offset = time.monotonic() - self._call_start_ts
            self._agent_frames.append((offset, raw))

        n = len(raw) // 2
        samples = struct.unpack_from(f"<{n}h", raw[: n * 2])
        rms = (sum(s * s for s in samples) / n) ** 0.5

        if rms > SILENCE_RMS_THRESHOLD:
            self._last_audio_ts = time.monotonic()
            if not self._agent_speaking:
                self._agent_speaking = True
                self._speech_start_ts = time.monotonic()
                # Prepend the pre-roll so the onset syllable is not lost
                self._agent_audio_buf.extend(self._preroll)
                self._preroll.clear()
        else:
            # Keep silent frames in the look-back window; discard once speech starts
            if not self._agent_speaking:
                self._preroll.append(raw)

        if self._agent_speaking:
            self._agent_audio_buf.append(raw)

    async def _wait_for_greeting(self) -> str:
        """Wait up to 8s for the agent to start speaking, then collect the full
        greeting. Returns empty string if the agent is silent (no greeting).
        This prevents the caller from talking over the opening greeting."""
        GREETING_START_TIMEOUT = 8.0   # how long to wait for first audio
        poll_start = time.monotonic()
        while time.monotonic() - poll_start < GREETING_START_TIMEOUT:
            if self._agent_speaking:
                text, _ = await self._collect_agent_response()
                self._agent_audio_buf.clear()
                self._preroll.clear()
                self._agent_speaking = False
                return text
            await asyncio.sleep(0.1)
        return ""

    async def _speak_loop(self):
        for step in self.steps:
            clean = step.get("text", step.get("raw", ""))
            quirks = [q.get("tag", "") for q in step.get("quirks", [])]

            # Record caller turn with its timestamp from call start
            caller_ts_ms = int((time.monotonic() - self._call_start_ts) * 1000)
            self._transcript.append(Turn("caller", clean, caller_ts_ms, quirks))
            logger.info(f"Caller speaking at +{caller_ts_ms}ms: {clean[:60]}")

            self._agent_audio_buf.clear()
            self._preroll.clear()
            self._agent_speaking = False

            try:
                audio_bytes = await self._synthesize_tts(clean)
            except ElevenLabsQuotaError:
                logger.error("ElevenLabs quota exhausted — aborting scenario immediately")
                raise
            if audio_bytes:
                # Timestamp BEFORE send so offset reflects when audio starts playing
                caller_offset = time.monotonic() - self._call_start_ts
                self._caller_frames.append((caller_offset, audio_bytes))
                await self._send_audio(audio_bytes)
            else:
                logger.warning("No audio synthesized for step")
            # Mark caller-done for latency measurement on the agent turn
            self._caller_done_ts = time.monotonic()

            agent_text, latency_ms = await self._collect_agent_response()
            if agent_text:
                agent_ts_ms = int((self._speech_start_ts - self._call_start_ts) * 1000)
                self._transcript.append(Turn("agent", agent_text, agent_ts_ms))
                logger.info(
                    "Agent responded at +%dms (pipeline latency %dms)",
                    agent_ts_ms, latency_ms,
                )

    async def _collect_agent_response(self) -> tuple[str, int]:
        """Returns (transcript_text, pipeline_latency_ms).
        pipeline_latency_ms = time from caller done speaking to agent first audio."""
        deadline = time.monotonic() + RESPONSE_TIMEOUT

        # Wait for agent to start speaking
        while time.monotonic() < deadline:
            if self._agent_speaking:
                break
            await asyncio.sleep(0.1)
        else:
            logger.warning("Timed out waiting for agent to start speaking")
            return "", 0

        latency_ms = int((self._speech_start_ts - self._caller_done_ts) * 1000)
        logger.info(
            "Agent started speaking — pipeline latency %dms, collecting for up to %.1fs",
            latency_ms, AGENT_COLLECT_WINDOW,
        )

        # Collect for a fixed window after speech starts, then check for silence
        collect_deadline = self._speech_start_ts + AGENT_COLLECT_WINDOW
        while time.monotonic() < collect_deadline:
            await asyncio.sleep(0.1)
            # Early exit: if we haven't heard audio in 2s, agent is done
            if self._agent_audio_buf and (time.monotonic() - self._last_audio_ts) > 2.0:
                logger.info("Agent silence detected — stopping early")
                break

        if not self._agent_audio_buf:
            logger.warning("No agent audio collected")
            return "", 0

        raw_pcm = b"".join(self._agent_audio_buf)
        self._agent_audio_buf.clear()
        self._agent_speaking = False
        logger.info("Collected %.2fs of agent audio — transcribing", len(raw_pcm) / BYTES_PER_SEC)
        text = await self._transcribe_scribe(raw_pcm)
        return text, latency_ms

    async def _synthesize_tts(self, text: str) -> bytes | None:
        url = f"{ELEVENLABS_API_URL}/text-to-speech/{self.voice_id}/stream"
        # output_format MUST be a query parameter — in the JSON body it is
        # ignored and ElevenLabs returns MP3 (ID3-tagged), which written as raw
        # PCM is high-RMS noise that VAD/STT cannot recognise as speech.
        params = {"output_format": "pcm_16000"}
        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
        }
        headers = {"xi-api-key": self._el_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(url, params=params, json=payload, headers=headers)
                if r.status_code == 401:
                    try:
                        detail = r.json().get("detail", {})
                        if isinstance(detail, dict) and detail.get("code") == "quota_exceeded":
                            raise ElevenLabsQuotaError(detail.get("message", "ElevenLabs quota exhausted"))
                    except (ValueError, AttributeError):
                        pass
                r.raise_for_status()
                return r.content
        except ElevenLabsQuotaError:
            raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            logger.error(f"ElevenLabs TTS failed: {e}")
            return None

    async def _transcribe_scribe(self, pcm_bytes: bytes) -> str:
        duration = len(pcm_bytes) / (16000 * 2)
        if duration < MIN_AUDIO_DURATION:
            return ""

        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm_bytes)
        wav_bytes = wav_buf.getvalue()

        url = f"{ELEVENLABS_API_URL}/speech-to-text"
        headers = {"xi-api-key": self._el_key}
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {"model_id": "scribe_v1"}

        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(url, headers=headers, files=files, data=data)
                if r.status_code == 401:
                    try:
                        detail = r.json().get("detail", {})
                        if isinstance(detail, dict) and detail.get("code") == "quota_exceeded":
                            raise ElevenLabsQuotaError(detail.get("message", "ElevenLabs quota exhausted"))
                    except (ValueError, AttributeError):
                        pass
                r.raise_for_status()
                return r.json().get("text", "").strip()
        except ElevenLabsQuotaError:
            raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            logger.error(f"ElevenLabs Scribe transcription failed: {e}")
            return ""

    async def _send_audio(self, pcm_bytes: bytes):
        """Send raw PCM 16kHz mono audio via the blocking VirtualMicrophoneDevice."""
        if not self._mic:
            return
        # write_frames requires whole 16-bit samples (even byte length)
        if len(pcm_bytes) % 2 != 0:
            pcm_bytes = pcm_bytes[:-1]
        # Write directly from the event-loop thread (daily devices are
        # thread-affine; writing from a worker thread silently injects nothing).
        # Non-blocking buffers internally and clocks out in real-time.
        self._mic.write_frames(pcm_bytes)
        # Let the device clock out the audio in real-time before returning.
        await asyncio.sleep(len(pcm_bytes) / BYTES_PER_SEC + 0.3)
