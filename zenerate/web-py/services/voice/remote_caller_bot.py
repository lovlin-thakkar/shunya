"""
Synthetic caller for a *remote* ElevenLabs Conversational AI agent.

Unlike ScenarioCallerBot (which joins a Daily room shared with a Pipecat agent),
this bot talks directly to a customer's deployed ElevenLabs agent over the
Conversational AI WebSocket:

    wss://api.elevenlabs.io/v1/convai/conversation?agent_id=<id>

For each scenario step it synthesises caller speech with ElevenLabs TTS, streams
it to the agent as `user_audio_chunk` frames, then collects the agent's audio
(for the recording) and the agent's `agent_response` text (for the transcript —
no Scribe pass needed, the platform hands us the text directly).

Audio format assumption: the agent must be configured for pcm_16000 input AND
output. That is the ElevenLabs default for the WS interface; if a customer's
agent uses ulaw_8000 the recording will be garbled and we'd need to transcode.

Protocol references handled below: conversation_initiation_metadata, ping/pong,
audio, agent_response, user_transcript, interruption.
"""
import asyncio
import base64
import json
import logging
import time
import uuid

import httpx
import websockets

from audio_utils import (
    ELEVENLABS_API_URL,
    BYTES_PER_SEC,
    synthesize_tts,
    write_mixed_wav,
)
from config import CALLER_DEFAULT_VOICE_ID

logger = logging.getLogger(__name__)

CONVAI_WS_BASE = "wss://api.elevenlabs.io/v1/convai/conversation"


def _detail_status(resp) -> str:
    """Best-effort extract of ElevenLabs' {"detail": {"status": ...}} reason."""
    try:
        detail = resp.json().get("detail", {})
        if isinstance(detail, dict):
            return detail.get("status", "") or detail.get("message", "")
    except (ValueError, AttributeError):
        pass
    return ""

# Wait up to this long for the agent's opening greeting before sending step 1.
GREETING_TIMEOUT = 12.0
# Per agent turn: max seconds to wait for the agent to start responding.
RESPONSE_TIMEOUT = 30.0
# Max seconds to keep collecting one agent turn once it has started.
COLLECT_WINDOW = 20.0
# Agent turn is considered finished after this much trailing silence.
SILENCE_GAP = 1.2
# Caller audio is streamed in ~250 ms frames so the agent's VAD perceives
# natural speech rather than one instantaneous blob.
SEND_FRAME_BYTES = 8000  # 250 ms at 16 kHz mono 16-bit
# Trailing silence appended after each caller turn so the agent's end-of-turn
# VAD fires reliably (absence of frames alone is a weaker signal).
TRAILING_SILENCE_BYTES = 16000  # 500 ms


