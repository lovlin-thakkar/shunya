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


def test_agents_crud(client_a, tenant_a, in_tenant):
    client, tenant = client_a
    # Create
    with in_tenant(tenant):
        resp = client.post("/api/v1/agents/", {
            "name": "Smoke Agent",
            "system_prompt": "You are a test agent.",
        }, format="json")
    assert resp.status_code == 201, resp.data
    agent_id = resp.data["id"]

    # List
    with in_tenant(tenant):
        resp = client.get("/api/v1/agents/")
    assert resp.status_code == 200
    assert any(a["id"] == agent_id for a in resp.data["results"])


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
