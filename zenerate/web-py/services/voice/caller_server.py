"""
Caller service: drives remote ElevenLabs Conversational AI agents.
Runs in a separate process with its own Daily SDK context.
"""
import hmac
import logging
import os
import uuid

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daily import Daily

from config import CALLER_DEFAULT_VOICE_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Daily.init()

app = FastAPI(title="Shunya Caller Bot")

_SERVICE_TOKEN = os.environ.get("DJANGO_SERVICE_TOKEN", "")
DAILY_API_URL = "https://api.daily.co/v1"
DAILY_API_KEY = os.environ.get("DAILY_API_KEY", "")

# Cap concurrent remote runs so parallel "Run All" dispatches don't overwhelm
# ElevenLabs (its edge refuses connections under burst load → mute caller / 500s).
# Excess requests get 429; the Celery task retries them with backoff.
# WARNING: _active_remote is a per-process integer. asyncio is single-threaded so
# no lock is needed, but if uvicorn is run with --workers > 1, each worker process
# has its own counter and the cap silently multiplies. Always run with one worker.
MAX_CONCURRENT_REMOTE = int(os.environ.get("MAX_CONCURRENT_REMOTE", "4"))
_active_remote = 0


def _require_service_token(x_service_token: str = Header(default="")) -> None:
    if not _SERVICE_TOKEN:
        raise HTTPException(status_code=500, detail="Service token not configured")
    if not hmac.compare_digest(x_service_token, _SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid service token")


async def _create_daily_room(room_name: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            f"{DAILY_API_URL}/rooms",
            headers={"Authorization": f"Bearer {DAILY_API_KEY}"},
            json={"name": room_name, "properties": {"max_participants": 10}},
        )
        r.raise_for_status()
        return r.json()


async def _get_room_token(room_name: str, is_owner: bool = True) -> str:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            f"{DAILY_API_URL}/meeting-tokens",
            headers={"Authorization": f"Bearer {DAILY_API_KEY}"},
            json={"properties": {"room_name": room_name, "is_owner": is_owner}},
        )
        r.raise_for_status()
        return r.json()["token"]



@app.post("/remote/connect", dependencies=[Depends(_require_service_token)])
async def remote_connect():
    """Provision a Daily room for a remote ElevenLabs agent call.

    Creates the room before the call starts so Django can persist observer_url
    to the TestRun immediately (enabling the "Listen Live" button while the
    call is in progress). The caller bot joins the room when /remote/run fires.
    """
    if not DAILY_API_KEY:
        raise HTTPException(status_code=500, detail="DAILY_API_KEY not configured on caller service")
    room_name = f"shunya-remote-{uuid.uuid4().hex[:10]}"
    try:
        room = await _create_daily_room(room_name)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Daily room creation failed: {e}")
    room_url = room["url"]
    caller_token = await _get_room_token(room_name, is_owner=True)
    observer_token = await _get_room_token(room_name, is_owner=False)
    return JSONResponse({
        "room_url": room_url,
        "room_name": room_name,
        "caller_token": caller_token,
        "observer_url": f"{room_url}?t={observer_token}",
    })


class RemoteRunRequest(BaseModel):
    el_agent_id: str
    steps: list[dict]
    persona: str = ""         # caller persona — passed to the live Scorer for context
    agent_api_key: str = ""   # tenant's ElevenLabs key — reaches/signs their agent
    dynamic_variables: dict = {}  # injected into conversation_initiation_client_data
    voice_id: str = CALLER_DEFAULT_VOICE_ID
    recording_id: str = ""
    run_id: str = ""          # TestRun id — target for live judge scores
    tenant_id: str = ""
    rubric: dict = {}
    # Optional Daily room provisioned by /remote/connect — enables live observer access.
    room_url: str = ""
    room_token: str = ""


@app.post("/remote/run", dependencies=[Depends(_require_service_token)])
async def remote_run(req: RemoteRunRequest):
    """Drive a scenario against a customer's deployed ElevenLabs agent.

    EvalAgent connects to the ElevenLabs ConvAI WebSocket, speaks each scenario
    step via EL TTS, and scores each agent turn concurrently via Scorer."""
    global _active_remote
    if _active_remote >= MAX_CONCURRENT_REMOTE:
        logger.warning("Remote caller at capacity (%d/%d), rejecting", _active_remote, MAX_CONCURRENT_REMOTE)
        raise HTTPException(status_code=429, detail="Caller at capacity. Retry shortly.")
    _active_remote += 1

    try:
        from eval_agent import run_eval_agent
        result = await run_eval_agent(
            el_agent_id=req.el_agent_id,
            steps=req.steps,
            persona=req.persona,
            room_url=req.room_url or "",
            room_token=req.room_token or "",
            agent_api_key=req.agent_api_key,
            tts_api_key=os.environ.get("ELEVENLABS_API_KEY", ""),
            dynamic_variables=req.dynamic_variables,
            caller_voice_id=req.voice_id,
            recording_id=req.recording_id,
            run_id=req.run_id,
            tenant_id=req.tenant_id,
            rubric=req.rubric,
            django_url=os.environ.get("DJANGO_API_URL", "http://django:8000"),
            service_token=_SERVICE_TOKEN,
        )
    except (ConnectionRefusedError, httpx.ConnectError, OSError) as e:
        logger.warning(f"Remote caller transient failure: {e}")
        raise HTTPException(status_code=503, detail=f"Transient connection failure: {e}")
    except Exception as e:
        logger.error(f"Remote caller bot failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _active_remote -= 1
    return JSONResponse(result)


@app.get("/health")
async def health():
    return {"status": "ok"}
