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


def test_get_caller_returns_audio_caller(agent_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller import get_caller, AudioCaller
    caller = get_caller("audio", agent_obj)
    assert isinstance(caller, AudioCaller)


def test_audio_caller_send_raises(agent_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller import AudioCaller
    caller = AudioCaller(agent_obj)
    with pytest.raises(NotImplementedError):
        caller.send("hello", "conv")


# ---------------------------------------------------------------------------
# runner.run_scenario — text mode end-to-end (mocked Anthropic + judge task)
# ---------------------------------------------------------------------------

def test_run_scenario_text_mode(tenant_a, in_tenant, test_run):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import run_scenario

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Sorry to hear that, let me help.")]

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat.anthropic.Anthropic") as MockAnthropic, \
         patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.tasks.run_judge_task") as mock_judge:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        mock_judge.delay = MagicMock()

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

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat.anthropic.Anthropic") as MockAnthropic, \
         patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.tasks.run_judge_task") as mock_judge:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        mock_judge.delay = MagicMock()
        with in_tenant(tenant_a):
            run_scenario(str(run.id))

    run.refresh_from_db()
    assert run.status == TestRun.Status.COMPLETED
    result = TestResult.objects.get(test_run=run)
    # Greeting should be first turn
    assert result.transcript[0]["speaker"] == "agent"
    assert result.transcript[0]["text"] == "Welcome!"


# ---------------------------------------------------------------------------
# views: agent connect (mocked httpx)
# ---------------------------------------------------------------------------

def test_agent_connect_action(tenant_a, in_tenant, agent_obj):
    from rest_framework.test import APIClient
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import TenantAPIKey

    with in_tenant(tenant_a):
        _, raw = TenantAPIKey.generate(tenant_a)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")

    fake_room = {"room_url": "https://daily.co/room-x", "room_name": "room-x",
                 "caller_token": "tok", "observer_url": "https://daily.co/room-x?t=obs"}

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.json.return_value = fake_room
        mock_post.return_value.raise_for_status = MagicMock()
        with in_tenant(tenant_a):
            resp = client.post(f"/api/v1/agents/{agent_obj.id}/connect/", {}, format="json")

    assert resp.status_code == 200
    assert "room_url" in resp.data


def test_agent_connect_pipecat_down(tenant_a, in_tenant, agent_obj):
    from rest_framework.test import APIClient
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import TenantAPIKey
    import httpx

    with in_tenant(tenant_a):
        _, raw = TenantAPIKey.generate(tenant_a)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.httpx.post") as mock_post:
        mock_post.side_effect = httpx.ConnectError("refused")
        with in_tenant(tenant_a):
            resp = client.post(f"/api/v1/agents/{agent_obj.id}/connect/", {}, format="json")

    assert resp.status_code == 503


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
