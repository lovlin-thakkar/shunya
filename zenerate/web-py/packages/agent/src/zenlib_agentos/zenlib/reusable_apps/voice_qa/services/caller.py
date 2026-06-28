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


def get_caller(mode: str, agent) -> CallerInterface:
    return AudioCaller(agent) if mode == "audio" else TextCaller(agent)
