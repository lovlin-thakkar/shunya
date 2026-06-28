"""
Standalone FastAPI server for the scenario caller bot.
Runs in a separate process with its own Daily SDK context,
isolated from the agent pipeline process.
"""
import asyncio
import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daily import Daily

from config import DEFAULT_VOICE_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Daily.init()

app = FastAPI(title="Shunya Caller Bot")


class CallerRunRequest(BaseModel):
    room_url: str
    room_token: str
    steps: list[dict]
    voice_id: str = DEFAULT_VOICE_ID
    recording_id: str = ""


@app.post("/run")
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


@app.get("/health")
async def health():
    return {"status": "ok"}
