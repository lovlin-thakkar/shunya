"""
Eval agent for testing remote ElevenLabs Conversational AI agents.

EvalAgent is a plain async class (no Pipecat BaseWorker / WorkerRunner). The
previous WorkerRunner-based implementation was dropped because:
  - self.job() / send_job_response do not exist on BaseWorker → scoring silently
    never ran (AttributeError swallowed by the outer try/except)
  - on_activated() returned before _run() finished → run_eval_agent() could
    return empty results before the call completed

Current architecture:
  - EvalAgent._run() is awaited directly
  - ScoringSubAgents are plain async objects; _score() is called directly
  - All rubric fields are scored concurrently via asyncio.gather, then ALL
    results are posted to Django in a single request (avoids the race where
    concurrent per-field POSTs overwrote each other in LiveScoresView)
"""

import asyncio
import base64
import json
import logging
import os
import re
import time
import uuid

import httpx
import websockets
from anthropic import AsyncAnthropic

from audio_utils import synthesize_tts, write_mixed_wav, BYTES_PER_SEC, ElevenLabsQuotaError
from config import CALLER_DEFAULT_VOICE_ID

logger = logging.getLogger(__name__)

CONVAI_WS_BASE = "wss://api.elevenlabs.io/v1/convai/conversation"
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"
SEND_FRAME_BYTES = 8000
TRAILING_SILENCE_BYTES = 16000
GREETING_TIMEOUT = 12.0
RESPONSE_TIMEOUT = 30.0
COLLECT_WINDOW = 20.0
# Normal agent turn: exit after this much trailing silence.
SILENCE_GAP = 1.5
# Greeting: ElevenLabs TTS has natural inter-sentence pauses of 1.5–2.5s;
# a too-short gap exits mid-greeting and causes the first caller turn to
# overlap with the second half of the greeting in the WAV recording.
GREETING_SILENCE_GAP = 2.5

LIVE_MODEL = "claude-sonnet-4-6"
PASS_THRESHOLD = 0.7

SCORE_SYSTEM_PROMPT = (
    "You are a live QA scorer for a voice AI agent under test. Given the "
    "conversation so far, score the AGENT (not the caller) on each rubric "
    "dimension from 0.0 (fail) to 1.0 (pass). Judge only what is observable "
    "so far. Return ONLY a JSON object, no prose, no markdown fences."
)


class Scorer:
    """Scores one or more rubric fields against a transcript via Anthropic."""

    def __init__(self, anthropic_api_key: str, persona: str = ""):
        self._client = (
            AsyncAnthropic(api_key=anthropic_api_key) if anthropic_api_key else None
        )
        self._persona = persona or ""

    async def score(self, transcript: list[dict], fields: list[str]) -> dict:
        if not self._client or not fields:
            return {}
        convo = "\n".join(
            f"{t.get('speaker', '?').upper()}: {t.get('text', '')}" for t in transcript
        )
        user = (
            f"Caller persona: {self._persona}\n\n"
            f"Dimensions to score: {', '.join(fields)}\n\n"
            f"Conversation so far:\n{convo}\n\n"
            'Return JSON: {"<dimension>": {"score": 0.0, "reason": "<=10 words"}, ...}'
        )
        try:
            resp = await self._client.messages.create(
                model=LIVE_MODEL,
                max_tokens=400,
                system=SCORE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user}],
            )
            text = resp.content[0].text if resp.content else "{}"
            return _parse_json(text)
        except Exception as e:
            logger.warning("Scoring failed: %s", e)
            return {}


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except (ValueError, TypeError):
                return {}
        return {}


