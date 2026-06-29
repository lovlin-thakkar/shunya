"""Cross-tenant RLS tests for voice_qa models.

Required by the baseline README: "Cross-tenant test in
apps/api/tests/email_pipeline/test_rls.py — model after test_multitenant.py".

Note: our app is voice_qa (not email_pipeline) because the take-home task is
a voice QA platform. These tests verify that Postgres RLS correctly prevents
cross-tenant data access across all core voice_qa models.
"""
from __future__ import annotations

import pytest

from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import (
    Agent,
    Call,
    Scenario,
    TestRun,
    TenantAPIKey,
)

pytestmark = pytest.mark.django_db


def _make_agent(name: str):
    return Agent.objects.create(name=name, system_prompt="x")


def _make_scenario(name: str):
    return Scenario.objects.create(
        name=name,
        yaml_content=f"name: {name}\npersona: x\nsteps: []",
        persona="x",
    )


# ---------------------------------------------------------------------------
# Agent isolation
# ---------------------------------------------------------------------------

def test_agent_not_visible_cross_tenant(tenant_a, tenant_b, in_tenant):
    with in_tenant(tenant_a):
        _make_agent("agent-a")
    with in_tenant(tenant_b):
        assert Agent.objects.filter(name="agent-a").count() == 0


def test_agent_visible_own_tenant(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        _make_agent("agent-own")
        assert Agent.objects.filter(name="agent-own").count() == 1


def test_agents_do_not_bleed_between_tenants(tenant_a, tenant_b, in_tenant):
    with in_tenant(tenant_a):
        _make_agent("shared-name")
    with in_tenant(tenant_b):
        _make_agent("shared-name")
    with in_tenant(tenant_a):
        assert Agent.objects.filter(name="shared-name").count() == 1
    with in_tenant(tenant_b):
        assert Agent.objects.filter(name="shared-name").count() == 1


# ---------------------------------------------------------------------------
# Scenario isolation
# ---------------------------------------------------------------------------

def test_scenario_not_visible_cross_tenant(tenant_a, tenant_b, in_tenant):
    with in_tenant(tenant_a):
        _make_scenario("scen-a")
    with in_tenant(tenant_b):
        assert Scenario.objects.filter(name="scen-a").count() == 0


def test_scenario_visible_own_tenant(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        _make_scenario("scen-own")
        assert Scenario.objects.filter(name="scen-own").count() == 1


# ---------------------------------------------------------------------------
# TenantAPIKey isolation
# ---------------------------------------------------------------------------

def test_api_key_not_visible_cross_tenant(tenant_a, tenant_b, in_tenant):
    with in_tenant(tenant_a):
        TenantAPIKey.generate(tenant_a)
    with in_tenant(tenant_b):
        assert TenantAPIKey.objects.count() == 0


def test_api_key_authenticate_wrong_tenant_key(tenant_a, tenant_b, in_tenant):
    with in_tenant(tenant_a):
        _, raw_a = TenantAPIKey.generate(tenant_a)
    with in_tenant(tenant_b):
        TenantAPIKey.generate(tenant_b)
    # Key from tenant_a must resolve to tenant_a, not tenant_b
    resolved = TenantAPIKey.authenticate(raw_a)
    assert resolved is not None
    assert resolved.id == tenant_a.id


# ---------------------------------------------------------------------------
# TestRun isolation
# ---------------------------------------------------------------------------

def test_test_run_not_visible_cross_tenant(tenant_a, tenant_b, in_tenant):
    with in_tenant(tenant_a):
        agent = _make_agent("tr-agent")
        scenario = _make_scenario("tr-scenario")
        TestRun.objects.create(agent=agent, scenario=scenario)
    with in_tenant(tenant_b):
        assert TestRun.objects.count() == 0


# ---------------------------------------------------------------------------
# Tenant FK is auto-populated
# ---------------------------------------------------------------------------

def test_tenant_fk_auto_populated(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        agent = _make_agent("fk-test")
    assert agent.tenant_id == tenant_a.id


def test_tenant_fk_correct_per_tenant(tenant_a, tenant_b, in_tenant):
    with in_tenant(tenant_a):
        a = _make_agent("fk-a")
    with in_tenant(tenant_b):
        b = _make_agent("fk-b")
    assert a.tenant_id == tenant_a.id
    assert b.tenant_id == tenant_b.id
    assert a.tenant_id != b.tenant_id
