"""Unit tests for the LLM judge (mocked Anthropic calls)."""
import json
import pytest
from unittest.mock import MagicMock, patch

from apps.testing.judge import _format_transcript, evaluate_result, RUBRIC_FIELDS


def test_format_transcript():
    turns = [
        {"speaker": "caller", "text": "Hello", "quirks": ["stutter"]},
        {"speaker": "agent", "text": "Hi there!", "quirks": []},
    ]
    output = _format_transcript(turns)
    assert "CALLER [stutter]: Hello" in output
    assert "AGENT: Hi there!" in output


def test_format_transcript_no_quirks():
    turns = [{"speaker": "caller", "text": "Hi", "quirks": []}]
    output = _format_transcript(turns)
    assert "[" not in output  # no quirk brackets


@pytest.mark.django_db
@patch("apps.testing.judge.anthropic.Anthropic")
def test_evaluate_result_creates_judge_scores(MockAnthropic):
    from apps.testing.models import TestRun, TestResult, JudgeScore, Scenario
    from apps.agents.models import Agent

    agent = Agent.objects.create(name="Test Agent", system_prompt="Be helpful.")
    scenario = Scenario.objects.create(
        name="test_scene",
        persona="A caller",
        steps=[],
        assertions=[],
        rubric={"instruction_following": 1.0, "csat_tone": 1.0},
    )
    run = TestRun.objects.create(agent=agent, scenario=scenario, mode=TestRun.Mode.TEXT)
    result = TestResult.objects.create(
        test_run=run,
        passed=True,
        transcript=[
            {"speaker": "caller", "text": "Hello", "quirks": []},
            {"speaker": "agent", "text": "Hi!", "quirks": [], "ts_ms": 200},
        ],
        assertion_results=[],
    )

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json.dumps({
        "scores": {
            "instruction_following": {"score": 0.9, "reasoning": "Good", "passed": True},
            "csat_tone": {"score": 0.8, "reasoning": "Friendly", "passed": True},
        },
        "overall_reasoning": "Strong performance."
    }))]
    MockAnthropic.return_value.messages.create.return_value = mock_message

    evaluate_result(str(result.id), {"instruction_following": 1.0, "csat_tone": 1.0})

    scores = JudgeScore.objects.filter(test_result=result)
    assert scores.count() == 2
    fields = {s.field for s in scores}
    assert "instruction_following" in fields
    assert "csat_tone" in fields


@pytest.mark.django_db
@patch("apps.testing.judge.anthropic.Anthropic")
def test_evaluate_result_handles_bad_json(MockAnthropic):
    from apps.testing.models import TestRun, TestResult, JudgeScore, Scenario
    from apps.agents.models import Agent

    agent = Agent.objects.create(name="Agent2", system_prompt="Be helpful.")
    scenario = Scenario.objects.create(name="s2", persona="x", steps=[], assertions=[], rubric={})
    run = TestRun.objects.create(agent=agent, scenario=scenario, mode=TestRun.Mode.TEXT)
    result = TestResult.objects.create(
        test_run=run, passed=True, transcript=[], assertion_results=[]
    )

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="not json at all")]
    MockAnthropic.return_value.messages.create.return_value = mock_message

    # Should not raise, just log and return
    evaluate_result(str(result.id), {})
    assert JudgeScore.objects.filter(test_result=result).count() == 0
