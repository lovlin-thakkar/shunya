import time
import uuid
from abc import ABC, abstractmethod

from apps.agents.chat import AgentChat
from apps.testing.quirks import strip_quirks, extract_quirk_tags


class CallerInterface(ABC):
    @abstractmethod
    def send(self, turn_text: str, conversation_id: str) -> dict:
        """Send a caller turn, return {response, ts_ms, quirks}."""

    @abstractmethod
    def reset(self):
        """Reset conversation state between test runs."""


class TextCaller(CallerInterface):
    """
    Injects text directly into the agent's Claude Haiku chat endpoint.
    Strips Voice Quirks DSL before sending; logs quirks alongside the turn.
    Bypasses STT/TTS entirely — fast and parallelisable.
    """

    def __init__(self, agent):
        self.agent = agent
        self._chat = AgentChat(agent)

    def send(self, turn_text: str, conversation_id: str) -> dict:
        quirks = extract_quirk_tags(turn_text)
        clean_text = strip_quirks(turn_text)

        t0 = time.monotonic()
        result = self._chat.send(clean_text, conversation_id)
        result["quirks"] = quirks
        return result

    def reset(self):
        self._chat = AgentChat(self.agent)


class AudioCaller(CallerInterface):
    """
    Pipecat bot-to-bot audio testing.

    Provisions a Daily room via the pipecat /connect endpoint, then calls
    the Pipecat server's /caller/run to dispatch a synthetic caller bot that
    speaks scenario steps via ElevenLabs TTS and transcribes the agent's
    responses via ElevenLabs Scribe v2 STT through the full Daily WebRTC stack.

    Because audio testing is inherently full-scenario (not turn-by-turn),
    the runner calls run_scenario() rather than send() for audio mode.
    """

    def __init__(self, agent):
        self.agent = agent
        self._room_url: str | None = None
        self._caller_token: str | None = None
        self.observer_url: str | None = None  # set by _connect(), persisted to TestRun

    def _connect(self):
        """Provision a Daily room with the agent bot already joined."""
        from django.conf import settings
        from django.db import connection as _conn
        import httpx as _httpx

        r = _httpx.post(
            f"{settings.PIPECAT_SERVER_URL}/connect",
            json={
                "agent_id": str(self.agent.id),
                "system_prompt": self.agent.system_prompt,
                # `or` so an empty/None voice_id falls back — an empty voice
                # produces a malformed ElevenLabs URL that the edge rejects with 403.
                "voice_id": getattr(self.agent, "voice_id", "") or "Xb7hH8MSUJpSbSDYk0k2",
                "greeting": getattr(self.agent, "greeting", ""),
                "schema_name": _conn.schema_name,
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        self._room_url = data["room_url"]
        self._caller_token = data["caller_token"]
        self.observer_url = data.get("observer_url")

    def run_scenario(self, steps: list[dict], conversation_id: str, recording_id: str = "") -> list[dict]:
        """
        Run the full scenario through the real audio pipeline.
        Returns transcript turns in the same format as TextCaller produces.
        """
        from django.conf import settings
        import httpx as _httpx
        import time as _time

        if not self._room_url:
            self._connect()

        r = _httpx.post(
            f"{settings.PIPECAT_SERVER_URL}/caller/run",
            json={
                "room_url": self._room_url,
                "room_token": self._caller_token,
                "steps": steps,
                "recording_id": recording_id,
            },
            timeout=300,
        )
        r.raise_for_status()

        transcript = r.json().get("transcript", [])
        for turn in transcript:
            turn.setdefault("quirks", [])
            turn.setdefault("ts_ms", 0)
        return transcript

    def send(self, turn_text: str, conversation_id: str) -> dict:
        raise NotImplementedError(
            "AudioCaller does not support turn-by-turn send(). "
            "The runner calls run_scenario() for audio mode."
        )

    def reset(self):
        self._room_url = None
        self._caller_token = None


def get_caller(mode: str, agent) -> CallerInterface:
    if mode == "audio":
        return AudioCaller(agent)
    return TextCaller(agent)
