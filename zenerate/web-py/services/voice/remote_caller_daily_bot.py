"""
Synthetic caller for a remote ElevenLabs Conversational AI agent,
with a Daily.co room relay so a human observer can listen live.

Architecture:
- ElevenLabs WebSocket: same protocol as ScenarioRemoteCallerBot
  (user_audio_chunk -> agent -> agent_response + audio_event)
- Daily.co relay: the bot joins a pre-created room with a VirtualMicrophoneDevice
  and writes both caller TTS audio and ElevenLabs agent audio to that mic so
  observers joining the room URL can hear the full conversation in real time.

The Daily room is created by POST /remote/connect before this bot runs.
Daily.init() has already been called by caller_server.py at startup.
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

GREETING_TIMEOUT = 12.0
RESPONSE_TIMEOUT = 30.0
COLLECT_WINDOW = 20.0
SILENCE_GAP = 1.2
SEND_FRAME_BYTES = 8000   # 250 ms at 16 kHz mono 16-bit
TRAILING_SILENCE_BYTES = 16000   # 500 ms end-of-turn padding


def _detail_status(resp) -> str:
    try:
        detail = resp.json().get("detail", {})
        if isinstance(detail, dict):
            return detail.get("status", "") or detail.get("message", "")
    except (ValueError, AttributeError):
        pass
    return ""


class ScenarioRemoteCallerDailyBot:
    """
    Like ScenarioRemoteCallerBot but also joins a pre-created Daily.co room and
    mirrors both sides of the conversation to it so observers can listen live.

    Caller audio (TTS) and agent audio (from ElevenLabs WS) are both written to
    a single VirtualMicrophoneDevice. Observers joining the room_url hear a mixed
    mono stream of the full conversation in near-real-time.
    """

    def __init__(
        self,
        el_agent_id: str,
        steps: list[dict],
        room_url: str,
        room_token: str,
        agent_api_key: str = "",
        dynamic_variables: dict | None = None,
        tts_api_key: str = "",
        caller_voice_id: str = CALLER_DEFAULT_VOICE_ID,
        recording_id: str = "",
        judge=None,
    ):
        self.el_agent_id = el_agent_id
        self.steps = steps
        self.room_url = room_url
        self.room_token = room_token
        self._dynamic_variables = dynamic_variables or {}
        self.judge = judge
        self._agent_key = agent_api_key
        self._tts_key = tts_api_key or agent_api_key
        self.caller_voice_id = caller_voice_id or CALLER_DEFAULT_VOICE_ID
        self.recording_id = recording_id

        self._ws = None
        self._call_start_ts: float = 0.0
        self._caller_done_ts: float = 0.0
        self._transcript: list[dict] = []
        self._caller_frames: list[tuple[float, bytes]] = []
        self._agent_frames: list[tuple[float, bytes]] = []
        self._meta: dict = {}
        self._agent_text: str = ""
        self._agent_audio_started: bool = False
        self._agent_speech_start_ts: float = 0.0
        self._last_agent_audio_ts: float = 0.0

        self.recording_file: str | None = None
        self.closed_reason: str = ""

        # Daily relay state
        self._mic = None
        self._call_client = None
        self._device_id = uuid.uuid4().hex[:8]

    # ------------------------------------------------------------------ Daily relay

    def _setup_daily(self):
        """Join the Daily room as a relay participant (synchronous setup)."""
        from daily import Daily, CallClient, EventHandler

        class Handler(EventHandler):
            def on_call_state_updated(self, state):
                logger.info("Daily relay state: %s", state)
            def on_error(self, message):
                logger.error("Daily relay error: %s", message)

        mic_name = f"relay-mic-{self._device_id}"
        self._mic = Daily.create_microphone_device(
            mic_name, sample_rate=16000, channels=1, non_blocking=True
        )
        self._call_client = CallClient(event_handler=Handler())
        self._call_client.join(
            self.room_url,
            meeting_token=self.room_token,
            client_settings={
                "inputs": {
                    "microphone": {"isEnabled": True, "settings": {"deviceId": mic_name}},
                    "camera": {"isEnabled": False},
                }
            },
        )
        logger.info("Daily relay joined room %s", self.room_url)

    def _teardown_daily(self):
        if self._call_client:
            try:
                self._call_client.leave()
            except Exception:
                pass

    def _relay_to_daily(self, pcm: bytes):
        """Write PCM bytes to the Daily mic device.
        Non-blocking — the Daily SDK clocks audio out to the room in real-time.
        Must be called from the asyncio event-loop thread (daily devices are thread-affine).
        """
        if not self._mic or not pcm:
            return
        if len(pcm) % 2:
            pcm = pcm[:-1]
        try:
            self._mic.write_frames(pcm)
        except Exception as e:
            logger.warning("Daily relay write_frames: %s", e)

    # ------------------------------------------------------------------ ElevenLabs WebSocket

    async def _resolve_ws_url(self) -> str:
        """Get a signed WebSocket URL for private agents; fall back to public URL."""
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
                        "Signed-URL unavailable (%s %s); falling back to public agent URL",
                        r.status_code, _detail_status(r),
                    )
                    return public_url
                r.raise_for_status()
                return r.json()["signed_url"]
        except (httpx.HTTPError, KeyError) as e:
            logger.warning("Signed-URL fetch failed (%s); falling back", e)
            return public_url

    async def run(self) -> list[dict]:
        self._setup_daily()
        url = await self._resolve_ws_url()
        recv_task = None
        try:
            async with websockets.connect(url, max_size=32 * 1024 * 1024) as ws:
                self._ws = ws
                self._call_start_ts = time.monotonic()
                recv_task = asyncio.create_task(self._receive_loop())
                if self.judge:
                    self.judge.start()

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
                    self.closed_reason = getattr(e, "reason", "") or str(e)
                    logger.warning("Agent WS closed mid-call: %s", self.closed_reason)
        finally:
            if self.judge:
                await self.judge.stop()
            if recv_task is not None:
                recv_task.cancel()
                try:
                    await recv_task
                except (asyncio.CancelledError, Exception):
                    pass
            self._teardown_daily()
            self.recording_file = write_mixed_wav(
                self.recording_id, self._caller_frames, self._agent_frames
            )

        return self._transcript

    # ------------------------------------------------------------- receive loop

    async def _receive_loop(self):
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
            self._meta = msg.get("conversation_initiation_metadata_event", {})
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
            # Mirror to Daily so observers hear the agent in real-time
            self._relay_to_daily(pcm)
            return

        if mtype == "agent_response":
            text = msg.get("agent_response_event", {}).get("agent_response", "")
            if text:
                self._agent_text = (
                    (self._agent_text + " " + text).strip() if self._agent_text else text.strip()
                )
            return

        if mtype == "interruption":
            return

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
                if self.judge:
                    self.judge.submit(self._transcript)

    async def _silence_keepalive(self):
        """Continuously send silence so ElevenLabs server-side VAD detects end-of-turn."""
        frame = base64.b64encode(b"\x00" * SEND_FRAME_BYTES).decode("ascii")
        try:
            while True:
                await self._ws.send(json.dumps({"user_audio_chunk": frame}))
                await asyncio.sleep(SEND_FRAME_BYTES / BYTES_PER_SEC)
        except (asyncio.CancelledError, websockets.ConnectionClosed):
            return

    async def _send_caller_audio(self, pcm: bytes):
        """Stream caller TTS to ElevenLabs WS in real-time chunks.
        Also writes the full PCM to the Daily relay mic upfront — Daily's non-blocking
        device buffers it internally and clocks it out at the natural rate.
        """
        if len(pcm) % 2:
            pcm = pcm[:-1]
        # Write full caller audio to Daily relay (buffered; clocks out in real-time)
        self._relay_to_daily(pcm)
        # Stream to ElevenLabs paced at real-time so server VAD sees natural speech
        for i in range(0, len(pcm), SEND_FRAME_BYTES):
            frame = pcm[i: i + SEND_FRAME_BYTES]
            await self._ws.send(
                json.dumps({"user_audio_chunk": base64.b64encode(frame).decode("ascii")})
            )
            await asyncio.sleep(len(frame) / BYTES_PER_SEC)
        silence = b"\x00" * TRAILING_SILENCE_BYTES
        await self._ws.send(
            json.dumps({"user_audio_chunk": base64.b64encode(silence).decode("ascii")})
        )

    async def _collect_agent_turn(self, start_timeout: float, is_greeting: bool = False) -> str:
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
