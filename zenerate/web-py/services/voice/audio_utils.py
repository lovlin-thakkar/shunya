"""
Pure audio helpers shared by the remote (WebSocket) caller bot.

Kept deliberately separate from caller_bot.py so the hard-won Daily/Pipecat
audio path is not destabilised. These functions have no Daily dependency.

All PCM here is 16 kHz mono 16-bit little-endian — the format ElevenLabs TTS
emits with output_format=pcm_16000 and the format we feed back to a remote
ElevenLabs agent's WebSocket.
"""
import array
import asyncio
import logging
import os
import wave

import httpx

logger = logging.getLogger(__name__)

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"
# 16 kHz mono 16-bit: 1 second = 32 000 bytes
BYTES_PER_SEC = 32_000


class ElevenLabsQuotaError(Exception):
    """Raised when ElevenLabs API credits are exhausted — fail the run immediately."""


def _raise_if_quota(resp: httpx.Response) -> None:
    if resp.status_code == 401:
        try:
            detail = resp.json().get("detail", {})
            if isinstance(detail, dict) and detail.get("code") == "quota_exceeded":
                raise ElevenLabsQuotaError(detail.get("message", "ElevenLabs quota exhausted"))
        except (ValueError, AttributeError):
            pass


async def synthesize_tts(text: str, voice_id: str, api_key: str) -> bytes | None:
    """Synthesise caller speech as raw 16 kHz PCM via ElevenLabs REST TTS.

    output_format MUST be a query parameter — in the JSON body it is ignored and
    ElevenLabs returns MP3, which fed to a remote agent as raw PCM is noise.
    """
    url = f"{ELEVENLABS_API_URL}/text-to-speech/{voice_id}/stream"
    params = {"output_format": "pcm_16000"}
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
    }
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    # ElevenLabs' edge intermittently refuses connections under concurrent load
    # (Errno 111) — a short backoff + retry clears it, instead of leaving the
    # caller mute for the whole call.
    last_err = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(url, params=params, json=payload, headers=headers)
                _raise_if_quota(r)
                r.raise_for_status()
                return r.content
        except ElevenLabsQuotaError:
            raise
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            last_err = e
            await asyncio.sleep(2 ** attempt)  # 2s, 4s, 8s — ElevenLabs needs real breathing room
        except httpx.HTTPStatusError as e:
            logger.error(f"ElevenLabs TTS failed: {e}")
            return None
    logger.error(f"ElevenLabs TTS failed after retries: {last_err}")
    return None


def write_mixed_wav(recording_id: str, caller_frames, agent_frames,
                    recordings_dir: str = "/recordings") -> str | None:
    """Mix caller + agent audio onto one timeline and write a mono 16 kHz WAV.

    caller_frames / agent_frames are lists of (offset_secs, pcm_bytes) where
    offset_secs is the wall-clock offset from call start captured at the moment
    the chunk was sent / received. Gaps stay as silence — nothing is invented.

    Returns the written filename (e.g. "<id>.wav") or None.
    """
    if not recording_id:
        return None
    all_chunks = list(caller_frames) + list(agent_frames)
    if not all_chunks:
        return None

    total_secs = max(off + len(pcm) / BYTES_PER_SEC for off, pcm in all_chunks)
    total_bytes = int(total_secs * BYTES_PER_SEC) + BYTES_PER_SEC  # +1s tail
    buf = array.array("h", [0] * (total_bytes // 2))

    for offset_secs, pcm in all_chunks:
        start_sample = int(offset_secs * 16000)
        n = len(pcm) // 2
        chunk = array.array("h", pcm[: n * 2])
        for i, s in enumerate(chunk):
            idx = start_sample + i
            if idx >= len(buf):
                break
            buf[idx] = max(-32768, min(32767, buf[idx] + s))

    try:
        os.makedirs(recordings_dir, exist_ok=True)
        path = os.path.join(recordings_dir, f"{recording_id}.wav")
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(buf.tobytes())
        logger.info(
            "Wrote recording %s (%.1fs, %d caller chunks, %d agent chunks)",
            path, total_secs, len(caller_frames), len(agent_frames),
        )
        return f"{recording_id}.wav"
    except OSError as e:
        logger.error(f"Failed to write recording: {e}")
        return None
