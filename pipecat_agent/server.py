"""
FastAPI server for the Pipecat voice agent.
Django calls /connect to provision a Daily room and start the pipeline.
"""
import asyncio
import os
import time
import logging

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import DEFAULT_VOICE_ID
from pipeline import run_voice_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Shunya Voice Agent")

DAILY_API_KEY = os.environ["DAILY_API_KEY"]
DAILY_API_URL = "https://api.daily.co/v1"

# Per-room readiness: set once the agent's TTS WebSocket is connected, so the
# synthetic caller only starts after the agent can actually respond.
AGENT_READY: dict[str, asyncio.Event] = {}

# Track background pipeline tasks so exceptions are not silently lost.
_PIPELINE_TASKS: dict[str, asyncio.Task] = {}


async def _create_daily_room(room_name: str) -> dict:
    headers = {"Authorization": f"Bearer {DAILY_API_KEY}"}
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{DAILY_API_URL}/rooms",
            headers=headers,
            json={
                "name": room_name,
                "properties": {
                    "exp": int(time.time()) + 3600,
                    "max_participants": 10,  # agent bot + caller bot + up to 8 observers
                },
            },
        )
        r.raise_for_status()
        return r.json()


async def _get_room_token(room_name: str, is_owner: bool = True) -> str:
    headers = {"Authorization": f"Bearer {DAILY_API_KEY}"}
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{DAILY_API_URL}/meeting-tokens",
            headers=headers,
            json={"properties": {"room_name": room_name, "is_owner": is_owner}},
        )
        r.raise_for_status()
        return r.json()["token"]


class ConnectRequest(BaseModel):
    agent_id: str
    system_prompt: str
    voice_id: str = DEFAULT_VOICE_ID
    greeting: str = ""
    schema_name: str = ""   # tenant schema — forwarded to /internal/ calls
    room_name: str | None = None


@app.post("/connect")
async def connect(req: ConnectRequest):
    """
    Called by Django to provision a room and start the voice pipeline.
    Returns the room_url for the human caller to join.
    """
    room_name = req.room_name or f"shunya-{req.agent_id[:8]}-{int(asyncio.get_event_loop().time())}"

    try:
        room = await _create_daily_room(room_name)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Daily room creation failed: {e}")

    room_url = room["url"]
    bot_token = await _get_room_token(room_name, is_owner=True)
    caller_token = await _get_room_token(room_name, is_owner=False)
    observer_token = await _get_room_token(room_name, is_owner=False)

    ready_event = asyncio.Event()
    AGENT_READY[room_url] = ready_event

    # Track the pipeline task so unhandled exceptions surface in logs rather than
    # being silently discarded.
    task = asyncio.create_task(
        run_voice_agent(
            agent_id=req.agent_id,
            room_url=room_url,
            room_token=bot_token,
            system_prompt=req.system_prompt,
            voice_id=req.voice_id,
            greeting=req.greeting,
            schema_name=req.schema_name,
            ready_event=ready_event,
        ),
        name=f"pipeline-{room_name}",
    )
    _PIPELINE_TASKS[room_url] = task
    task.add_done_callback(
        lambda t: (
            _PIPELINE_TASKS.pop(room_url, None),
            logger.error(f"Pipeline {room_name} raised: {t.exception()}") if t.exception() else None,
        )
    )

    return JSONResponse({
        "room_url": room_url,
        "room_name": room_name,
        "caller_token": caller_token,
        # Pre-auth join link for any human observer (tenant, debugger).
        # Open this URL in a browser during the test run to listen in.
        "observer_url": f"{room_url}?t={observer_token}",
    })


class CallerRunRequest(BaseModel):
    room_url: str
    room_token: str
    steps: list[dict]
    voice_id: str = DEFAULT_VOICE_ID
    recording_id: str = ""


CALLER_SERVICE_URL = os.environ.get("CALLER_SERVICE_URL", "http://caller:8002")


@app.post("/caller/run")
async def caller_run(req: CallerRunRequest):
    """
    Forward to the caller service (separate process with its own Daily SDK context).
    Waits for the agent's TTS WebSocket to be connected first so the caller only
    starts speaking once the agent can actually respond.
    """
    ready_event = AGENT_READY.get(req.room_url)
    if ready_event is not None:
        try:
            await asyncio.wait_for(ready_event.wait(), timeout=20)
            logger.info("Agent ready — dispatching caller")
        except asyncio.TimeoutError:
            logger.warning("Agent readiness timed out; dispatching caller anyway")

    try:
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(
                f"{CALLER_SERVICE_URL}/run",
                json={
                    "room_url": req.room_url,
                    "room_token": req.room_token,
                    "steps": req.steps,
                    "voice_id": req.voice_id,
                    "recording_id": req.recording_id,
                },
            )
            r.raise_for_status()
            return JSONResponse(r.json())
    except httpx.HTTPStatusError as e:
        logger.error(f"Caller service error: {e.response.text}")
        raise HTTPException(status_code=502, detail=f"Caller service: {e.response.text}")
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error(f"Caller service unreachable: {e}")
        raise HTTPException(status_code=503, detail=f"Caller service unreachable: {e}")
    finally:
        AGENT_READY.pop(req.room_url, None)


@app.get("/debug-ws")
async def debug_ws():
    """Attempt the ElevenLabs TTS WS handshake from inside the server event loop."""
    from websockets.asyncio.client import connect as websocket_connect
    key = os.environ["ELEVENLABS_API_KEY"]
    url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{DEFAULT_VOICE_ID}/"
        "multi-stream-input?model_id=eleven_turbo_v2_5&output_format=pcm_24000&auto_mode=true"
    )
    results = []
    for i in range(3):
        try:
            ws = await websocket_connect(url, max_size=16 * 1024 * 1024,
                                         additional_headers={"xi-api-key": key})
            await ws.close()
            results.append(f"{i}:OK")
        except Exception as e:
            results.append(f"{i}:{type(e).__name__}:{e}")
    return {"results": results}


@app.get("/health")
async def health():
    return {"status": "ok"}
