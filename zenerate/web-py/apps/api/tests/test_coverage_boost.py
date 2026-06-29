"""Tests targeting uncovered lines to bring overall coverage above 90%.

Focuses on:
- AgentChat (mocked Anthropic)
- Internal API endpoints (CallTurn, CallEnd)
- View actions: chat, test_runs, results, alerts, connect
- Authentication edge cases
- Model __str__ and AlertConfig.evaluate()
- Quirks DSL parser
- Assertion evaluator in runner
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from django.conf import settings
from rest_framework.test import APIClient

from zenlib.reusable_apps.multitenant.models import Tenant
from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import (
    Agent, Call, Scenario, TestRun, TestResult, JudgeScore,
    TenantAPIKey, Transcript, CallMetric, AlertConfig, AlertEvent,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_a(tenant_a, in_tenant):
    client = APIClient()
    with in_tenant(tenant_a):
        _, raw = TenantAPIKey.generate(tenant_a)
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    return client, tenant_a


@pytest.fixture
def svc_client(tenant_a):
    client = APIClient()
    client.credentials(
        HTTP_X_SERVICE_TOKEN=settings.SERVICE_TOKEN,
        HTTP_X_TENANT_ID=str(tenant_a.id),
    )
    return client, tenant_a


@pytest.fixture
def agent_obj(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        return Agent.objects.create(name="Test Agent", system_prompt="Be helpful.")


@pytest.fixture
def scenario_obj(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        return Scenario.objects.create(
            name="test_scen",
            yaml_content="name: test_scen\npersona: x\nsteps: []",
            persona="x",
        )


@pytest.fixture
def call_obj(tenant_a, in_tenant, agent_obj):
    with in_tenant(tenant_a):
        return Call.objects.create(
            agent=agent_obj, source=Call.Source.HUMAN, status=Call.Status.IN_PROGRESS,
        )


# ---------------------------------------------------------------------------
# Model __str__ methods
# ---------------------------------------------------------------------------

def test_agent_str(tenant_a, in_tenant, agent_obj):
    assert str(agent_obj) == "Test Agent"


def test_call_str(tenant_a, in_tenant, call_obj, agent_obj):
    assert "Test Agent" in str(call_obj)


def test_scenario_str(scenario_obj):
    assert str(scenario_obj) == "test_scen"


def test_test_run_str(tenant_a, in_tenant, agent_obj, scenario_obj):
    with in_tenant(tenant_a):
        run = TestRun.objects.create(agent=agent_obj, scenario=scenario_obj)
    assert "test_scen" in str(run)
    assert "text" in str(run)


def test_alert_config_str(tenant_a, in_tenant, agent_obj):
    with in_tenant(tenant_a):
        ac = AlertConfig.objects.create(
            agent=agent_obj, metric_name="latency", operator="gt",
            threshold=500.0, webhook_url="https://example.com/hook",
        )
    assert "latency" in str(ac)


def test_call_metric_str(tenant_a, in_tenant, call_obj):
    with in_tenant(tenant_a):
        m = CallMetric.objects.create(call=call_obj, name="latency_ms", value=123.0)
    assert "latency_ms=123.0" in str(m)


def test_judge_score_str(tenant_a, in_tenant, agent_obj, scenario_obj):
    with in_tenant(tenant_a):
        run = TestRun.objects.create(agent=agent_obj, scenario=scenario_obj)
        result = TestResult.objects.create(test_run=run, passed=True, transcript=[])
        js = JudgeScore.objects.create(
            test_result=result, field="safety", score=0.9, reasoning="good", passed=True
        )
    assert "safety" in str(js)
    assert "0.9" in str(js)


# ---------------------------------------------------------------------------
# AlertConfig.evaluate()
# ---------------------------------------------------------------------------

def test_alert_config_evaluate_gt(tenant_a, in_tenant, agent_obj):
    with in_tenant(tenant_a):
        ac = AlertConfig(agent=agent_obj, metric_name="x", operator="gt",
                         threshold=5.0, webhook_url="https://x.com")
    assert ac.evaluate(6.0) is True
    assert ac.evaluate(5.0) is False
    assert ac.evaluate(4.0) is False


def test_alert_config_evaluate_lte(tenant_a, in_tenant, agent_obj):
    with in_tenant(tenant_a):
        ac = AlertConfig(agent=agent_obj, metric_name="x", operator="lte",
                         threshold=10.0, webhook_url="https://x.com")
    assert ac.evaluate(10.0) is True
    assert ac.evaluate(9.9) is True
    assert ac.evaluate(10.1) is False


def test_alert_config_evaluate_eq(tenant_a, in_tenant, agent_obj):
    with in_tenant(tenant_a):
        ac = AlertConfig(agent=agent_obj, metric_name="x", operator="eq",
                         threshold=1.0, webhook_url="https://x.com")
    assert ac.evaluate(1.0) is True
    assert ac.evaluate(2.0) is False


# ---------------------------------------------------------------------------
# Authentication edge cases
# ---------------------------------------------------------------------------

def test_api_key_auth_invalid_key_raises_401():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Api-Key bad-key")
    resp = client.get("/api/v1/agents/")
    assert resp.status_code == 401


def test_service_token_auth_bad_token(tenant_a):
    client = APIClient()
    client.credentials(
        HTTP_X_SERVICE_TOKEN="wrong-token",
        HTTP_X_TENANT_ID=str(tenant_a.id),
    )
    resp = client.post("/internal/calls/start/", {}, format="json")
    assert resp.status_code == 401


def test_service_token_auth_unknown_tenant():
    client = APIClient()
    client.credentials(
        HTTP_X_SERVICE_TOKEN=settings.SERVICE_TOKEN,
        HTTP_X_TENANT_ID="99999",
    )
    resp = client.post("/internal/calls/start/", {}, format="json")
    assert resp.status_code == 401


def test_no_auth_header_returns_401():
    resp = APIClient().get("/api/v1/agents/")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Internal API: CallTurn and CallEnd
# ---------------------------------------------------------------------------

def test_internal_call_turn(svc_client, tenant_a, in_tenant, agent_obj):
    client, _ = svc_client
    with in_tenant(tenant_a):
        call = Call.objects.create(agent=agent_obj, source=Call.Source.TEST_TEXT,
                                   status=Call.Status.IN_PROGRESS)
        Transcript.objects.create(call=call, turns=[])

    resp = client.post(
        f"/internal/calls/{call.id}/turn/",
        {"speaker": "caller", "text": "Hello", "ts_ms": 0, "quirks": []},
        format="json",
    )
    assert resp.status_code == 200
    with in_tenant(tenant_a):
        t = Transcript.objects.get(call=call)
    assert t.turns[0]["text"] == "Hello"


def test_internal_call_turn_not_found(svc_client):
    client, _ = svc_client
    import uuid
    resp = client.post(
        f"/internal/calls/{uuid.uuid4()}/turn/",
        {"speaker": "caller", "text": "hi"},
        format="json",
    )
    assert resp.status_code == 404


def test_internal_call_end(svc_client, tenant_a, in_tenant, agent_obj):
    client, _ = svc_client
    with in_tenant(tenant_a):
        call = Call.objects.create(agent=agent_obj, source=Call.Source.HUMAN,
                                   status=Call.Status.IN_PROGRESS)
        Transcript.objects.create(call=call, turns=[])

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.urls.internal.compute_call_metrics") as mock_task:
        mock_task.delay = MagicMock()
        resp = client.post(f"/internal/calls/{call.id}/end/", {}, format="json")

    assert resp.status_code == 200
    with in_tenant(tenant_a):
        call.refresh_from_db()
    assert call.status == Call.Status.COMPLETED


def test_internal_call_end_not_found(svc_client):
    client, _ = svc_client
    import uuid
    resp = client.post(f"/internal/calls/{uuid.uuid4()}/end/", {}, format="json")
    assert resp.status_code == 404


def test_internal_call_start_agent_not_found(svc_client):
    client, _ = svc_client
    resp = client.post(
        "/internal/calls/start/",
        {"agent_id": "00000000-0000-0000-0000-000000000000", "source": "human"},
        format="json",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# View actions: test_runs, results, alerts, metrics
# ---------------------------------------------------------------------------

def test_agent_test_runs_action(client_a, tenant_a, in_tenant, agent_obj, scenario_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        TestRun.objects.create(agent=agent_obj, scenario=scenario_obj)
    with in_tenant(tenant_a):
        resp = client.get(f"/api/v1/agents/{agent_obj.id}/test-runs/")
    assert resp.status_code == 200
    assert len(resp.data) >= 1


def test_test_run_results_no_result(client_a, tenant_a, in_tenant, agent_obj, scenario_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        run = TestRun.objects.create(agent=agent_obj, scenario=scenario_obj)
    with in_tenant(tenant_a):
        resp = client.get(f"/api/v1/test-runs/{run.id}/results/")
    assert resp.status_code == 404


def test_test_run_results_with_result(client_a, tenant_a, in_tenant, agent_obj, scenario_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        run = TestRun.objects.create(agent=agent_obj, scenario=scenario_obj)
        TestResult.objects.create(test_run=run, passed=True, transcript=[], assertion_results=[])
    with in_tenant(tenant_a):
        resp = client.get(f"/api/v1/test-runs/{run.id}/results/")
    assert resp.status_code == 200
    assert resp.data["passed"] is True


def test_agents_alerts_get(client_a, tenant_a, in_tenant, agent_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.get(f"/api/v1/agents/{agent_obj.id}/alerts/")
    assert resp.status_code == 200
    assert resp.data == []


def test_agents_alerts_create(client_a, tenant_a, in_tenant, agent_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.post(
            f"/api/v1/agents/{agent_obj.id}/alerts/",
            {"metric_name": "latency_ms", "operator": "gt", "threshold": 1000,
             "webhook_url": "https://hooks.example.com/alert"},
            format="json",
        )
    assert resp.status_code == 201
    assert resp.data["metric_name"] == "latency_ms"


def test_calls_list(client_a, tenant_a, in_tenant, call_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.get("/api/v1/calls/")
    assert resp.status_code == 200


def test_calls_transcript_missing(client_a, tenant_a, in_tenant, call_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.get(f"/api/v1/calls/{call_obj.id}/transcript/")
    assert resp.status_code == 404


def test_calls_transcript_exists(client_a, tenant_a, in_tenant, call_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        Transcript.objects.create(call=call_obj, turns=[{"speaker": "agent", "text": "Hi", "ts_ms": 0, "quirks": []}])
        resp = client.get(f"/api/v1/calls/{call_obj.id}/transcript/")
    assert resp.status_code == 200


def test_test_run_create_missing_agent(client_a, tenant_a, in_tenant):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.post(
            "/api/v1/test-runs/",
            {"agent": "00000000-0000-0000-0000-000000000000", "scenario": "nope"},
            format="json",
        )
    assert resp.status_code == 404


def test_test_run_create_missing_scenario(client_a, tenant_a, in_tenant, agent_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.post(
            "/api/v1/test-runs/",
            {"agent": str(agent_obj.id), "scenario": "nonexistent"},
            format="json",
        )
    assert resp.status_code == 404


def test_scenarios_crud(client_a, tenant_a, in_tenant, scenario_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.get(f"/api/v1/scenarios/{scenario_obj.id}/")
    assert resp.status_code == 200
    assert resp.data["name"] == "test_scen"


# ---------------------------------------------------------------------------
# AgentChat (mocked Anthropic)
# ---------------------------------------------------------------------------

def test_agent_chat_send(tenant_a, in_tenant, agent_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat import AgentChat

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Hello! How can I help?")]

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        chat = AgentChat(agent_obj)
        result = chat.send("I need help", "conv-123")

    assert result["response"] == "Hello! How can I help?"
    assert result["conversation_id"] == "conv-123"
    assert "ts_ms" in result


def test_agent_chat_with_greeting(tenant_a, in_tenant):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat import AgentChat
    with in_tenant(tenant_a):
        agent = Agent.objects.create(
            name="Greeter", system_prompt="Be helpful.", greeting="Welcome!"
        )

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="How may I assist?")]

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        chat = AgentChat(agent)
        result = chat.send("hello", "conv-456")

    history = chat.get_history("conv-456")
    # Greeting prepended as user/assistant pair
    assert history[0]["content"] == "[call started]"
    assert history[1]["content"] == "Welcome!"


def test_agent_chat_view_action(client_a, tenant_a, in_tenant, agent_obj):
    client, _ = client_a
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="I can help with that.")]

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.chat.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        with in_tenant(tenant_a):
            resp = client.post(
                f"/api/v1/agents/{agent_obj.id}/chat/",
                {"message": "Can you help me?", "conversation_id": "test-conv"},
                format="json",
            )
    assert resp.status_code == 200
    assert resp.data["response"] == "I can help with that."


def test_agent_chat_view_missing_message(client_a, tenant_a, in_tenant, agent_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.post(
            f"/api/v1/agents/{agent_obj.id}/chat/",
            {"conversation_id": "x"},
            format="json",
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Quirks DSL
# ---------------------------------------------------------------------------

def test_strip_quirks_removes_tags():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.quirks import strip_quirks
    assert strip_quirks("[stutter] I want a refund") == "I want a refund"
    # hard_input keeps the value (substitutes the literal into the text)
    assert strip_quirks('My name is [hard_input:"John"]') == "My name is John"
    assert strip_quirks("[pause:3s] Yes") == "Yes"


def test_extract_quirk_tags():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.quirks import extract_quirk_tags
    tags = extract_quirk_tags("[stutter] text [pause:3s] more")
    assert "stutter" in tags
    assert "pause" in tags


# ---------------------------------------------------------------------------
# Runner assertion checker
# ---------------------------------------------------------------------------

def test_runner_assertions():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import _check_assertion

    transcript = [
        {"speaker": "caller", "text": "I need a refund"},
        {"speaker": "agent", "text": "I'm sorry for the inconvenience. Let me help you."},
    ]
    full_agent = "i'm sorry for the inconvenience. let me help you."

    assert _check_assertion("agent_acknowledges_frustration", transcript, full_agent) is True
    assert _check_assertion("no_hallucinated_policy", transcript, full_agent) is True
    assert _check_assertion("resolved_within_5_turns", transcript, full_agent) is True
    assert _check_assertion("unknown_assertion", transcript, full_agent) is True


def test_runner_resolved_within_turns_fail():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import _check_assertion
    transcript = [{"speaker": "agent", "text": f"turn {i}"} for i in range(7)]
    full_agent = " ".join(t["text"] for t in transcript)
    assert _check_assertion("resolved_within_5_turns", transcript, full_agent) is False
