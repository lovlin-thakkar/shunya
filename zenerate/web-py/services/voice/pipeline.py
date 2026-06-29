"""
Pipecat voice agent pipeline.
Wires: Daily WebRTC → ElevenLabs Scribe STT → Claude Haiku → ElevenLabs TTS → Daily output
"""
import asyncio
import os
import logging
import httpx
import aiohttp

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMUserAggregator,
    LLMUserAggregatorParams,
    LLMAssistantAggregator,
)
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.elevenlabs.stt import ElevenLabsSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.processors.audio.vad_processor import VADProcessor

from config import DEFAULT_VOICE_ID

logger = logging.getLogger(__name__)

DJANGO_API_URL = os.environ.get("DJANGO_API_URL", "http://localhost:8000")
DJANGO_SERVICE_TOKEN = os.environ.get("DJANGO_SERVICE_TOKEN", "")


def _service_headers(tenant_id: str) -> dict:
    return {
        "X-Service-Token": DJANGO_SERVICE_TOKEN,
        "X-Tenant-Id": str(tenant_id),
    }


class RetryingElevenLabsTTSService(ElevenLabsTTSService):
    """ElevenLabs TTS with connection retry.

    ElevenLabs' GCP edge intermittently returns an empty-body HTTP 403 to the
    TTS WebSocket handshake when the host IP bursts requests (the synthetic
    caller bot hammers the same key with REST TTS/STT during a test run). The
    base service treats this as a non-fatal error and never retries, leaving the
    agent mute for the whole call. A short backoff + retry clears it reliably.
    """

    _CONNECT_RETRIES = 5
    _CONNECT_BACKOFF = 0.75  # seconds, grows linearly

    async def _connect_websocket(self):
        last_state = None
        logger.info(
            f"TTS connect params: voice={self._settings.voice} model={self._settings.model} "
            f"output_format={self._output_format!r} sample_rate={self.sample_rate} "
            f"auto_mode={self._auto_mode} url={self._url}"
        )
        for attempt in range(1, self._CONNECT_RETRIES + 1):
            await super()._connect_websocket()
            if self._websocket is not None:
                if attempt > 1:
                    logger.info(f"ElevenLabs TTS connected on attempt {attempt}")
                return
            last_state = "no websocket"
            delay = self._CONNECT_BACKOFF * attempt
            logger.warning(
                f"ElevenLabs TTS connect failed (attempt {attempt}/{self._CONNECT_RETRIES}); "
                f"retrying in {delay:.2f}s"
            )
            await asyncio.sleep(delay)
        logger.error(f"ElevenLabs TTS connect exhausted retries ({last_state})")


async def _notify_django(path: str, payload: dict, tenant_id: str = ""):
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(
                f"{DJANGO_API_URL}/internal/{path}",
                json=payload,
                headers=_service_headers(tenant_id),
            )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as e:
        logger.error(f"Django notify failed ({path}): {e}")


async def run_voice_agent(
    agent_id: str,
    room_url: str,
    room_token: str,
    system_prompt: str,
    voice_id: str = DEFAULT_VOICE_ID,
    greeting: str = "",
    tenant_id: str = "",
    ready_event: "asyncio.Event | None" = None,
):
    async with aiohttp.ClientSession() as aiohttp_session:
        await _run_voice_agent_inner(
            agent_id, room_url, room_token, system_prompt, voice_id,
            greeting, tenant_id, aiohttp_session, ready_event,
        )


async def _run_voice_agent_inner(
    agent_id: str,
    room_url: str,
    room_token: str,
    system_prompt: str,
    voice_id: str,
    greeting: str,
    tenant_id: str,
    aiohttp_session: aiohttp.ClientSession,
    ready_event: "asyncio.Event | None" = None,
):
    transport = DailyTransport(
        room_url,
        room_token,
        "Shunya Agent",
        DailyParams(
            audio_out_enabled=True,
            audio_in_enabled=True,
            audio_in_sample_rate=16000,
            transcription_enabled=False,
        ),
    )

    stt = ElevenLabsSTTService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        aiohttp_session=aiohttp_session,
    )
    voice_id = voice_id or DEFAULT_VOICE_ID
    tts = RetryingElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsTTSService.Settings(voice=voice_id),
    )

    # Signal readiness once the TTS WebSocket is actually connected, so the
    # synthetic caller only starts speaking after the agent can respond.
    @tts.event_handler("on_connected")
    async def _on_tts_connected(service):
        if ready_event is not None and not ready_event.is_set():
            logger.info("Agent TTS connected — signaling ready")
            ready_event.set()
    # If the agent has a hardcoded greeting, prepend it to the system instruction
    # so the LLM knows exactly what to say when "[call started]" arrives.
    effective_system = system_prompt
    if greeting:
        effective_system = (
            f"OPENING GREETING INSTRUCTION (highest priority): When you receive the "
            f"message [call started], respond with ONLY this exact text — no additions, "
            f"no emoji, no variations:\n"
            f'"{greeting}"\n\n'
            + system_prompt
        )
    llm = AnthropicLLMService(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        settings=AnthropicLLMService.Settings(
            model="claude-haiku-4-5-20251001",
            system_instruction=effective_system,
        ),
    )

    context = LLMContext()
    # Pipecat 1.4.0 DailyParams has no vad_analyzer, so VAD is a standalone
    # processor (below) placed before the STT rather than configured on the transport.
    vad = SileroVADAnalyzer(params=VADParams(
        confidence=0.5, start_secs=0.2, stop_secs=0.3, min_volume=0.05,
    ))
    # Standalone VAD processor placed before the STT so the segmented Scribe
    # STT receives VADUserStartedSpeaking/StoppedSpeaking boundaries.
    vad_processor = VADProcessor(vad_analyzer=vad)
    user_agg = LLMUserAggregator(context=context)
    asst_agg = LLMAssistantAggregator(context=context)

    pipeline = Pipeline([
        transport.input(),
        vad_processor,
        stt,
        user_agg,
        llm,
        tts,
        transport.output(),
        asst_agg,
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(allow_interruptions=True),
    )

    call_resp = {"call_id": None, "caller_participant_id": None}

    @transport.event_handler("on_first_participant_joined")
    async def on_participant_joined(transport, participant):
        # Record the caller's participant ID so we only end the call when THEY leave.
        # Observers or transient ghost participants leaving must not cancel the pipeline.
        call_resp["caller_participant_id"] = participant.get("id")

        data = {
            "agent_id": agent_id,
            "source": "human",
            "daily_room_url": room_url,
            "daily_room_name": room_url.split("/")[-1],
        }
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(
                f"{DJANGO_API_URL}/internal/calls/start/",
                json=data,
                headers=_service_headers(tenant_id),
            )
            if r.status_code == 201:
                call_resp["call_id"] = r.json()["call_id"]

        if greeting:
            from pipecat.frames.frames import LLMMessagesAppendFrame
            await task.queue_frames([
                LLMMessagesAppendFrame(
                    messages=[{"role": "user", "content": "[call started]"}],
                    run_llm=True,
                )
            ])

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        pid = participant.get("id")
        caller_pid = call_resp.get("caller_participant_id")
        if caller_pid and pid != caller_pid:
            # An observer or unrelated participant left — keep the pipeline alive.
            logger.info(f"Non-caller participant {pid} left ({reason}); pipeline continues")
            return
        if call_resp["call_id"]:
            await _notify_django(
                f"calls/{call_resp['call_id']}/end/",
                {"reason": reason},
                tenant_id=tenant_id,
            )
        await task.cancel()

    runner = PipelineRunner()
    await runner.run(task)
