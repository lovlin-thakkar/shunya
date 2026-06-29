import json
import logging
import re

import anthropic
from django.conf import settings

from .models import TestResult, JudgeScore

logger = logging.getLogger(__name__)

RUBRIC_FIELDS = JudgeScore.RUBRIC_FIELDS

JUDGE_SYSTEM_PROMPT = """You are a senior QA evaluator for voice AI agents.
Evaluate the provided conversation transcript against the scoring rubric.
Return a JSON object only — no prose, no markdown fences.
"""

JUDGE_TEMPLATE = """
Scenario persona: {persona}

Transcript:
{transcript}

Score each rubric field that is present in the weight map below.
For each field return:
  - score: 0.0–1.0 (0=fail, 0.5=partial, 1.0=pass)
  - reasoning: one sentence
  - passed: true if score >= 0.7

Rubric weights (higher weight = more important to this scenario):
{rubric}

Return JSON in this exact shape:
{{
  "scores": {{
    "<field_name>": {{"score": 0.0, "reasoning": "...", "passed": true}},
    ...
  }},
  "overall_reasoning": "..."
}}
"""


def _format_transcript(turns: list) -> str:
    lines = []
    for t in turns:
        quirk_note = f" [{', '.join(t['quirks'])}]" if t.get("quirks") else ""
        lines.append(f"{t['speaker'].upper()}{quirk_note}: {t['text']}")
    return "\n".join(lines)


def evaluate_result(test_result_id: str, rubric: dict):
    try:
        result = TestResult.objects.select_related(
            "test_run__scenario", "test_run__agent"
        ).get(id=test_result_id)
    except TestResult.DoesNotExist:
        logger.error(f"TestResult {test_result_id} not found")
        return

    scenario = result.test_run.scenario
    transcript_text = _format_transcript(result.transcript)

    # Only score the fields that have weights in this scenario's rubric
    active_rubric = {k: v for k, v in rubric.items() if k in RUBRIC_FIELDS}
    if not active_rubric:
        active_rubric = {f: 1.0 for f in RUBRIC_FIELDS}

    rubric_str = json.dumps(active_rubric, indent=2)
    user_prompt = JUDGE_TEMPLATE.format(
        persona=scenario.persona,
        transcript=transcript_text,
        rubric=rubric_str,
    )

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text.strip()
    # Strip markdown code fences if Claude wraps the response (handles ```json\n...\n``` style)
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
    raw = re.sub(r"\n?```\s*$", "", raw).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Judge returned non-JSON for TestResult {test_result_id}: {raw}")
        return

    scores_data = parsed.get("scores", {})
    judge_scores = []
    for field, data in scores_data.items():
        if field in RUBRIC_FIELDS:
            score = float(data.get("score", 0.0))
            js = JudgeScore(
                test_result=result,
                field=field,
                score=score,
                reasoning=data.get("reasoning", ""),
                passed=score >= 0.7,  # derive from score, ignore judge's boolean
            )
            judge_scores.append(js)

    JudgeScore.objects.bulk_create(judge_scores)

    # Re-evaluate overall pass/fail based on rubric-weighted judge scores
    if judge_scores:
        total_weight = sum(active_rubric.get(js.field, 1.0) for js in judge_scores)
        weighted_score = sum(
            js.score * active_rubric.get(js.field, 1.0) for js in judge_scores
        ) / total_weight if total_weight else 0.0

        passed = weighted_score >= 0.7 and result.passed
        result.passed = passed
        result.save(update_fields=["passed"])

    logger.info(
        f"Judge completed for TestResult {test_result_id}. "
        f"Fields scored: {list(scores_data.keys())}"
    )