class ScenarioRemoteCallerBot:
    def __init__(
        self,
        el_agent_id: str,
        steps: list[dict],
        agent_api_key: str = "",
        dynamic_variables: dict | None = None,
        tts_api_key: str = "",
        caller_voice_id: str = CALLER_DEFAULT_VOICE_ID,
        recording_id: str = "",
        judge=None,
    ):
        self.el_agent_id = el_agent_id
        self.steps = steps
        self._dynamic_variables = dynamic_variables or {}
        # Optional during-call judge sub-agent (scores turns live; see judge_subagent).
        self.judge = judge
        # Tenant key → reach/sign the agent under test. Platform key → caller TTS.
        # Fall back to the agent key for TTS if no platform key was provided.
        self._agent_key = agent_api_key
        self._tts_key = tts_api_key or agent_api_key
        self.caller_voice_id = caller_voice_id or CALLER_DEFAULT_VOICE_ID
        self.recording_id = recording_id

        self._ws = None
        self._call_start_ts: float = 0.0
        self._caller_done_ts: float = 0.0

        # Transcript turns: {speaker, text, ts_ms, quirks}
        self._transcript: list[dict] = []

        # Real-time capture for the mixed recording: (offset_secs, pcm)
        self._caller_frames: list[tuple[float, bytes]] = []
        self._agent_frames: list[tuple[float, bytes]] = []

        # conversation_initiation_metadata: the agent's declared audio formats etc.
        self._meta: dict = {}

        # Per-turn agent state, mutated by the receive loop (single asyncio thread)
        self._agent_text: str = ""
        self._agent_audio_started: bool = False
        self._agent_speech_start_ts: float = 0.0
        self._last_agent_audio_ts: float = 0.0

        self.recording_file: str | None = None
        # Set if ElevenLabs closes the WS mid-call (e.g. agent technical issues).
        self.closed_reason: str = ""

    # ------------------------------------------------------------------ connect

    async def _resolve_ws_url(self) -> str:
        """Prefer a signed WS URL (required for private agents). Fall back to the
        public agent URL when signing is unavailable — e.g. the agent is public
        (no signing needed) or the key lacks convai scope. The WS connect itself
        is then the source of truth: a private agent will simply be rejected."""
        public_url = f"{CONVAI_WS_BASE}?agent_id={self.el_agent_id}"
        if not self._agent_key:
            return public_url
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(
                    f"{ELEVENLABS_API_URL}/convai/conversation/get-signed-url",
                    params={"agent_id": self.el_agent_id},
                    headers={"xi-api-key": self._agent_key},
                )
                if r.status_code in (401, 403):
                    logger.warning(
                        "Signed-URL unavailable (%s %s); falling back to public agent URL. "
                        "If this agent is private, grant the API key convai_read/convai_write.",
                        r.status_code, _detail_status(r),
                    )
                    return public_url
                r.raise_for_status()
                return r.json()["signed_url"]
        except (httpx.HTTPError, KeyError) as e:
            logger.warning("Signed-URL fetch failed (%s); falling back to public agent URL", e)
            return public_url

    async def run(self) -> list[dict]:
        url = await self._resolve_ws_url()
        recv_task = None
        try:
            async with websockets.connect(url, max_size=32 * 1024 * 1024) as ws:
                self._ws = ws
                self._call_start_ts = time.monotonic()
                recv_task = asyncio.create_task(self._receive_loop())
                if self.judge:
                    self.judge.start()

                # Signal readiness so the agent emits its opening line promptly
                # (without this the greeting can lag ~12s and overlap step 1).
                init_msg: dict = {"type": "conversation_initiation_client_data"}
                if self._dynamic_variables:
                    init_msg["dynamic_variables"] = self._dynamic_variables
                await ws.send(json.dumps(init_msg))

                try:
                    greeting = await self._collect_agent_turn(
                        start_timeout=GREETING_TIMEOUT, is_greeting=True
                    )
                    if greeting:
                        self._append_agent_turn(greeting)
                        logger.info("Agent greeting captured: %s", greeting[:60])

                    await self._speak_loop()
                except websockets.ConnectionClosed as e:
                    # ElevenLabs closed the socket mid-call — commonly because the
                    # agent under test errored ("technical issues"). That is a real
                    # QA signal, not a harness crash: keep the partial transcript +
                    # recording and let the judge score the truncated conversation.
                    self.closed_reason = getattr(e, "reason", "") or str(e)
                    logger.warning("Agent connection closed mid-conversation: %s", self.closed_reason)
        finally:
            if self.judge:
                await self.judge.stop()
            if recv_task is not None:
                recv_task.cancel()
                try:
                    await recv_task
                except (asyncio.CancelledError, Exception):
                    pass
            self.recording_file = write_mixed_wav(
                self.recording_id, self._caller_frames, self._agent_frames
            )

        return self._transcript

    # ------------------------------------------------------------- receive loop

    async def _receive_loop(self):
        """Handle every inbound WS message until the socket closes/cancels."""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                await self._handle_message(msg)
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            return

    async def _handle_message(self, msg: dict):
        mtype = msg.get("type")

        if mtype == "conversation_initiation_metadata":
            ev = msg.get("conversation_initiation_metadata_event", {})
            self._meta = ev
            logger.info(
                "convai init: conversation_id=%s user_input_format=%s agent_output_format=%s",
                ev.get("conversation_id"),
                ev.get("user_input_audio_format"),
                ev.get("agent_output_audio_format"),
            )
            return

        if mtype == "ping":
            event_id = msg.get("ping_event", {}).get("event_id")
            await self._ws.send(json.dumps({"type": "pong", "event_id": event_id}))
            return

        if mtype == "audio":
            b64 = msg.get("audio_event", {}).get("audio_base_64", "")
            if not b64:
                return
            pcm = base64.b64decode(b64)
            now = time.monotonic()
            self._agent_frames.append((now - self._call_start_ts, pcm))
            self._last_agent_audio_ts = now
            if not self._agent_audio_started:
                self._agent_audio_started = True
                self._agent_speech_start_ts = now
            return

        if mtype == "agent_response":
            text = msg.get("agent_response_event", {}).get("agent_response", "")
            if text:
                # Concatenate in case the platform sends it in pieces.
                self._agent_text = (self._agent_text + " " + text).strip() if self._agent_text else text.strip()
            return

        if mtype == "interruption":
            # Agent was interrupted; drop any partial audio captured so far for
            # this turn so timing/transcript stay consistent.
            logger.info("Agent interruption event")
            return

        # user_transcript, agent_response_correction, vad_score, client_tool_call,
        # conversation_initiation_metadata — not needed for our transcript.

    # ------------------------------------------------------------- speak / drive

    async def _speak_loop(self):
        for step in self.steps:
            clean = step.get("text", step.get("raw", ""))
            quirks = [q.get("tag", "") for q in step.get("quirks", [])]

            caller_ts_ms = int((time.monotonic() - self._call_start_ts) * 1000)
            self._transcript.append(
                {"speaker": "caller", "text": clean, "ts_ms": caller_ts_ms, "quirks": quirks}
            )
            logger.info("Caller speaking at +%dms: %s", caller_ts_ms, clean[:60])

            self._reset_agent_turn()

            audio = await synthesize_tts(clean, self.caller_voice_id, self._tts_key)
            if audio:
                caller_offset = time.monotonic() - self._call_start_ts
                self._caller_frames.append((caller_offset, audio))
                await self._send_caller_audio(audio)
            else:
                logger.warning("No audio synthesised for step")
            self._caller_done_ts = time.monotonic()

            # Hold the mic "open" with silence while waiting. ElevenLabs uses
            # server-side VAD on the incoming stream to detect end-of-user-turn;
            # if we simply stop sending audio it keeps waiting for more and never
            # responds. Continuous silence makes the VAD fire and the agent reply.
            keepalive = asyncio.create_task(self._silence_keepalive())
            try:
                text = await self._collect_agent_turn(start_timeout=RESPONSE_TIMEOUT)
            finally:
                keepalive.cancel()
                try:
                    await keepalive
                except (asyncio.CancelledError, Exception):
                    pass
            if text:
                self._append_agent_turn(text)
                # Hand the running conversation to the judge sub-agent to score live.
                if self.judge:
                    self.judge.submit(self._transcript)

    async def _silence_keepalive(self):
        """Continuously send silence frames so the agent's VAD sees the user
        utterance followed by sustained silence and produces a response."""
        frame = base64.b64encode(b"\x00" * SEND_FRAME_BYTES).decode("ascii")
        try:
            while True:
                await self._ws.send(json.dumps({"user_audio_chunk": frame}))
                await asyncio.sleep(SEND_FRAME_BYTES / BYTES_PER_SEC)
        except (asyncio.CancelledError, websockets.ConnectionClosed):
            return

    async def _send_caller_audio(self, pcm: bytes):
        """Stream caller PCM to the agent in ~250 ms frames, then a short trailing
        silence so the agent's VAD detects end-of-turn."""
        if len(pcm) % 2:
            pcm = pcm[:-1]
        for i in range(0, len(pcm), SEND_FRAME_BYTES):
            frame = pcm[i : i + SEND_FRAME_BYTES]
            await self._ws.send(
                json.dumps({"user_audio_chunk": base64.b64encode(frame).decode("ascii")})
            )
            # Pace roughly to real-time so server-side VAD sees natural speech.
            await asyncio.sleep(len(frame) / BYTES_PER_SEC)
        silence = b"\x00" * TRAILING_SILENCE_BYTES
        await self._ws.send(
            json.dumps({"user_audio_chunk": base64.b64encode(silence).decode("ascii")})
        )

    async def _collect_agent_turn(self, start_timeout: float, is_greeting: bool = False) -> str:
        """Wait for the agent to respond, collect until trailing silence, return text.

        For a normal turn we gate on the ``agent_response`` *text* — the reliable
        "the agent answered" signal. Gating on audio-start alone is unsafe because
        greeting-tail audio from the prior turn bleeds in and would trip an early,
        empty exit. The greeting turn has no prior audio, so audio-start is fine.
        """
        deadline = time.monotonic() + start_timeout
        while time.monotonic() < deadline:
            ready = (self._agent_audio_started or self._agent_text) if is_greeting else bool(self._agent_text)
            if ready:
                break
            await asyncio.sleep(0.05)
        else:
            if not is_greeting:
                logger.warning("Timed out waiting for agent response")
            return ""

        if self._agent_audio_started and not is_greeting:
            latency_ms = int((self._agent_speech_start_ts - self._caller_done_ts) * 1000)
            logger.info("Agent responded — latency %dms", latency_ms)

        collect_deadline = time.monotonic() + COLLECT_WINDOW
        while time.monotonic() < collect_deadline:
            await asyncio.sleep(0.1)
            quiet_for = time.monotonic() - self._last_agent_audio_ts
            if self._agent_audio_started and quiet_for > SILENCE_GAP:
                break

        return self._agent_text.strip()

    def _append_agent_turn(self, text: str):
        # Timestamp from when the agent started speaking (falls back to now).
        start = self._agent_speech_start_ts or time.monotonic()
        agent_ts_ms = int((start - self._call_start_ts) * 1000)
        self._transcript.append(
            {"speaker": "agent", "text": text, "ts_ms": agent_ts_ms, "quirks": []}
        )

    def _reset_agent_turn(self):
        self._agent_text = ""
        self._agent_audio_started = False
        self._agent_speech_start_ts = 0.0
        self._last_agent_audio_ts = 0.0
