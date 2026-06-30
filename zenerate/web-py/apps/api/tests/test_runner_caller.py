"""Tests for runner, caller, tasks, and quirks.parse_step — the remaining coverage gaps."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import (
    Agent, Scenario, TestRun, TestResult,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agent_obj(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        return Agent.objects.create(name="Runner Agent", system_prompt="Be helpful.")


@pytest.fixture
def scenario_obj(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        return Scenario.objects.create(
            name="runner_scen",
            yaml_content="name: runner_scen\npersona: angry customer\nsteps: []",
            persona="angry customer",
            steps=[{"text": "I need help", "raw": "I need help", "quirks": []}],
            assertions=["agent_acknowledges_frustration", "resolved_within_5_turns"],
            rubric={"safety": 1.0},
        )


@pytest.fixture
def test_run(tenant_a, in_tenant, agent_obj, scenario_obj):
    with in_tenant(tenant_a):
        return TestRun.objects.create(agent=agent_obj, scenario=scenario_obj, mode=TestRun.Mode.TEXT)


# ---------------------------------------------------------------------------
# quirks.parse_step
# ---------------------------------------------------------------------------

def test_parse_step_plain():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.quirks import parse_step
    result = parse_step("Hello, I need help")
    assert result["text"] == "Hello, I need help"
    assert result["raw"] == "Hello, I need help"
    assert result["quirks"] == []


def test_parse_step_with_stutter():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.quirks import parse_step
    result = parse_step("[stutter] I w-want a refund")
    assert result["text"] == "I w-want a refund"
    assert any(q["tag"] == "stutter" for q in result["quirks"])


def test_parse_step_with_hard_input():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.quirks import parse_step
    result = parse_step('My name is [hard_input:"Jane Smith"]')
    assert result["text"] == "My name is Jane Smith"
    assert any(q["tag"] == "hard_input" and q["value"] == "Jane Smith" for q in result["quirks"])


def test_parse_step_with_pause():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.quirks import parse_step
    result = parse_step("[pause:3s] Yes, I want that")
    assert result["text"] == "Yes, I want that"
    assert any(q["tag"] == "pause" for q in result["quirks"])


# ---------------------------------------------------------------------------
# TextCaller
# ---------------------------------------------------------------------------

def test_text_caller_send(agent_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller import TextCaller

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="I can help with that.")]

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        caller = TextCaller(agent_obj)
        result = caller.send("I need a refund", "conv-1")

    assert result["response"] == "I can help with that."
    assert "ts_ms" in result


def test_text_caller_send_with_quirks(agent_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller import TextCaller

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="I understand.")]

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        caller = TextCaller(agent_obj)
        result = caller.send("[stutter] I w-want help", "conv-2")

    assert result["response"] == "I understand."
    assert "stutter" in result["quirks"]


def test_text_caller_reset(agent_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller import TextCaller

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat.anthropic.Anthropic"):
        caller = TextCaller(agent_obj)
        original_chat = caller._chat
        caller.reset()
        assert caller._chat is not original_chat


def test_get_caller_returns_text_caller(agent_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller import get_caller, TextCaller
    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat.anthropic.Anthropic"):
        caller = get_caller("text", agent_obj)
    assert isinstance(caller, TextCaller)


# ---------------------------------------------------------------------------
# runner.run_scenario — text mode end-to-end (mocked Anthropic + judge task)
# ---------------------------------------------------------------------------

def test_run_scenario_text_mode(tenant_a, in_tenant, test_run):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import run_scenario

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Sorry to hear that, let me help.")]

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        with in_tenant(tenant_a):
            run_scenario(str(test_run.id))

    test_run.refresh_from_db()
    assert test_run.status == TestRun.Status.COMPLETED
    assert TestResult.objects.filter(test_run=test_run).exists()


def test_run_scenario_not_found(tenant_a, in_tenant):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import run_scenario
    import uuid
    with in_tenant(tenant_a):
        run_scenario(str(uuid.uuid4()))  # Should log error and return, not raise


def test_run_scenario_with_greeting(tenant_a, in_tenant):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import run_scenario

    with in_tenant(tenant_a):
        agent = Agent.objects.create(name="Greeter", system_prompt="x", greeting="Welcome!")
        scenario = Scenario.objects.create(
            name="greet_scen", yaml_content="x", persona="x",
            steps=[{"text": "hi", "raw": "hi", "quirks": []}],
        )
        run = TestRun.objects.create(agent=agent, scenario=scenario)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="How may I help?")]

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        with in_tenant(tenant_a):
            run_scenario(str(run.id))

    run.refresh_from_db()
    assert run.status == TestRun.Status.COMPLETED
    result = TestResult.objects.get(test_run=run)
    # Greeting should be first turn
    assert result.transcript[0]["speaker"] == "agent"
    assert result.transcript[0]["text"] == "Welcome!"


# ---------------------------------------------------------------------------
# run_scenario edge cases
# ---------------------------------------------------------------------------

def test_run_scenario_exception_marks_failed(tenant_a, in_tenant, test_run):
    """If TextCaller raises, the run should be marked FAILED, not bubble up."""
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import run_scenario

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller.AgentChat") as MockChat:
        MockChat.return_value.send.side_effect = RuntimeError("API exploded")
        with in_tenant(tenant_a):
            run_scenario(str(test_run.id))

    test_run.refresh_from_db()
    assert test_run.status == TestRun.Status.FAILED


# ---------------------------------------------------------------------------
# RemoteAudioCaller — remote ElevenLabs agent path
# ---------------------------------------------------------------------------

@pytest.fixture
def remote_agent(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        return Agent.objects.create(
            name="Remote EL Agent",
            system_prompt="(ignored for remote)",
            target_type=Agent.TargetType.ELEVENLABS,
            el_agent_id="agent_abc123",
        )


def test_get_caller_returns_remote_caller(remote_agent):
    """An ELEVENLABS-target agent dispatches to RemoteAudioCaller regardless of mode."""
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller import (
        get_caller, RemoteAudioCaller,
    )
    assert isinstance(get_caller("text", remote_agent), RemoteAudioCaller)
    assert isinstance(get_caller("audio", remote_agent), RemoteAudioCaller)


def test_remote_caller_send_raises(remote_agent):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller import RemoteAudioCaller
    with pytest.raises(NotImplementedError):
        RemoteAudioCaller(remote_agent).send("hi", "conv")


def test_remote_caller_run_scenario_posts(remote_agent):
    """run_scenario POSTs el_agent_id + steps to the caller service and maps the
    transcript, defaulting missing quirks/ts_ms."""
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller import RemoteAudioCaller

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"transcript": [{"speaker": "agent", "text": "Hello"}]}
    mock_resp.raise_for_status = MagicMock()

    caller = RemoteAudioCaller(remote_agent)
    steps = [{"text": "hi", "raw": "hi", "quirks": []}]
    with patch("httpx.post", return_value=mock_resp) as mock_post:
        out = caller.run_scenario(steps, "conv", recording_id="rec-1")

    url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
    assert url.endswith("/remote/run")
    assert kwargs["json"]["el_agent_id"] == "agent_abc123"
    assert kwargs["json"]["recording_id"] == "rec-1"
    assert out == [{"speaker": "agent", "text": "Hello", "quirks": [], "ts_ms": 0}]


def test_run_scenario_remote_mode(tenant_a, in_tenant, remote_agent):
    """End-to-end runner with a remote agent takes the run_scenario (WS) path
    even when the run mode is text, and completes."""
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import run_scenario

    with in_tenant(tenant_a):
        scenario = Scenario.objects.create(
            name="remote_scen", yaml_content="x", persona="x",
            steps=[{"text": "I need a refund", "raw": "I need a refund", "quirks": []}],
            assertions=["resolved_within_5_turns"],
        )
        run = TestRun.objects.create(agent=remote_agent, scenario=scenario, mode=TestRun.Mode.TEXT)

    transcript = [
        {"speaker": "caller", "text": "I need a refund", "ts_ms": 0, "quirks": []},
        {"speaker": "agent", "text": "Happy to help with that.", "ts_ms": 1200, "quirks": []},
    ]
    with patch(
        "zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller.RemoteAudioCaller.run_scenario",
        return_value=transcript,
    ) as mock_run:
        with in_tenant(tenant_a):
            run_scenario(str(run.id))

    assert mock_run.called
    run.refresh_from_db()
    assert run.status == TestRun.Status.COMPLETED
    result = TestResult.objects.get(test_run=run)
    assert any(t["speaker"] == "agent" for t in result.transcript)


# ---------------------------------------------------------------------------
# _post_call_score — text mode scoring writes JudgeScore rows
# ---------------------------------------------------------------------------

def test_post_call_score_writes_judge_scores(tenant_a, in_tenant, test_run):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import run_scenario
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import JudgeScore

    mock_chat = MagicMock()
    mock_chat.content = [MagicMock(text="I can help you.")]

    mock_scores = [
        {"field": "safety", "score": 0.9, "reasoning": "safe", "passed": True},
        {"field": "goal_completion", "score": 0.8, "reasoning": "done", "passed": True},
    ]
    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat.anthropic.Anthropic") as MockA:
        MockA.return_value.messages.create.return_value = mock_chat
        with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner.score_transcript",
                   return_value=mock_scores) as mock_score:
            with in_tenant(tenant_a):
                run_scenario(str(test_run.id))

    assert mock_score.called
    with in_tenant(tenant_a):
        scores = list(JudgeScore.objects.filter(test_result__test_run=test_run))
    assert len(scores) == 2
    fields = {s.field for s in scores}
    assert "safety" in fields
    assert "goal_completion" in fields


def test_post_call_score_skipped_when_live_scores_present(tenant_a, in_tenant, remote_agent):
    """Remote mode: _promote_live_scores found scores → _post_call_score must not run."""
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import run_scenario
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import JudgeScore

    with in_tenant(tenant_a):
        scenario = Scenario.objects.create(
            name="live_skip_scen", yaml_content="x", persona="x",
            steps=[{"text": "hello", "raw": "hello", "quirks": []}],
            rubric={"safety": 1.0},
        )
        run = TestRun.objects.create(agent=remote_agent, scenario=scenario)
        # Pre-populate live_scores as if Scorer already ran
        run.live_scores = {"turn": 1, "scores": [
            {"field": "safety", "score": 0.95, "reasoning": "great", "passed": True}
        ]}
        run.save(update_fields=["live_scores"])

    transcript = [{"speaker": "agent", "text": "Hi", "ts_ms": 0, "quirks": []}]
    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller.RemoteAudioCaller.run_scenario",
               return_value=transcript):
        with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner.score_transcript") as mock_score:
            with in_tenant(tenant_a):
                run_scenario(str(run.id))

    mock_score.assert_not_called()
    with in_tenant(tenant_a):
        assert JudgeScore.objects.filter(test_result__test_run=run, field="safety").exists()


# ---------------------------------------------------------------------------
# agent.chat — ElevenLabs agents must be rejected
# ---------------------------------------------------------------------------

def test_agent_chat_rejects_elevenlabs_agent(tenant_a, in_tenant, remote_agent):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import TenantAPIKey
    from rest_framework.test import APIClient

    with in_tenant(tenant_a):
        _, raw = TenantAPIKey.generate(tenant_a)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    with in_tenant(tenant_a):
        resp = client.post(
            f"/api/v1/agents/{remote_agent.id}/chat/",
            {"message": "hello", "conversation_id": "conv-1"},
            format="json",
        )
    assert resp.status_code == 400
    assert "ElevenLabs" in resp.data["error"]
