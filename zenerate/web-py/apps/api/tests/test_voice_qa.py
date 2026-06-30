"""Smoke tests for the voice_qa reusable app."""

from __future__ import annotations

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from zenlib.reusable_apps.multitenant import context
from zenlib.reusable_apps.multitenant.models import Tenant
from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import (
    Agent, Scenario, TenantAPIKey, TestRun,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

def test_agent_inherits_tenant(tenant_a, in_tenant):
    """Agent.save() populates tenant from ContextVar via UUIDTenantModel.save()."""
    with in_tenant(tenant_a):
        agent = Agent.objects.create(
            name="Test Agent",
            system_prompt="You are helpful.",
        )
    assert agent.tenant_id == tenant_a.id


def test_scenario_unique_per_tenant(tenant_a, tenant_b, in_tenant):
    """Two tenants can have scenarios with the same name (unique_together is per tenant)."""
    with in_tenant(tenant_a):
        s_a = Scenario.objects.create(
            name="happy_path",
            yaml_content="name: happy_path\npersona: x\nsteps: []",
            persona="customer",
        )
    with in_tenant(tenant_b):
        s_b = Scenario.objects.create(
            name="happy_path",
            yaml_content="name: happy_path\npersona: y\nsteps: []",
            persona="customer",
        )
    assert s_a.id != s_b.id


def test_rls_isolation(tenant_a, tenant_b, in_tenant):
    """Tenant A's agents are not visible to Tenant B's queryset."""
    with in_tenant(tenant_a):
        Agent.objects.create(name="Agent A", system_prompt="a")
    with in_tenant(tenant_b):
        assert Agent.objects.filter(name="Agent A").count() == 0


# ---------------------------------------------------------------------------
# TenantAPIKey tests
# ---------------------------------------------------------------------------

def test_api_key_generate_and_authenticate(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        key_obj, raw = TenantAPIKey.generate(tenant_a)
    resolved = TenantAPIKey.authenticate(raw)
    assert resolved is not None
    assert resolved.id == tenant_a.id


def test_api_key_bad_key_returns_none(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        TenantAPIKey.generate(tenant_a)
    assert TenantAPIKey.authenticate("wrong-key") is None


# ---------------------------------------------------------------------------
# API endpoint smoke tests (via DRF test client)
# ---------------------------------------------------------------------------

@pytest.fixture
def client_a(tenant_a, in_tenant) -> tuple[APIClient, Tenant]:
    client = APIClient()
    with in_tenant(tenant_a):
        _, raw = TenantAPIKey.generate(tenant_a)
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    return client, tenant_a


def test_agents_list_requires_auth():
    client = APIClient()
    resp = client.get("/api/v1/agents/")
    assert resp.status_code == 401


def test_agents_not_creatable_via_api(client_a, tenant_a, in_tenant):
    """Agents are synced from ElevenLabs, not authored in Shunya — create is gone."""
    client, tenant = client_a
    with in_tenant(tenant):
        resp = client.post("/api/v1/agents/", {
            "name": "Smoke Agent",
            "system_prompt": "You are a test agent.",
        }, format="json")
    assert resp.status_code == 405, resp.data


def test_agents_list_shows_only_elevenlabs(client_a, tenant_a, in_tenant):
    """The list surfaces only remote ElevenLabs agents; built-ins are hidden."""
    client, tenant = client_a
    with in_tenant(tenant):
        Agent.objects.create(name="Builtin One", system_prompt="x")
        el = Agent.objects.create(
            name="Remote One", system_prompt="",
            target_type=Agent.TargetType.ELEVENLABS, el_agent_id="agent_xyz",
        )
        resp = client.get("/api/v1/agents/")
    assert resp.status_code == 200
    rows = resp.data if isinstance(resp.data, list) else resp.data["results"]
    ids = {a["id"] for a in rows}
    assert str(el.id) in ids
    assert all(a["target_type"] == "elevenlabs" for a in rows)


# ---------------------------------------------------------------------------
# ElevenLabs integration + sync
# ---------------------------------------------------------------------------

def test_elevenlabs_integration_get_unconfigured(client_a, tenant_a, in_tenant):
    client, tenant = client_a
    with in_tenant(tenant):
        resp = client.get("/api/v1/integrations/elevenlabs/")
    assert resp.status_code == 200
    assert resp.data == {"configured": False, "key_hint": ""}


def test_elevenlabs_integration_put_validates_and_saves(client_a, tenant_a, in_tenant):
    from unittest.mock import MagicMock, patch
    client, tenant = client_a
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"agents": []}
    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.httpx.get", return_value=ok):
        with in_tenant(tenant):
            resp = client.put("/api/v1/integrations/elevenlabs/",
                              {"api_key": "sk_0123456789abcdef"}, format="json")
            assert resp.status_code == 200
            assert resp.data["configured"] is True
            assert resp.data["key_hint"] == "sk_0…cdef"
            # GET now reports configured, never the raw key
            get = client.get("/api/v1/integrations/elevenlabs/")
    assert get.data["configured"] is True
    assert "api_key" not in get.data


def test_elevenlabs_integration_put_rejects_bad_key(client_a, tenant_a, in_tenant):
    from unittest.mock import MagicMock, patch
    client, tenant = client_a
    bad = MagicMock(status_code=401)
    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.httpx.get", return_value=bad):
        with in_tenant(tenant):
            resp = client.put("/api/v1/integrations/elevenlabs/",
                              {"api_key": "sk_bad"}, format="json")
    assert resp.status_code == 400
    assert "convai_read" in resp.data["error"]


def test_sync_elevenlabs_requires_key(client_a, tenant_a, in_tenant):
    client, tenant = client_a
    with in_tenant(tenant):
        resp = client.post("/api/v1/agents/sync-elevenlabs/")
    assert resp.status_code == 400


def test_sync_elevenlabs_upserts_agents(client_a, tenant_a, in_tenant):
    from unittest.mock import MagicMock, patch
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import ElevenLabsCredential
    client, tenant = client_a
    with in_tenant(tenant):
        ElevenLabsCredential.objects.create(tenant=tenant, api_key="sk_x", key_hint="sk_x…")
    listed = MagicMock(status_code=200)
    listed.raise_for_status = MagicMock()
    listed.json.return_value = {"agents": [
        {"agent_id": "agent_aaa", "name": "Support Bot"},
        {"agent_id": "agent_bbb", "name": "Sales Bot"},
    ]}
    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.httpx.get", return_value=listed):
        with in_tenant(tenant):
            resp = client.post("/api/v1/agents/sync-elevenlabs/")
    assert resp.status_code == 200
    rows = resp.data if isinstance(resp.data, list) else resp.data["results"]
    names = {a["name"] for a in rows}
    assert {"Support Bot", "Sales Bot"} <= names
    assert all(a["target_type"] == "elevenlabs" for a in rows)


def test_scenarios_list(client_a, tenant_a, in_tenant):
    client, tenant = client_a
    with in_tenant(tenant):
        Scenario.objects.create(
            name="test_scenario",
            yaml_content="name: test_scenario\npersona: x\nsteps: []",
            persona="x",
        )
        resp = client.get("/api/v1/scenarios/")
    assert resp.status_code == 200
    names = [s["name"] for s in resp.data["results"]]
    assert "test_scenario" in names


def test_service_token_auth(tenant_a, in_tenant):
    """Internal endpoints require X-Service-Token + X-Tenant-Id."""
    client = APIClient()
    resp = client.post("/internal/calls/start/", {
        "agent_id": "00000000-0000-0000-0000-000000000000",
        "source": "human",
        "daily_room_url": "https://test.daily.co/room",
        "daily_room_name": "room",
    }, format="json")
    # No auth → 401 or 403
    assert resp.status_code in (401, 403)


def test_run_evals_parallel(client_a, tenant_a, in_tenant):
    """run-evals creates N TestRun objects in one request (parallel sub-agent dispatch)."""
    from unittest.mock import MagicMock, patch

    client, tenant = client_a
    with in_tenant(tenant):
        agent = Agent.objects.create(name="Eval Agent", system_prompt="You are helpful.")
        Scenario.objects.create(
            name="scenario_a", yaml_content="name: scenario_a\npersona: x\nsteps: []", persona="x",
        )
        Scenario.objects.create(
            name="scenario_b", yaml_content="name: scenario_b\npersona: y\nsteps: []", persona="y",
        )

    # Mock Celery group dispatch — we verify endpoint logic, not worker execution
    fake_result = MagicMock()
    fake_result.id = "fake-group-id"
    fake_result.results = [MagicMock(id=f"task-{i}") for i in range(2)]

    with patch("zenlib_agentos.zenlib.reusable_apps.voice_qa.views.celery_group") as mock_group:
        mock_group.return_value.apply_async.return_value = fake_result
        with in_tenant(tenant):
            resp = client.post(
                f"/api/v1/agents/{agent.id}/run-evals/",
                {"scenario_names": ["scenario_a", "scenario_b"], "mode": "text"},
                format="json",
            )

    assert resp.status_code == 201, resp.data
    assert resp.data["parallelism"] == 2
    assert len(resp.data["runs"]) == 2
    assert resp.data["group_id"] == "fake-group-id"
    mock_group.assert_called_once()


def test_service_token_auth_valid(tenant_a, in_tenant):
    """Valid service token + tenant resolves correctly."""
    with in_tenant(tenant_a):
        agent = Agent.objects.create(name="Svc Agent", system_prompt="x")

    client = APIClient()
    resp = client.post(
        "/internal/calls/start/",
        {
            "agent_id": str(agent.id),
            "source": "human",
            "daily_room_url": "https://test.daily.co/room",
            "daily_room_name": "room",
        },
        format="json",
        HTTP_X_SERVICE_TOKEN=settings.SERVICE_TOKEN,
        HTTP_X_TENANT_ID=str(tenant_a.id),
    )
    assert resp.status_code == 201, resp.data
    assert "call_id" in resp.data