class EvalBridge:
    """Joins a Daily room as "Shunya Eval" and pushes raw PCM audio to it.

    Uses raw ``daily.CallClient`` + virtual microphone device (matching the
    pattern in ``caller_bot.py``) instead of ``DailyTransport``, because
    ``Daily.init()`` is already called by ``caller_server.py`` at module load
    time — a second call from ``DailyTransport`` would panic.
    """

    def __init__(self, room_url: str, room_token: str, device_tag: str = ""):
        self.room_url = room_url
        self.room_token = room_token
        self._device_tag = device_tag or uuid.uuid4().hex[:8]
        self._call_client = None
        self._mic = None
        self._joined = asyncio.Event()

    async def join(self):
        from daily import CallClient, Daily, EventHandler

        bridge = self
        # Capture the running event loop so the Daily callback thread can
        # safely signal it (asyncio.Event.set() is not thread-safe).
        loop = asyncio.get_running_loop()

        class Handler(EventHandler):
            def on_call_state_updated(self, state):
                if state == "joined":
                    loop.call_soon_threadsafe(bridge._joined.set)

            def on_error(self, message):
                logger.error("EvalBridge Daily error: %s", message)

        mic_name = f"eval-mic-{self._device_tag}"
        self._mic = Daily.create_microphone_device(
            mic_name,
            sample_rate=16000,
            channels=1,
            non_blocking=True,
        )
        self._call_client = CallClient(event_handler=Handler())
        self._call_client.join(
            self.room_url,
            meeting_token=self.room_token,
            client_settings={
                "inputs": {
                    "microphone": {
                        "isEnabled": True,
                        "settings": {"deviceId": mic_name},
                    },
                    "camera": {"isEnabled": False},
                },
            },
        )
        await asyncio.wait_for(self._joined.wait(), timeout=15)

    def send_audio(self, pcm: bytes):
        """Write PCM to the Daily mic device (non-blocking; clocked out in real-time)."""
        if self._mic and pcm:
            if len(pcm) % 2:
                pcm = pcm[:-1]
            try:
                self._mic.write_frames(pcm)
            except Exception as e:
                logger.warning("EvalBridge write_frames: %s", e)

    async def leave(self):
        if self._call_client:
            try:
                self._call_client.leave()
            except Exception:
                pass
            self._call_client = None


