"""
Pipecat-powered eval agent for testing remote ElevenLabs Conversational AI agents.

Architecture (WorkerRunner):
  EvalAgent (BaseWorker) — orchestrator, root worker
    ├── EvalBridge (PipelineWorker) — DailyTransport, joins room as "Shunya Eval"
    └── ScoringSubAgent × N (BaseWorker) — concurrent scoring via bus jobs

Replaces remote_caller_daily_bot.py, remote_caller_bot.py, judge_subagent.py.
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
from pipecat.frames.frames import AudioRawFrame
from pipecat.pipeline.base_worker import BaseWorker
from pipecat.pipeline.job_decorator import job
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker, PipelineParams
from pipecat.pipeline.worker_ready_decorator import worker_ready
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.workers.runner import WorkerRunner

from audio_utils import synthesize_tts, write_mixed_wav, BYTES_PER_SEC
from config import CALLER_DEFAULT_VOICE_ID

logger = logging.getLogger(__name__)

CONVAI_WS_BASE = "wss://api.elevenlabs.io/v1/convai/conversation"
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"
SEND_FRAME_BYTES = 8000
TRAILING_SILENCE_BYTES = 16000
GREETING_TIMEOUT = 12.0
RESPONSE_TIMEOUT = 30.0
COLLECT_WINDOW = 20.0
SILENCE_GAP = 1.2

LIVE_MODEL = "claude-haiku-4-5-20251001"
PASS_THRESHOLD = 0.7

SCORE_SYSTEM_PROMPT = (
    "You are a live QA scorer for a voice AI agent under test. Given the "
    "conversation so far, score the AGENT (not the caller) on each rubric "
    "dimension from 0.0 (fail) to 1.0 (pass). Judge only what is observable "
    "so far. Return ONLY a JSON object, no prose, no markdown fences."
)


class ScoringSubAgent(BaseWorker):
    """Bus-based sub-agent that scores rubric dimensions via Anthropic.

    Receives ``score`` jobs from the parent EvalAgent after each agent turn.
    Multiple ScoringSubAgents may run concurrently for different dimensions.
    """

    def __init__(self, name: str, anthropic_api_key: str, persona: str = ""):
        super().__init__(name=name)
        self._client = AsyncAnthropic(api_key=anthropic_api_key) if anthropic_api_key else None
        self._persona = persona or ""

    @job(name="score")
    async def on_score(self, message):
        if not self._client:
            await self.send_job_response(message.job_id, {"error": "no api key"}, status="FAILED")
            return
        fields = message.payload.get("fields", [])
        transcript = message.payload.get("transcript", [])
        try:
            scores = await self._score(transcript, fields)
            await self.send_job_response(message.job_id, scores)
        except Exception as e:
            logger.warning("Scoring failed: %s", e)
            await self.send_job_response(message.job_id, {"error": str(e)}, status="FAILED")

    async def _score(self, transcript: list[dict], fields: list[str]) -> dict:
        convo = "\n".join(
            f"{t.get('speaker', '?').upper()}: {t.get('text', '')}" for t in transcript
        )
        user = (
            f"Caller persona: {self._persona}\n\n"
            f"Dimensions to score: {', '.join(fields)}\n\n"
            f"Conversation so far:\n{convo}\n\n"
            'Return JSON: {"<dimension>": {"score": 0.0, "reason": "<=10 words"}, ...}'
        )
        resp = await self._client.messages.create(
            model=LIVE_MODEL,
            max_tokens=400,
            system=SCORE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        text = resp.content[0].text if resp.content else "{}"
        return ScoringSubAgent._parse_json(text)

    @staticmethod
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


class EvalBridge(PipelineWorker):
    """Pipeline worker that joins a Daily room as "Shunya Eval".

    Audio is pushed via ``queue_frame()`` and played to the room by the
    DailyTransport output processor. No input/STT/LLM — pure audio output.
    """

    def __init__(self, name: str, room_url: str, room_token: str):
        transport = DailyTransport(
            room_url,
            room_token,
            "Shunya Eval",
            DailyParams(audio_out_enabled=True, audio_in_enabled=False),
        )
        pipeline = Pipeline([transport.output()])
        super().__init__(name=name, pipeline=pipeline, params=PipelineParams())
        self._transport = transport


class EvalAgent(BaseWorker):
    """Root Pipecat worker that orchestrates a remote ElevenLabs agent test run.

    Lifecycle:
      1. Activated by WorkerRunner → spawns ``_run()`` background task
      2. Adds EvalBridge (Daily room) and ScoringSubAgents as children
      3. Connects to ElevenLabs Conversational AI WebSocket
      4. Drives scenario steps (TTS → WS + Daily room)
      5. After each agent turn dispatches scoring jobs to sub-agents
      6. Posts aggregated scores to Django
      7. Calls ``end()`` to signal completion
    """

    def __init__(
        self,
        name: str,
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
        super().__init__(name=name)
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
        self._scorers: list[ScoringSubAgent] = []

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
        self._bridge_ready = asyncio.Event()

        self.recording_file: str | None = None
        self.closed_reason: str = ""

    # -- lifecycle -------------------------------------------------------

    async def on_activated(self, args: dict | None = None) -> None:
        asyncio.create_task(self._run())

    @worker_ready(name="bridge")
    async def on_bridge_ready(self, data) -> None:
        self._bridge_ready.set()

    async def _run(self):
        try:
            fields = [f for f in self._rubric] if self._rubric else \
                     ["instruction_following", "goal_completion", "csat_tone", "safety"]
            persona = (self.steps[0].get("persona", "") if self.steps else "")
            anthro_key = os.environ.get("ANTHROPIC_API_KEY", "")

            # Optional Daily bridge — only when room_url provided
            if self.room_url and self.room_token:
                bridge_name = f"bridge-{uuid.uuid4().hex[:6]}"
                self._bridge = EvalBridge(bridge_name, self.room_url, self.room_token)
                await self.add_workers(self._bridge)
                await asyncio.wait_for(self._bridge_ready.wait(), timeout=15)
            else:
                logger.info("No Daily room — running WS-only (no live listen-in)")

            for field in fields:
                scorer = ScoringSubAgent(f"scorer-{field}", anthro_key, persona=persona)
                self._scorers.append(scorer)
                await self.add_workers(scorer)

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

            self.recording_file = write_mixed_wav(
                self._recording_id, self._caller_frames, self._agent_frames
            )
        except Exception as e:
            logger.exception("Eval agent failed: %s", e)
        finally:
            await self.end()

    # -- ElevenLabs WebSocket -------------------------------------------

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
        """Read WS messages from the ElevenLabs agent."""
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
                        await self._bridge.queue_frame(
                            AudioRawFrame(audio=pcm, sample_rate=16000, num_channels=1)
                        )
                    continue
                if mtype == "agent_response":
                    text = msg.get("agent_response_event", {}).get("agent_response", "")
                    if text:
                        self._agent_text = (
                            (self._agent_text + " " + text).strip() if self._agent_text else text.strip()
                        )
                    continue
                if mtype == "interruption":
                    continue
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            return

    # -- scenario driving -----------------------------------------------

    async def _speak_loop(self):
        for step in self.steps:
            clean = step.get("text", step.get("raw", ""))
            quirks = [q.get("tag", "") for q in step.get("quirks", [])]

            caller_ts_ms = int((time.monotonic() - self._call_start_ts) * 1000)
            self._transcript.append({
                "speaker": "caller", "text": clean, "ts_ms": caller_ts_ms, "quirks": quirks,
            })
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

            text = await self._collect_agent_turn(start_timeout=RESPONSE_TIMEOUT)
            if text:
                self._append_agent_turn(text)
                await self._dispatch_scoring()

    async def _send_caller_audio(self, pcm: bytes):
        """Stream caller PCM to ElevenLabs WS and optionally to Daily room."""
        if not self._ws:
            return
        if self._bridge:
            await self._bridge.queue_frame(
                AudioRawFrame(audio=pcm, sample_rate=16000, num_channels=1)
            )
        for i in range(0, len(pcm), SEND_FRAME_BYTES):
            frame = pcm[i:i + SEND_FRAME_BYTES]
            await self._ws.send(json.dumps({
                "user_audio_chunk": base64.b64encode(frame).decode("ascii"),
            }))
            await asyncio.sleep(len(frame) / BYTES_PER_SEC)
        await self._ws.send(json.dumps({
            "user_audio_chunk": base64.b64encode(b"\x00" * TRAILING_SILENCE_BYTES).decode("ascii"),
        }))

    async def _collect_agent_turn(self, start_timeout: float, is_greeting: bool = False) -> str:
        deadline = time.monotonic() + start_timeout
        while time.monotonic() < deadline:
            ready = (self._agent_audio_started or self._agent_text) if is_greeting else bool(self._agent_text)
            if ready:
                break
            await asyncio.sleep(0.05)
        else:
            if not is_greeting:
                logger.warning("Timed out waiting for agent")
            return ""

        collect_deadline = time.monotonic() + COLLECT_WINDOW
        while time.monotonic() < collect_deadline:
            await asyncio.sleep(0.1)
            quiet_for = time.monotonic() - self._last_agent_audio_ts
            if self._agent_audio_started and quiet_for > SILENCE_GAP:
                break

        return self._agent_text.strip()

    # -- concurrent scoring via bus jobs ---------------------------------

    async def _dispatch_scoring(self):
        if not self._scorers:
            return
        fields = list(self._rubric.keys()) if self._rubric else \
                 ["instruction_following", "goal_completion", "csat_tone", "safety"]
        snapshot = list(self._transcript)

        async def _score_one(scorer: ScoringSubAgent, field: str):
            try:
                async with self.job(
                    scorer.name,
                    name="score",
                    payload={"fields": [field], "transcript": snapshot},
                    timeout=20,
                ) as j:
                    async for _ in j:
                        pass
                    if j.response and "error" not in j.response:
                        await self._post_scores(j.response)
            except Exception as e:
                logger.warning("Score dispatch failed for %s: %s", field, e)

        await asyncio.gather(*[_score_one(s, f) for s, f in zip(self._scorers, fields)])

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
            normalized.append({
                "field": field,
                "score": round(score, 2),
                "reasoning": str(entry.get("reason", ""))[:200],
                "passed": score >= PASS_THRESHOLD,
            })
        if not normalized:
            return
        try:
            async with httpx.AsyncClient(timeout=5) as c:
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

    # -- helpers ---------------------------------------------------------

    def _append_agent_turn(self, text: str):
        start = self._agent_speech_start_ts or time.monotonic()
        ts = int((start - self._call_start_ts) * 1000)
        self._transcript.append({
            "speaker": "agent", "text": text, "ts_ms": ts, "quirks": [],
        })

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
    """Convenience: create WorkerRunner + EvalAgent, run, return results."""
    agent = EvalAgent(
        name=f"eval-{uuid.uuid4().hex[:6]}",
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
    runner = WorkerRunner()
    await runner.add_workers(agent)
    await runner.run()
    return {
        "transcript": agent._transcript,
        "recording_file": agent.recording_file,
        "closed_reason": agent.closed_reason,
    }
