"""Coverage boost tests: metrics, views (ElevenLabs, run-evals, clear),
serializers (ScenarioSerializer, AlertConfigSerializer), and remaining assertion checks.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call as _call
import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import (
    Agent, Scenario, TestRun, TestResult, JudgeScore, Call, Transcript,
    CallMetric, AlertConfig, AlertEvent, TenantAPIKey, ElevenLabsCredential,
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
def agent_obj(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        return Agent.objects.create(name="Coverage Agent", system_prompt="Be helpful.")


@pytest.fixture
def remote_agent(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        return Agent.objects.create(
            name="EL Agent", system_prompt="",
            target_type=Agent.TargetType.ELEVENLABS, el_agent_id="agent_test123",
        )


@pytest.fixture
def scenario_obj(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        return Scenario.objects.create(
            name="cov_scen", yaml_content="name: cov_scen\npersona: test\nsteps: []",
            persona="test user", steps=[{"text": "Hello", "raw": "Hello", "quirks": []}],
            assertions=["agent_acknowledges_frustration"],
            rubric={"safety": 1.0, "goal_completion": 1.0},
        )


@pytest.fixture
def call_obj(tenant_a, in_tenant, agent_obj):
    with in_tenant(tenant_a):
        c = Call.objects.create(agent=agent_obj, source=Call.Source.TEST_TEXT,
                                status=Call.Status.IN_PROGRESS)
        c.started_at = timezone.now()
        c.save(update_fields=["started_at"])
        return c


# ===========================================================================
# metrics.py — compute_metrics, _is_safe_webhook_url, _check_alerts, _fire_alert
# ===========================================================================

def test_compute_metrics_basic(tenant_a, in_tenant, agent_obj, call_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics import compute_metrics

    with in_tenant(tenant_a):
        Transcript.objects.create(call=call_obj, turns=[
            {"speaker": "caller", "text": "Hello", "ts_ms": 0, "quirks": []},
            {"speaker": "agent", "text": "Hi", "ts_ms": 800, "quirks": []},
            {"speaker": "caller", "text": "Bye", "ts_ms": 2000, "quirks": ["interrupt"]},
            {"speaker": "agent", "text": "Goodbye", "ts_ms": 2500, "quirks": []},
        ])
        call_obj.ended_at = timezone.now()
        call_obj.save(update_fields=["ended_at"])

    with in_tenant(tenant_a):
        compute_metrics(str(call_obj.id))
        metrics = CallMetric.objects.filter(call=call_obj)

    names = set(metrics.values_list("name", flat=True))
    assert "turn_count" in names
    assert "avg_latency_ms" in names
    assert "interruption_count" in names


def test_compute_metrics_call_not_found(tenant_a, in_tenant):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics import compute_metrics
    import uuid
    with in_tenant(tenant_a):
        compute_metrics(str(uuid.uuid4()))  # log error and return


def test_compute_metrics_no_transcript(tenant_a, in_tenant, call_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics import compute_metrics
    with in_tenant(tenant_a):
        compute_metrics(str(call_obj.id))  # log warning and return
    with in_tenant(tenant_a):
        assert CallMetric.objects.filter(call=call_obj).count() == 0


def test_is_safe_webhook_url_valid():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics import _is_safe_webhook_url
    # A genuine public URL (or unresolvable) should not be blocked
    assert _is_safe_webhook_url("https://nonexistent-host-xyz123.example.com/hook") is True


def test_is_safe_webhook_url_localhost():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics import _is_safe_webhook_url
    assert _is_safe_webhook_url("http://localhost/hook") is False


def test_is_safe_webhook_url_metadata_server():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics import _is_safe_webhook_url
    assert _is_safe_webhook_url("http://169.254.169.254/latest") is False


def test_is_safe_webhook_url_bad_scheme():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics import _is_safe_webhook_url
    assert _is_safe_webhook_url("ftp://example.com/hook") is False


def test_percentile():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics import _percentile
    assert _percentile([], 95) == 0.0
    assert _percentile([100, 200, 300, 400, 500], 50) == 300.0


def test_check_alerts_fires_when_threshold_exceeded(tenant_a, in_tenant, agent_obj, call_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics import _check_alerts

    with in_tenant(tenant_a):
        config = AlertConfig.objects.create(
            agent=agent_obj, metric_name="turn_count",
            operator="gt", threshold=2.0,
            webhook_url="https://nonexistent-webhook-host.example.com/hook",
        )

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics._fire_alert") as mock_fire:
        with in_tenant(tenant_a):
            _check_alerts(call_obj, {"turn_count": 5.0})
        mock_fire.assert_called_once()


def test_check_alerts_does_not_fire_below_threshold(tenant_a, in_tenant, agent_obj, call_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics import _check_alerts

    with in_tenant(tenant_a):
        AlertConfig.objects.create(
            agent=agent_obj, metric_name="turn_count",
            operator="gt", threshold=10.0,
            webhook_url="https://x.example.com/hook",
        )

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics._fire_alert") as mock_fire:
        with in_tenant(tenant_a):
            _check_alerts(call_obj, {"turn_count": 3.0})
        mock_fire.assert_not_called()


def test_fire_alert_skips_unsafe_url(tenant_a, in_tenant, agent_obj, call_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics import _fire_alert
    import httpx

    with in_tenant(tenant_a):
        config = AlertConfig.objects.create(
            agent=agent_obj, metric_name="turn_count",
            operator="gt", threshold=1.0,
            webhook_url="http://localhost/hook",
        )

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics.httpx") as mock_httpx:
        with in_tenant(tenant_a):
            _fire_alert(config, call_obj, 5.0)
        # httpx.Client.post should NOT be called for an unsafe URL
        mock_httpx.Client.assert_not_called()

    with in_tenant(tenant_a):
        assert AlertEvent.objects.filter(alert_config=config, call=call_obj).exists()


def test_fire_alert_sends_webhook(tenant_a, in_tenant, agent_obj, call_obj):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics import _fire_alert

    with in_tenant(tenant_a):
        config = AlertConfig.objects.create(
            agent=agent_obj, metric_name="turn_count",
            operator="gt", threshold=1.0,
            webhook_url="https://nonexistent-safe-webhook.example.com/hook",
        )

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.services.metrics.httpx.Client") as MockClient:
        mock_ctx = MagicMock()
        MockClient.return_value.__enter__.return_value = mock_ctx
        MockClient.return_value.__exit__.return_value = False
        with in_tenant(tenant_a):
            _fire_alert(config, call_obj, 5.0)
        mock_ctx.post.assert_called_once()


# ===========================================================================
# runner.py — remaining _check_assertion paths
# ===========================================================================

def test_assertion_appointment_confirmed():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import _check_assertion
    t = [{"speaker": "agent", "text": "Your appointment is confirmed for 3pm."}]
    full = "your appointment is confirmed for 3pm."
    assert _check_assertion("appointment_confirmed", t, full) is True


def test_assertion_appointment_not_confirmed():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import _check_assertion
    t = [{"speaker": "agent", "text": "I need to check availability."}]
    full = "i need to check availability."
    assert _check_assertion("appointment_confirmed", t, full) is False


def test_assertion_correct_date_time_captured():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import _check_assertion
    t = [{"speaker": "agent", "text": "I have you booked for Tuesday at 3pm."}]
    full = "i have you booked for tuesday at 3pm."
    assert _check_assertion("correct_date_time_captured", t, full) is True


def test_assertion_correct_date_time_not_captured():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import _check_assertion
    t = [{"speaker": "agent", "text": "We will contact you soon."}]
    full = "we will contact you soon."
    assert _check_assertion("correct_date_time_captured", t, full) is False


def test_assertion_contact_details_phone(tenant_a):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import _check_assertion
    t = [
        {"speaker": "caller", "text": "My number is 415-555-0192"},
        {"speaker": "agent", "text": "Got it, I noted 415-555-0192 for you."},
    ]
    full = "got it, i noted 415-555-0192 for you."
    assert _check_assertion("contact_details_collected", t, full) is True


def test_assertion_contact_details_acknowledgement():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import _check_assertion
    t = [
        {"speaker": "caller", "text": "Here are my details."},
        {"speaker": "agent", "text": "Thank you, I've noted that for you."},
        {"speaker": "agent", "text": "All set."},
    ]
    full = "thank you, i've noted that for you. all set."
    assert _check_assertion("contact_details_collected", t, full) is True


def test_assertion_confirmation_number():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import _check_assertion
    t = [{"speaker": "agent", "text": "Your reference number is ABC123."}]
    full = "your reference number is abc123."
    assert _check_assertion("agent_provides_confirmation_number_or_summary", t, full) is True


def test_assertion_asks_for_clarification():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import _check_assertion
    t = [{"speaker": "agent", "text": "Could you please repeat that?"}]
    full = "could you please repeat that?"
    assert _check_assertion("agent_asks_for_clarification_when_unclear", t, full) is True


def test_assertion_resolved_within_6_turns():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.runner import _check_assertion
    transcript = [{"speaker": "agent", "text": f"turn {i}"} for i in range(6)]
    full = " ".join(t["text"] for t in transcript)
    assert _check_assertion("resolved_within_6_turns", transcript, full) is True
    transcript7 = transcript + [{"speaker": "agent", "text": "turn 7"}]
    full7 = " ".join(t["text"] for t in transcript7)
    assert _check_assertion("resolved_within_6_turns", transcript7, full7) is False


# ===========================================================================
# views — ElevenLabsIntegrationView
# ===========================================================================

def test_elevenlabs_integration_get_not_configured(client_a, tenant_a, in_tenant):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.get("/api/v1/integrations/elevenlabs/")
    assert resp.status_code == 200
    assert resp.data["configured"] is False


def test_elevenlabs_integration_put_valid_key(client_a, tenant_a, in_tenant):
    client, _ = client_a
    mock_r = MagicMock(status_code=200)
    mock_r.json.return_value = {"agents": []}
    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.httpx.get", return_value=mock_r):
        with in_tenant(tenant_a):
            resp = client.put("/api/v1/integrations/elevenlabs/", {"api_key": "el_abc123456789"}, format="json")
    assert resp.status_code == 200
    assert resp.data["configured"] is True
    with in_tenant(tenant_a):
        assert ElevenLabsCredential.objects.filter(tenant=tenant_a).exists()


def test_elevenlabs_integration_put_missing_key(client_a, tenant_a, in_tenant):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.put("/api/v1/integrations/elevenlabs/", {}, format="json")
    assert resp.status_code == 400


def test_elevenlabs_integration_put_invalid_key(client_a, tenant_a, in_tenant):
    client, _ = client_a
    mock_r = MagicMock(status_code=401)
    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.httpx.get", return_value=mock_r):
        with in_tenant(tenant_a):
            resp = client.put("/api/v1/integrations/elevenlabs/", {"api_key": "bad-key"}, format="json")
    assert resp.status_code == 400


def test_elevenlabs_integration_put_connection_error(client_a, tenant_a, in_tenant):
    import httpx
    client, _ = client_a
    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.httpx.get",
               side_effect=httpx.ConnectError("timeout")):
        with in_tenant(tenant_a):
            resp = client.put("/api/v1/integrations/elevenlabs/", {"api_key": "el_abc123456789"}, format="json")
    assert resp.status_code == 502


def test_elevenlabs_integration_get_configured(client_a, tenant_a, in_tenant):
    client, _ = client_a
    with in_tenant(tenant_a):
        ElevenLabsCredential.objects.create(
            tenant=tenant_a, api_key="el_test12345678", key_hint="el_t…5678"
        )
        resp = client.get("/api/v1/integrations/elevenlabs/")
    assert resp.status_code == 200
    assert resp.data["configured"] is True
    assert resp.data["key_hint"] == "el_t…5678"


# ===========================================================================
# views — sync_elevenlabs
# ===========================================================================

def test_sync_elevenlabs_no_credential(client_a, tenant_a, in_tenant):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.post("/api/v1/agents/sync-elevenlabs/")
    assert resp.status_code == 400
    assert "not connected" in resp.data["error"].lower()


def test_sync_elevenlabs_success(client_a, tenant_a, in_tenant):
    client, _ = client_a
    with in_tenant(tenant_a):
        ElevenLabsCredential.objects.create(
            tenant=tenant_a, api_key="el_key12345678", key_hint="el_k…5678"
        )
    mock_r = MagicMock(status_code=200)
    mock_r.json.return_value = {"agents": [
        {"agent_id": "agent_newone", "name": "New Agent"},
    ]}
    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.httpx.get", return_value=mock_r):
        with in_tenant(tenant_a):
            resp = client.post("/api/v1/agents/sync-elevenlabs/")
    assert resp.status_code == 200
    with in_tenant(tenant_a):
        assert Agent.objects.filter(el_agent_id="agent_newone", tenant=tenant_a).exists()


def test_sync_elevenlabs_deactivates_removed_agents(client_a, tenant_a, in_tenant):
    client, _ = client_a
    with in_tenant(tenant_a):
        ElevenLabsCredential.objects.create(
            tenant=tenant_a, api_key="el_key12345678", key_hint="el_k…5678"
        )
        # Pre-existing agent that won't appear in the sync response
        old_agent = Agent.objects.create(
            name="Old Agent", system_prompt="",
            target_type=Agent.TargetType.ELEVENLABS, el_agent_id="agent_old",
        )
    mock_r = MagicMock(status_code=200)
    mock_r.json.return_value = {"agents": [{"agent_id": "agent_new2", "name": "New 2"}]}
    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.httpx.get", return_value=mock_r):
        with in_tenant(tenant_a):
            client.post("/api/v1/agents/sync-elevenlabs/")
    with in_tenant(tenant_a):
        old_agent.refresh_from_db()
    assert old_agent.status == Agent.Status.INACTIVE


def test_sync_elevenlabs_401(client_a, tenant_a, in_tenant):
    client, _ = client_a
    with in_tenant(tenant_a):
        ElevenLabsCredential.objects.create(
            tenant=tenant_a, api_key="el_key12345678", key_hint="el_k…5678"
        )
    mock_r = MagicMock(status_code=401)
    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.httpx.get", return_value=mock_r):
        with in_tenant(tenant_a):
            resp = client.post("/api/v1/agents/sync-elevenlabs/")
    assert resp.status_code == 400


# ===========================================================================
# views — run-evals (run all scenarios for an agent)
# ===========================================================================

def test_run_evals_no_scenarios(client_a, tenant_a, in_tenant, agent_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.post(f"/api/v1/agents/{agent_obj.id}/run-evals/", {}, format="json")
    assert resp.status_code == 404


def test_run_evals_dispatches_group(client_a, tenant_a, in_tenant, agent_obj, scenario_obj):
    client, _ = client_a

    mock_group = MagicMock()
    mock_result = MagicMock()
    mock_result.id = "grp-id-1"
    mock_result.results = [MagicMock(id=f"t-{i}") for i in range(1)]
    mock_group.apply_async.return_value = mock_result

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.celery_group", return_value=mock_group), \
         patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.run_scenario_task"):
        with in_tenant(tenant_a):
            resp = client.post(f"/api/v1/agents/{agent_obj.id}/run-evals/", {}, format="json")

    assert resp.status_code == 201
    assert "runs" in resp.data
    assert resp.data["parallelism"] == 1


# ===========================================================================
# views — test run clear endpoint
# ===========================================================================

def test_test_runs_clear(client_a, tenant_a, in_tenant, agent_obj, scenario_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        TestRun.objects.create(agent=agent_obj, scenario=scenario_obj)
        TestRun.objects.create(agent=agent_obj, scenario=scenario_obj)
    with in_tenant(tenant_a):
        resp = client.delete("/api/v1/test-runs/clear/")
    assert resp.status_code == 200
    assert resp.data["deleted"] >= 2
    with in_tenant(tenant_a):
        assert TestRun.objects.filter(tenant=tenant_a).count() == 0


# ===========================================================================
# views — agent PATCH (dynamic_variables update)
# ===========================================================================

def test_agent_patch_dynamic_variables(client_a, tenant_a, in_tenant, remote_agent):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.patch(
            f"/api/v1/agents/{remote_agent.id}/",
            {"dynamic_variables": {"company_name": "Acme Corp"}},
            format="json",
        )
    assert resp.status_code == 200
    assert resp.data["dynamic_variables"] == {"company_name": "Acme Corp"}
    with in_tenant(tenant_a):
        remote_agent.refresh_from_db()
    assert remote_agent.dynamic_variables == {"company_name": "Acme Corp"}


def test_agent_patch_clears_dynamic_variables(client_a, tenant_a, in_tenant, remote_agent):
    client, _ = client_a
    with in_tenant(tenant_a):
        remote_agent.dynamic_variables = {"old_key": "old_val"}
        remote_agent.save()
    with in_tenant(tenant_a):
        resp = client.patch(
            f"/api/v1/agents/{remote_agent.id}/",
            {"dynamic_variables": {}},
            format="json",
        )
    assert resp.status_code == 200
    with in_tenant(tenant_a):
        remote_agent.refresh_from_db()
    assert remote_agent.dynamic_variables == {}


# ===========================================================================
# serializers — ScenarioSerializer create with yaml auto-generation
# ===========================================================================

def test_scenario_create_via_api_auto_yaml(client_a, tenant_a, in_tenant):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.post("/api/v1/scenarios/", {
            "name": "api_created_scen",
            "persona": "An annoyed customer",
            "steps": ["I want a refund", "Now please"],
            "assertions": ["agent_acknowledges_frustration"],
        }, format="json")
    assert resp.status_code == 201
    # yaml_content should have been auto-generated
    assert "api_created_scen" in resp.data["yaml_content"]
    # steps normalised to [{text, raw, quirks}]
    assert resp.data["steps"][0]["text"] == "I want a refund"


def test_scenario_create_steps_as_dicts(client_a, tenant_a, in_tenant):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.post("/api/v1/scenarios/", {
            "name": "dict_steps_scen",
            "persona": "x",
            "steps": [{"text": "Hello", "raw": "Hello", "quirks": []}],
        }, format="json")
    assert resp.status_code == 201
    assert resp.data["steps"][0]["raw"] == "Hello"


def test_scenario_update_compatible_agents(client_a, tenant_a, in_tenant, agent_obj, scenario_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.patch(
            f"/api/v1/scenarios/{scenario_obj.id}/",
            {"compatible_agent_ids": [str(agent_obj.id)]},
            format="json",
        )
    assert resp.status_code == 200
    assert agent_obj.name in resp.data["compatible_agents"]


# ===========================================================================
# serializers — AlertConfigSerializer SSRF validation
# ===========================================================================

def test_alert_config_webhook_rejects_localhost(client_a, tenant_a, in_tenant, agent_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.post(
            f"/api/v1/agents/{agent_obj.id}/alerts/",
            {"metric_name": "turn_count", "operator": "gt", "threshold": 5,
             "webhook_url": "http://localhost/hook"},
            format="json",
        )
    assert resp.status_code == 400
    assert "internal" in str(resp.data).lower() or "must not" in str(resp.data).lower()


def test_alert_config_webhook_rejects_non_http_scheme(client_a, tenant_a, in_tenant, agent_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.post(
            f"/api/v1/agents/{agent_obj.id}/alerts/",
            {"metric_name": "turn_count", "operator": "gt", "threshold": 5,
             "webhook_url": "ftp://example.com/hook"},
            format="json",
        )
    assert resp.status_code == 400


# ===========================================================================
# views — test run agent_name in serializer output
# ===========================================================================

def test_test_run_list_includes_agent_name(client_a, tenant_a, in_tenant, agent_obj, scenario_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        TestRun.objects.create(agent=agent_obj, scenario=scenario_obj)
        resp = client.get("/api/v1/test-runs/")
    assert resp.status_code == 200
    runs = resp.data if isinstance(resp.data, list) else resp.data.get("results", [])
    assert any(r.get("agent_name") == "Coverage Agent" for r in runs)


# ===========================================================================
# caller — RemoteAudioCaller
# ===========================================================================

def test_remote_caller_reset_is_noop(remote_agent):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller import RemoteAudioCaller
    caller = RemoteAudioCaller(remote_agent)
    caller.reset()  # should not raise


def test_remote_caller_connect_is_noop(remote_agent):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller import RemoteAudioCaller
    caller = RemoteAudioCaller(remote_agent)
    caller._connect()  # should not raise, no HTTP call made


def test_remote_caller_dynamic_variables_sent(remote_agent, tenant_a, in_tenant):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.caller import RemoteAudioCaller

    with in_tenant(tenant_a):
        remote_agent.dynamic_variables = {"company_name": "TestCo"}
        remote_agent.save()

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"transcript": [], "closed_reason": ""}
    mock_resp.raise_for_status = MagicMock()

    caller = RemoteAudioCaller(remote_agent)
    with patch("httpx.post", return_value=mock_resp) as mock_post:
        with in_tenant(tenant_a):
            caller.run_scenario([], "conv", recording_id="rec-x")

    sent_json = mock_post.call_args[1]["json"]
    assert sent_json["dynamic_variables"] == {"company_name": "TestCo"}


# ===========================================================================
# views — call metrics endpoint
# ===========================================================================

def test_call_metrics_endpoint(client_a, tenant_a, in_tenant, call_obj):
    client, _ = client_a
    with in_tenant(tenant_a):
        CallMetric.objects.create(call=call_obj, name="turn_count", value=3.0)
        resp = client.get(f"/api/v1/calls/{call_obj.id}/metrics/")
    assert resp.status_code == 200
    assert any(m["name"] == "turn_count" for m in resp.data)


# ===========================================================================
# views — agents list only shows elevenlabs
# ===========================================================================

def test_agents_list_filters_elevenlabs_only(client_a, tenant_a, in_tenant):
    client, _ = client_a
    with in_tenant(tenant_a):
        Agent.objects.create(name="Builtin", system_prompt="x", target_type=Agent.TargetType.BUILTIN)
        Agent.objects.create(name="Remote", system_prompt="",
                             target_type=Agent.TargetType.ELEVENLABS, el_agent_id="agent_yyy")
    with in_tenant(tenant_a):
        resp = client.get("/api/v1/agents/")
    assert resp.status_code == 200
    names = [a["name"] for a in resp.data]
    assert "Remote" in names
    assert "Builtin" not in names


def test_agents_create_returns_405(client_a, tenant_a, in_tenant):
    client, _ = client_a
    with in_tenant(tenant_a):
        resp = client.post("/api/v1/agents/", {"name": "x", "system_prompt": "y"}, format="json")
    assert resp.status_code == 405
