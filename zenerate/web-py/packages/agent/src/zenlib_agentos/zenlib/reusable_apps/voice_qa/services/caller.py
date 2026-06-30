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

    Unlike AudioCaller there is no Daily room and no Pipecat agent pipeline — the
    agent under test is hosted by ElevenLabs and reached by ``agent.el_agent_id``.
    We therefore POST straight to the caller service ``/remote/run`` endpoint
    (which mounts ``/recordings`` and owns the ElevenLabs API key) rather than
    going through Pipecat's ``/connect``.
    """

    def __init__(self, agent):
        self.agent = agent
        # No live listen-in: there is no Daily room to observe for a remote agent.
        self.observer_url: str | None = None
        # Set if ElevenLabs closed the WS mid-call (e.g. agent technical issues).
        self.disconnect_reason: str = ""
        # Rubric for the during-call judge sub-agent; the runner sets this.
        self.rubric: dict = {}

    def _connect(self):
        # Nothing to provision — ElevenLabs already hosts the agent. Kept so the
        # runner's audio branch can call it uniformly with AudioCaller.
        return

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
        return


def get_caller(mode: str, agent) -> CallerInterface:
    if getattr(agent, "target_type", "builtin") == "elevenlabs":
        # Remote ElevenLabs agents are always exercised over the WS audio path,
        # regardless of the run's mode.
        return RemoteAudioCaller(agent)
    return AudioCaller(agent) if mode == "audio" else TextCaller(agent)