class EvalAgent:
    """Orchestrates a remote ElevenLabs agent test run.

    Lifecycle:
      1. Joins the Daily room (if room_url provided) — observers can listen live
      2. Connects to ElevenLabs Conversational AI WebSocket
      3. Collects agent greeting
      4. Drives scenario steps (TTS → WS + Daily room)
      5. After each agent turn: scores all rubric fields concurrently, posts
         aggregated results to Django in one atomic update
      6. Writes mixed-mono WAV recording
    """

    def __init__(
        self,
        el_agent_id: str,
        steps: list[dict],
        room_url: str = "",
        room_token: str = "",
        agent_api_key: str = "",
        tts_api_key: str = "",
        dynamic_variables: dict | None = None,
        caller_voice_id: str = CALLER_DEFAULT_VOICE_ID,
        recording_id: str = "",
        run_id: str = "",
        tenant_id: str = "",
        rubric: dict | None = None,
        django_url: str = "",
        service_token: str = "",
    ):
        self.el_agent_id = el_agent_id
        self.steps = steps
        self.room_url = room_url
        self.room_token = room_token
        self._agent_key = agent_api_key
        self._tts_key = tts_api_key or agent_api_key
        self._dynamic_variables = dynamic_variables or {}
        self._caller_voice_id = caller_voice_id or CALLER_DEFAULT_VOICE_ID
        self._recording_id = recording_id
        self._run_id = run_id
        self._tenant_id = str(tenant_id) if tenant_id else ""
        self._rubric = rubric or {}
        self._django_url = django_url.rstrip("/") if django_url else ""
        self._service_token = service_token or ""

        self._bridge: EvalBridge | None = None
        self._scorer: Scorer | None = None
        self._fields: list[str] = []

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._call_start_ts: float = 0.0
        self._transcript: list[dict] = []
        self._caller_frames: list[tuple[float, bytes]] = []
        self._agent_frames: list[tuple[float, bytes]] = []

        self._agent_text: str = ""
        self._agent_audio_started: bool = False
        self._agent_speech_start_ts: float = 0.0
        self._last_agent_audio_ts: float = 0.0
        self._caller_done_ts: float = 0.0

        self.recording_file: str | None = None
        self.closed_reason: str = ""

    # -- entry point --------------------------------------------------------

    async def run(self) -> dict:
        try:
            self._fields = (
                list(self._rubric.keys())
                if self._rubric
                else ["instruction_following", "goal_completion", "csat_tone", "safety"]
            )
            persona = self.steps[0].get("persona", "") if self.steps else ""
            anthro_key = os.environ.get("ANTHROPIC_API_KEY", "")
            self._scorer = Scorer(anthro_key, persona=persona)

            if self.room_url and self.room_token:
                self._bridge = EvalBridge(
                    self.room_url, self.room_token, device_tag=uuid.uuid4().hex[:6]
                )
                await self._bridge.join()
            else:
                logger.info("No Daily room — running WS-only (no live listen-in)")

            ws_url = await self._resolve_ws_url()
            async with websockets.connect(ws_url, max_size=32 * 1024 * 1024) as ws:
                self._ws = ws
                self._call_start_ts = time.monotonic()
                recv_task = asyncio.create_task(self._receive_loop())

                init_msg: dict = {"type": "conversation_initiation_client_data"}
                if self._dynamic_variables:
                    init_msg["dynamic_variables"] = self._dynamic_variables
                await ws.send(json.dumps(init_msg))

                greeting = await self._collect_agent_turn(
                    start_timeout=GREETING_TIMEOUT, is_greeting=True
                )
                if greeting:
                    self._append_agent_turn(greeting)
                    logger.info("Agent greeting: %s", greeting[:60])

                try:
                    await self._speak_loop()
                except websockets.ConnectionClosed as e:
                    self.closed_reason = getattr(e, "reason", "") or str(e)
                    logger.warning("Agent WS closed mid-call: %s", self.closed_reason)

                recv_task.cancel()
                try:
                    await recv_task
                except (asyncio.CancelledError, Exception):
                    pass

        except ElevenLabsQuotaError:
            # Re-raise quota errors so caller_server returns 500 → Celery marks
            # the TestRun as failed. Continuing with empty transcript is misleading.
            raise
        except Exception as e:
            logger.exception("Eval agent failed: %s", e)
        finally:
            if self._bridge:
                await self._bridge.leave()
            self.recording_file = write_mixed_wav(
                self._recording_id, self._caller_frames, self._agent_frames
            )

        return {
            "transcript": self._transcript,
            "recording_file": self.recording_file,
            "closed_reason": self.closed_reason,
        }

    # -- ElevenLabs WebSocket -----------------------------------------------

    async def _resolve_ws_url(self) -> str:
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
                    return public_url
                r.raise_for_status()
                return r.json()["signed_url"]
        except (httpx.HTTPError, KeyError) as e:
            logger.warning("Signed-URL failed (%s); fallback to public", e)
            return public_url

    async def _receive_loop(self):
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                mtype = msg.get("type")
                if mtype == "conversation_initiation_metadata":
                    continue
                if mtype == "ping":
                    eid = msg.get("ping_event", {}).get("event_id")
                    await self._ws.send(json.dumps({"type": "pong", "event_id": eid}))
                    continue
                if mtype == "audio":
                    b64 = msg.get("audio_event", {}).get("audio_base_64", "")
                    if not b64:
                        continue
                    pcm = base64.b64decode(b64)
                    now = time.monotonic()
                    self._agent_frames.append((now - self._call_start_ts, pcm))
                    self._last_agent_audio_ts = now
                    if not self._agent_audio_started:
                        self._agent_audio_started = True
                        self._agent_speech_start_ts = now
                    if self._bridge:
                        self._bridge.send_audio(pcm)
                    continue
                if mtype == "agent_response":
                    text = msg.get("agent_response_event", {}).get("agent_response", "")
                    if text:
                        self._agent_text = (
                            (self._agent_text + " " + text).strip()
                            if self._agent_text
                            else text.strip()
                        )
                    continue
                if mtype == "interruption":
                    continue
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            return

    # -- scenario driving ---------------------------------------------------

    async def _speak_loop(self):
        for step in self.steps:
            clean = step.get("text", step.get("raw", ""))
            quirks = [q.get("tag", "") for q in step.get("quirks", [])]

            caller_ts_ms = int((time.monotonic() - self._call_start_ts) * 1000)
            self._transcript.append(
                {"speaker": "caller", "text": clean, "ts_ms": caller_ts_ms, "quirks": quirks}
            )
            logger.info("Caller at +%dms: %s", caller_ts_ms, clean[:60])

            self._reset_agent_turn()

            audio = await synthesize_tts(clean, self._caller_voice_id, self._tts_key)
            if audio:
                caller_offset = time.monotonic() - self._call_start_ts
                self._caller_frames.append((caller_offset, audio))
                await self._send_caller_audio(audio)
            else:
                logger.warning("No audio for step: %s", clean[:40])
            self._caller_done_ts = time.monotonic()

            # Keep sending silence so ElevenLabs server-side VAD sees sustained
            # end-of-turn and fires a response even on slow calls.
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
                await self._dispatch_scoring()

    async def _send_caller_audio(self, pcm: bytes):
        """Stream caller PCM to ElevenLabs WS and mirror to the Daily relay."""
        if not self._ws:
            return
        # Write full audio to Daily relay upfront — the non-blocking mic device
        # buffers it and clocks it out in real-time, staying in sync with the WS pacing.
        if self._bridge:
            self._bridge.send_audio(pcm)
        # Pace frames to ElevenLabs in real-time so server-side VAD perceives natural speech.
        for i in range(0, len(pcm), SEND_FRAME_BYTES):
            frame = pcm[i: i + SEND_FRAME_BYTES]
            await self._ws.send(
                json.dumps({"user_audio_chunk": base64.b64encode(frame).decode("ascii")})
            )
            await asyncio.sleep(len(frame) / BYTES_PER_SEC)
        await self._ws.send(
            json.dumps(
                {"user_audio_chunk": base64.b64encode(b"\x00" * TRAILING_SILENCE_BYTES).decode("ascii")}
            )
        )

    async def _silence_keepalive(self):
        """Send silence frames to ElevenLabs WS while waiting for the agent to respond.
        This ensures server-side VAD consistently fires even on slow-responding agents."""
        frame = base64.b64encode(b"\x00" * SEND_FRAME_BYTES).decode("ascii")
        try:
            while True:
                if self._ws:
                    await self._ws.send(json.dumps({"user_audio_chunk": frame}))
                await asyncio.sleep(SEND_FRAME_BYTES / BYTES_PER_SEC)
        except (asyncio.CancelledError, websockets.ConnectionClosed):
            return

    async def _collect_agent_turn(
        self, start_timeout: float, is_greeting: bool = False
    ) -> str:
        # Check if the agent already responded during the TTS synthesis / audio send
        # phase (fast agents can respond before we even reach this method). Snapshot
        # the value before clearing so a real early response is not discarded.
        snapshot = self._agent_text.strip()
        self._agent_text = ""
        if snapshot and not is_greeting:
            logger.info("Agent responded during caller audio phase — using early response")
            return snapshot

        deadline = time.monotonic() + start_timeout
        while time.monotonic() < deadline:
            ready = (
                (self._agent_audio_started or self._agent_text)
                if is_greeting
                else bool(self._agent_text)
            )
            if ready:
                break
            await asyncio.sleep(0.05)
        else:
            if not is_greeting:
                logger.warning("Timed out waiting for agent response")
            return ""

        # Use a wider silence gap for the greeting: ElevenLabs TTS produces natural
        # inter-sentence pauses of 1.5–2.5s, so 1.2s exits mid-greeting and causes
        # the first caller turn to overlap with the trailing greeting audio in the recording.
        gap = GREETING_SILENCE_GAP if is_greeting else SILENCE_GAP
        collect_deadline = time.monotonic() + COLLECT_WINDOW
        while time.monotonic() < collect_deadline:
            await asyncio.sleep(0.1)
            quiet_for = time.monotonic() - self._last_agent_audio_ts
            if self._agent_audio_started and quiet_for > gap:
                break

        return self._agent_text.strip()

    # -- scoring ------------------------------------------------------------

    async def _dispatch_scoring(self):
        """Score all rubric fields concurrently, then POST all results in one request.

        Scoring per field is concurrent (asyncio.gather) but the final POST is a single
        call with all fields — avoiding the race where per-field POSTs overwrote each
        other in LiveScoresView.
        """
        if not self._scorer or not self._fields:
            return
        snapshot = list(self._transcript)

        # Score each field independently so partial failures don't block others.
        results = await asyncio.gather(
            *[self._scorer.score(snapshot, [field]) for field in self._fields],
            return_exceptions=True,
        )

        # Merge all field results into one dict.
        merged: dict = {}
        for res in results:
            if isinstance(res, dict):
                merged.update(res)

        if merged:
            await self._post_scores(merged)

    async def _post_scores(self, scores: dict):
        if not self._run_id or not self._django_url:
            return
        turn = len([t for t in self._transcript if t["speaker"] == "agent"])
        normalized = []
        for field, entry in scores.items():
            if not isinstance(entry, dict):
                continue
            try:
                score = max(0.0, min(1.0, float(entry.get("score", 0.0))))
            except (TypeError, ValueError):
                continue
            normalized.append(
                {
                    "field": field,
                    "score": round(score, 2),
                    "reasoning": str(entry.get("reason", ""))[:200],
                    "passed": score >= PASS_THRESHOLD,
                }
            )
        if not normalized:
            return
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                await c.post(
                    f"{self._django_url}/internal/test-runs/{self._run_id}/live-scores/",
                    json={"turn": turn, "scores": normalized},
                    headers={
                        "X-Service-Token": self._service_token,
                        "X-Tenant-Id": self._tenant_id,
                    },
                )
        except httpx.HTTPError as e:
            logger.warning("Score post failed: %s", e)

    # -- helpers ------------------------------------------------------------

    def _append_agent_turn(self, text: str):
        start = self._agent_speech_start_ts or time.monotonic()
        ts = int((start - self._call_start_ts) * 1000)
        self._transcript.append({"speaker": "agent", "text": text, "ts_ms": ts, "quirks": []})

    def _reset_agent_turn(self):
        self._agent_text = ""
        self._agent_audio_started = False
        self._agent_speech_start_ts = 0.0
        self._last_agent_audio_ts = 0.0


async def run_eval_agent(
    el_agent_id: str,
    steps: list[dict],
    room_url: str = "",
    room_token: str = "",
    agent_api_key: str = "",
    tts_api_key: str = "",
    dynamic_variables: dict | None = None,
    caller_voice_id: str = CALLER_DEFAULT_VOICE_ID,
    recording_id: str = "",
    run_id: str = "",
    tenant_id: str = "",
    rubric: dict | None = None,
    django_url: str = "",
    service_token: str = "",
) -> dict:
    agent = EvalAgent(
        el_agent_id=el_agent_id,
        steps=steps,
        room_url=room_url,
        room_token=room_token,
        agent_api_key=agent_api_key,
        tts_api_key=tts_api_key,
        dynamic_variables=dynamic_variables,
        caller_voice_id=caller_voice_id,
        recording_id=recording_id,
        run_id=run_id,
        tenant_id=tenant_id,
        rubric=rubric,
        django_url=django_url,
        service_token=service_token,
    )
    return await agent.run()
