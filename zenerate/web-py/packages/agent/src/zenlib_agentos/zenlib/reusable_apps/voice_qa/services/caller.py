import logging
from abc import ABC, abstractmethod

import httpx

from .chat import AgentChat
from .quirks import strip_quirks, extract_quirk_tags

logger = logging.getLogger(__name__)


class CallerInterface(ABC):
    @abstractmethod
    def send(self, turn_text: str, conversation_id: str) -> dict: ...
    @abstractmethod
    def reset(self): ...


class TextCaller(CallerInterface):
    def __init__(self, agent):
        self.agent = agent
        self._chat = AgentChat(agent)

    def send(self, turn_text: str, conversation_id: str) -> dict:
        quirks = extract_quirk_tags(turn_text)
        result = self._chat.send(strip_quirks(turn_text), conversation_id)
        result["quirks"] = quirks
        return result

    def reset(self):
        self._chat = AgentChat(self.agent)



class RemoteAudioCaller(CallerInterface):
    """Drives a scenario against a customer's deployed ElevenLabs Conversational
    AI agent. EvalAgent (caller service) connects over WebSocket; EvalBridge
    optionally mirrors audio into a Daily.co room for live listen-in.
    """

    def __init__(self, agent):
        self.agent = agent
        self.observer_url: str | None = None
        # Set if ElevenLabs closed the WS mid-call (e.g. agent technical issues).
        self.disconnect_reason: str = ""
        # Rubric + persona for the during-call judge sub-agent; the runner sets these.
        self.rubric: dict = {}
        self.persona: str = ""
        self._room_url: str = ""
        self._caller_token: str = ""

    def _connect(self):
        """Provision a Daily room for live observation.

        Falls back gracefully when DAILY_API_KEY is not set on the caller service
        — the test still runs, just without a live listen-in link.
        """
        from django.conf import settings
        try:
            r = httpx.post(
                f"{settings.CALLER_SERVER_URL}/remote/connect",
                headers={"X-Service-Token": settings.SERVICE_TOKEN},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            self._room_url = data.get("room_url", "")
            self._caller_token = data.get("caller_token", "")
            self.observer_url = data.get("observer_url")
        except Exception as e:
            logger.warning("Remote room provisioning failed (%s) — running without live listen-in", e)

    def run_scenario(self, steps: list[dict], conversation_id: str, recording_id: str = "") -> list[dict]:
        from django.conf import settings
        from ..models import ElevenLabsCredential
        # The tenant's own ElevenLabs key reaches their agent (and signs private
        # ones). The caller service uses the platform key for the synthetic
        # caller's TTS voice.
        cred = ElevenLabsCredential.objects.filter(tenant=self.agent.tenant).first()
        r = httpx.post(
            f"{settings.CALLER_SERVER_URL}/remote/run",
            headers={"X-Service-Token": settings.SERVICE_TOKEN},
            json={
                "el_agent_id": self.agent.el_agent_id,
                "agent_api_key": cred.api_key if cred else "",
                "dynamic_variables": self.agent.dynamic_variables or {},
                "steps": steps,
                "persona": self.persona or "",
                "recording_id": recording_id,
                # Daily room for live observer access (empty → falls back to WS-only bot)
                "room_url": self._room_url,
                "room_token": self._caller_token,
                # During-call judge sub-agent inputs:
                "run_id": recording_id,
                "tenant_id": str(self.agent.tenant_id),
                "rubric": self.rubric or {},
            },
            timeout=300,
        )
        r.raise_for_status()
        data = r.json()
        self.disconnect_reason = (data.get("closed_reason") or "")[:255]
        transcript = data.get("transcript", [])
        for turn in transcript:
            turn.setdefault("quirks", [])
            turn.setdefault("ts_ms", 0)
        return transcript

    def send(self, turn_text: str, conversation_id: str) -> dict:
        raise NotImplementedError("RemoteAudioCaller does not support turn-by-turn send().")

    def reset(self):
        self._room_url = ""
        self._caller_token = ""


def get_caller(mode: str, agent) -> CallerInterface:
    if getattr(agent, "target_type", "builtin") == "elevenlabs":
        return RemoteAudioCaller(agent)
    return TextCaller(agent)
