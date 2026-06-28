import time
import uuid

import anthropic
from django.conf import settings


class AgentChat:
    """Stateful Claude chat handler for an Agent. Used by TextCaller and the /chat/ endpoint."""

    MODEL = "claude-haiku-4-5-20251001"  # fast + cheap for the agent under test

    def __init__(self, agent):
        self.agent = agent
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._histories: dict[str, list] = {}

    def send(self, message: str, conversation_id: str | None = None) -> dict:
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())

        history = self._histories.setdefault(conversation_id, [])

        # Pre-seed greeting: inject it as the first assistant turn so the LLM
        # "remembers" it already said this and continues naturally from there.
        # The greeting is not sent to the API here — it's added to history so
        # the next real user message sees it as prior context.
        if not history and getattr(self.agent, "greeting", ""):
            history.extend([
                {"role": "user", "content": "[call started]"},
                {"role": "assistant", "content": self.agent.greeting},
            ])

        history.append({"role": "user", "content": message})

        system = (
            "VOICE CALL RULES (override everything): Reply in 1-2 short sentences only. "
            "Never use bullet points, numbered lists, bold text, or markdown. "
            "Never ask more than one question at a time. Speak like a human on a phone call.\n\n"
            + self.agent.system_prompt.rstrip()
        )

        t0 = time.monotonic()
        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=200,
            system=system,
            messages=history,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        reply = response.content[0].text
        history.append({"role": "assistant", "content": reply})

        return {
            "response": reply,
            "conversation_id": conversation_id,
            "ts_ms": latency_ms,
        }

    def get_history(self, conversation_id: str) -> list:
        return self._histories.get(conversation_id, [])
