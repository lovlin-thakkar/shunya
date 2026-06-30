import json
import logging

import anthropic

from ..models import JudgeScore

logger = logging.getLogger(__name__)

PASS_THRESHOLD = 0.7
RUBRIC_FIELDS = JudgeScore.RUBRIC_FIELDS

_SYSTEM = (
    "You are a QA evaluator for a voice AI customer-service agent. "
    "Given a conversation transcript, score the AGENT (not the caller) on each "
    "rubric dimension from 0.0 (complete fail) to 1.0 (perfect). "
    "Return ONLY a JSON object — no prose, no markdown fences — with this shape:\n"
    '{"<field>": {"score": 0.0-1.0, "reasoning": "one sentence", "passed": true/false}, ...}'
)


def score_transcript(transcript: list[dict], rubric: dict) -> list[dict]:
    """Call Claude Sonnet to score a completed transcript.

    Returns a list of dicts with keys: field, score, reasoning, passed.
    Returns [] on any error (logged, not raised).
    """
    active_fields = [f for f in (rubric or {}) if f in RUBRIC_FIELDS] or list(RUBRIC_FIELDS)
    formatted = _format_transcript(transcript)

    try:
        # Explicit timeout + bounded retries: the SDK default is a 600s timeout
        # with retries, so an API stall here would block run_scenario_task and
        # leave the run wedged in "running" (UI shows "scoring with Claude Sonnet").
        client = anthropic.Anthropic(timeout=30.0, max_retries=1)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Score these rubric fields: {', '.join(active_fields)}\n\n"
                    f"Transcript:\n{formatted}"
                ),
            }],
        )
    except Exception:
        logger.exception("Claude Sonnet scoring API call failed")
        return []

    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Judge returned non-JSON response: %s", raw[:300])
        return []

    scores = []
    for field, val in data.items():
        if field not in RUBRIC_FIELDS:
            continue
        try:
            score = max(0.0, min(1.0, float(val.get("score", 0.0))))
        except (TypeError, ValueError):
            continue
        scores.append({
            "field": field,
            "score": round(score, 2),
            "reasoning": str(val.get("reasoning", ""))[:500],
            "passed": bool(val.get("passed", score >= PASS_THRESHOLD)),
        })

    return scores


def _format_transcript(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        speaker = t.get("speaker", "?").upper()
        text = t.get("text", "")
        quirks = t.get("quirks") or []
        suffix = f" [{', '.join(str(q) for q in quirks)}]" if quirks else ""
        lines.append(f"{speaker}: {text}{suffix}")
    return "\n".join(lines)
