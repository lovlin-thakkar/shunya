"""
Standalone FastAPI server for the scenario caller bot.
Runs in a separate process with its own Daily SDK context,
isolated from the agent pipeline process.
"""
import asyncio
import logging
import os

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daily import Daily

from config import DEFAULT_VOICE_ID, CALLER_DEFAULT_VOICE_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Daily.init()

app = FastAPI(title="Shunya Caller Bot")

_SERVICE_TOKEN = os.environ.get("DJANGO_SERVICE_TOKEN", "")

# Cap concurrent remote runs so parallel "Run All" dispatches don't overwhelm
# ElevenLabs (its edge refuses connections under burst load → mute caller / 500s).
# Excess requests get 429; the Celery task retries them with backoff.
MAX_CONCURRENT_REMOTE = int(os.environ.get("MAX_CONCURRENT_REMOTE", "4"))
_active_remote = 0


def _require_service_token(x_service_token: str = Header(default="")) -> None:
    if not _SERVICE_TOKEN:
        raise HTTPException(status_code=500, detail="Service token not configured")
    if x_service_token != _SERVICE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid service token")


class CallerRunRequest(BaseModel):
    room_url: str
    room_token: str
    steps: list[dict]
    voice_id: str = DEFAULT_VOICE_ID
    recording_id: str = ""


@app.post("/run", dependencies=[Depends(_require_service_token)])
async def run(req: CallerRunRequest):
    from caller_bot import ScenarioCallerBot
    bot = ScenarioCallerBot(
        room_url=req.room_url,
        room_token=req.room_token,
        steps=req.steps,
        voice_id=req.voice_id,
        recording_id=req.recording_id,
    )
    try:
        transcript = await bot.run()
    except Exception as e:
        logger.error(f"Caller bot failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse({"transcript": transcript, "recording_file": bot.recording_file})


class RemoteRunRequest(BaseModel):
    el_agent_id: str
    steps: list[dict]
    agent_api_key: str = ""   # tenant's ElevenLabs key — reaches/signs their agent
    dynamic_variables: dict = {}  # injected into conversation_initiation_client_data
    voice_id: str = CALLER_DEFAULT_VOICE_ID
    recording_id: str = ""
    run_id: str = ""          # TestRun id — target for live judge scores
    tenant_id: str = ""
    rubric: dict = {}


@app.post("/remote/run", dependencies=[Depends(_require_service_token)])
async def remote_run(req: RemoteRunRequest):
    """Drive a scenario against a customer's deployed ElevenLabs agent over the
    Conversational AI WebSocket. No Daily room / Pipecat pipeline involved.

    Runs a concurrent judge sub-agent that scores the conversation live when a
    run_id is supplied (the "eval agent with sub-agents" pattern)."""
    global _active_remote
    if _active_remote >= MAX_CONCURRENT_REMOTE:
        logger.warning("Remote caller at capacity (%d/%d), rejecting", _active_remote, MAX_CONCURRENT_REMOTE)
        # 429 → the Celery task retries with backoff instead of failing the run.
        raise HTTPException(status_code=429, detail="Caller at capacity. Retry shortly.")
    _active_remote += 1

    from remote_caller_bot import ScenarioRemoteCallerBot

    judge = None
    if req.run_id:
        from judge_subagent import LiveJudgeSubAgent
        persona = (req.steps[0].get("persona", "") if req.steps else "")
        judge = LiveJudgeSubAgent(
            run_id=req.run_id,
            tenant_id=req.tenant_id,
            rubric=req.rubric,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            django_url=os.environ.get("DJANGO_API_URL", "http://django:8000"),
            service_token=_SERVICE_TOKEN,
            persona=persona,
        )

    bot = ScenarioRemoteCallerBot(
        el_agent_id=req.el_agent_id,
        steps=req.steps,
        agent_api_key=req.agent_api_key,
        dynamic_variables=req.dynamic_variables,
        # Platform key drives the synthetic caller's own TTS voice.
        tts_api_key=os.environ.get("ELEVENLABS_API_KEY", ""),
        caller_voice_id=req.voice_id,
        recording_id=req.recording_id,
        judge=judge,
    )
    try:
        transcript = await bot.run()
    except (ConnectionRefusedError, httpx.ConnectError, OSError) as e:
        # Transient egress/ElevenLabs failure — tell Celery to retry (503), not 500.
        logger.warning(f"Remote caller transient failure: {e}")
        raise HTTPException(status_code=503, detail=f"Transient connection failure: {e}")
    except Exception as e:
        logger.error(f"Remote caller bot failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _active_remote -= 1
    return JSONResponse({
        "transcript": transcript,
        "recording_file": bot.recording_file,
        "closed_reason": bot.closed_reason,
    })


@app.get("/health")
async def health():
    return {"status": "ok"}
