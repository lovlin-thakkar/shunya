"""
Live judge sub-agent for during-call scoring.

This realises the "eval agent with sub-agents" pattern: while the caller bot
drives the conversation with the remote ElevenLabs agent, this sub-agent runs
*concurrently* and scores the conversation turn-by-turn with Claude Haiku
(fast/cheap), pushing a running snapshot to Django after every agent turn so the
run page can show scores accumulating live.

It is intentionally independent of the caller's turn-taking loop: the caller
just calls submit() after each agent turn; scoring happens on its own asyncio
task and never blocks the call. The post-call Sonnet judge still produces the
authoritative JudgeScore rows — these are the live, indicative ones.
"""
import asyncio
import json
import logging
import re

import httpx
from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

# Mirrors JudgeScore.RUBRIC_FIELDS on the Django side.
RUBRIC_FIELDS = [
    "instruction_following", "goal_completion", "interruption_handling",
    "tool_call_accuracy", "csat_tone", "safety",
]
# Dimensions that are meaningful to score live (others need the full call).
DEFAULT_LIVE_FIELDS = ["instruction_following", "goal_completion", "csat_tone", "safety"]

LIVE_MODEL = "claude-haiku-4-5-20251001"
PASS_THRESHOLD = 0.7

SYSTEM_PROMPT = (
    "You are a live QA scorer for a voice AI agent under test. Given the "
    "conversation so far, score the AGENT (not the caller) on each rubric "
    "dimension from 0.0 (fail) to 1.0 (pass). Judge only what is observable so "
    "far. Return ONLY a JSON object, no prose, no markdown fences."
)


class LiveJudgeSubAgent:
    def __init__(self, run_id, tenant_id, rubric, anthropic_api_key,
                 django_url, service_token, persona=""):
        self.run_id = run_id
        self.tenant_id = str(tenant_id)
        self.persona = persona or ""
        self._fields = [f for f in (rubric or {}) if f in RUBRIC_FIELDS] or list(DEFAULT_LIVE_FIELDS)
        self._django_url = (django_url or "").rstrip("/")
        self._service_token = service_token or ""
        self._client = AsyncAnthropic(api_key=anthropic_api_key) if anthropic_api_key else None

        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._turn = 0
        # field -> {"score", "reasoning", "passed"}
        self._scores: dict[str, dict] = {}

    def start(self):
        if self._client is None:
            logger.warning("Live judge disabled: no Anthropic key")
            return
        self._task = asyncio.create_task(self._loop(), name=f"live-judge-{self.run_id}")

    def submit(self, transcript_snapshot: list[dict]):
        """Non-blocking: hand the current cumulative transcript to the scorer."""
        if self._task is not None:
            self._queue.put_nowait(list(transcript_snapshot))

    async def stop(self):
        if self._task is None:
            return
        self._queue.put_nowait(None)
        try:
            await asyncio.wait_for(self._task, timeout=20)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception) as e:
            logger.warning("Live judge stop: %s", e)

    # ------------------------------------------------------------------ internals

    async def _loop(self):
        while True:
            snapshot = await self._queue.get()
            if snapshot is None:
                return
            # Coalesce: if newer snapshots are already queued, score only the latest.
            while not self._queue.empty():
                nxt = self._queue.get_nowait()
                if nxt is None:
                    snapshot = None
                    break
                snapshot = nxt
            if snapshot is None:
                return
            self._turn += 1
            try:
                await self._score(snapshot)
                await self._post()
            except Exception as e:
                logger.warning("Live judge scoring failed (turn %d): %s", self._turn, e)

    async def _score(self, transcript: list[dict]):
        convo = "\n".join(f"{t['speaker'].upper()}: {t.get('text', '')}" for t in transcript)
        user = (
            f"Caller persona: {self.persona}\n\n"
            f"Dimensions to score: {', '.join(self._fields)}\n\n"
            f"Conversation so far:\n{convo}\n\n"
            'Return JSON: {"<dimension>": {"score": 0.0, "reason": "<=10 words"}, ...}'
        )
        resp = await self._client.messages.create(
            model=LIVE_MODEL,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        text = resp.content[0].text if resp.content else "{}"
        data = self._parse_json(text)
        for field in self._fields:
            entry = data.get(field)
            if not isinstance(entry, dict):
                continue
            try:
                score = max(0.0, min(1.0, float(entry.get("score", 0.0))))
            except (TypeError, ValueError):
                continue
            self._scores[field] = {
                "field": field,
                "score": round(score, 2),
                "reasoning": str(entry.get("reason", ""))[:200],
                "passed": score >= PASS_THRESHOLD,
            }

    async def _post(self):
        if not self._scores or not self._django_url:
            return
        payload = {"turn": self._turn, "scores": list(self._scores.values())}
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post(
                    f"{self._django_url}/internal/test-runs/{self.run_id}/live-scores/",
                    json=payload,
                    headers={"X-Service-Token": self._service_token, "X-Tenant-Id": self.tenant_id},
                )
        except httpx.HTTPError as e:
            logger.warning("Live judge post failed: %s", e)

    @staticmethod
    def _parse_json(text: str) -> dict:
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except (ValueError, TypeError):
                    return {}
            return {}
