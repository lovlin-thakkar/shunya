from abc import ABC, abstractmethod
from .chat import AgentChat
from .quirks import strip_quirks, extract_quirk_tags


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


class AudioCaller(CallerInterface):
    """
    Pipecat bot-to-bot audio testing via Daily.co WebRTC.
    ElevenLabs Scribe v2 STT + Claude Haiku + ElevenLabs TTS end-to-end.
    """

    def __init__(self, agent):
        self.agent = agent
        self._room_url: str | None = None
        self._caller_token: str | None = None
        self.observer_url: str | None = None

    def _connect(self):
        import httpx
        from django.conf import settings
        r = httpx.post(
            f"{settings.PIPECAT_SERVER_URL}/connect",
            headers={"X-Service-Token": settings.SERVICE_TOKEN},
            json={
                "agent_id": str(self.agent.id),
                "system_prompt": self.agent.system_prompt,
                "voice_id": getattr(self.agent, "voice_id", "") or "Xb7hH8MSUJpSbSDYk0k2",
                "greeting": getattr(self.agent, "greeting", ""),
                "tenant_id": str(self.agent.tenant_id),
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        self._room_url = data["room_url"]
        self._caller_token = data["caller_token"]
        self.observer_url = data.get("observer_url")

    def run_scenario(self, steps: list[dict], conversation_id: str, recording_id: str = "") -> list[dict]:
        import httpx
        from django.conf import settings
        if not self._room_url:
            self._connect()
        r = httpx.post(
            f"{settings.PIPECAT_SERVER_URL}/caller/run",
            headers={"X-Service-Token": settings.SERVICE_TOKEN},
            json={"room_url": self._room_url, "room_token": self._caller_token,
                  "steps": steps, "recording_id": recording_id},
            timeout=300,
        )
        r.raise_for_status()
        transcript = r.json().get("transcript", [])
        for turn in transcript:
            turn.setdefault("quirks", [])
            turn.setdefault("ts_ms", 0)
        return transcript

    def send(self, turn_text: str, conversation_id: str) -> dict:
        raise NotImplementedError("AudioCaller does not support turn-by-turn send().")

    def reset(self):
        self._room_url = None
        self._caller_token = None


class RemoteAudioCaller(CallerInterface):
    """
    Drives a scenario against a customer's *deployed* ElevenLabs Conversational
    AI agent over the caller service's WebSocket bridge.

    The caller service provisions a Daily.co room via /remote/connect so a human
    observer can join the room URL and listen live during the call. Both caller TTS
    audio and ElevenLabs agent audio are mirrored into the Daily room by the
    ScenarioRemoteCallerDailyBot running inside the caller service.
    """

    def __init__(self, agent):
        self.agent = agent
        self.observer_url: str | None = None
        # Set if ElevenLabs closed the WS mid-call (e.g. agent technical issues).
        self.disconnect_reason: str = ""
        # Rubric for the during-call judge sub-agent; the runner sets this.
        self.rubric: dict = {}
        self._room_url: str = ""
        self._caller_token: str = ""

    def _connect(self):
        """Provision a Daily room for live observation.

        POST /remote/connect returns immediately with a room URL and an observer
        join link. The runner persists observer_url to the TestRun so the "Listen
        Live" button appears while the call is still in progress.

        Falls back gracefully when the caller service has no DAILY_API_KEY — the
        test still runs, just without live listen-in.
        """
        import httpx
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
            import logging
            logging.getLogger(__name__).warning(
                "Remote room provisioning failed (%s) — running without live listen-in", e
            )

    def run_scenario(self, steps: list[dict], conversation_id: str, recording_id: str = "") -> list[dict]:
        import httpx
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
        # Remote ElevenLabs agents are always exercised over the WS audio path,
        # regardless of the run's mode.
        return RemoteAudioCaller(agent)
    return AudioCaller(agent) if mode == "audio" else TextCaller(agent)
