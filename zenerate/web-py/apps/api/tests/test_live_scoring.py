"""Tests for the during-call live-scoring internal endpoint and the tenant-aware throttle."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import Agent, Scenario, TestRun

pytestmark = pytest.mark.django_db


def _svc_client(tenant):
    client = APIClient()
    client.credentials(
        HTTP_X_SERVICE_TOKEN=settings.SERVICE_TOKEN,
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    return client


@pytest.fixture
def run_obj(tenant_a, in_tenant):
    with in_tenant(tenant_a):
        agent = Agent.objects.create(
            name="Remote", system_prompt="",
            target_type=Agent.TargetType.ELEVENLABS, el_agent_id="agent_x",
        )
        scenario = Scenario.objects.create(name="s", yaml_content="x", persona="x")
        return TestRun.objects.create(agent=agent, scenario=scenario, mode=TestRun.Mode.AUDIO)


# --------------------------------------------------------------------------- LiveScoresView

def test_live_scores_stored_on_run(tenant_a, in_tenant, run_obj):
    client = _svc_client(tenant_a)
    payload = {"turn": 3, "scores": [{"field": "safety", "score": 1.0, "passed": True, "reasoning": "ok"}]}
    resp = client.post(f"/internal/test-runs/{run_obj.id}/live-scores/", payload, format="json")
    assert resp.status_code == 200
    with in_tenant(tenant_a):
        run_obj.refresh_from_db()
    assert run_obj.live_scores["turn"] == 3
    assert run_obj.live_scores["scores"][0]["field"] == "safety"


def test_live_scores_unknown_run_404(tenant_a):
    client = _svc_client(tenant_a)
    resp = client.post(f"/internal/test-runs/{uuid.uuid4()}/live-scores/", {"turn": 1, "scores": []}, format="json")
    assert resp.status_code == 404


def test_live_scores_cross_tenant_isolated(tenant_a, tenant_b, run_obj):
    """A run from another tenant is invisible under RLS — 404, never cross-written."""
    client = APIClient()
    client.credentials(HTTP_X_SERVICE_TOKEN=settings.SERVICE_TOKEN, HTTP_X_TENANT_ID=str(tenant_b.id))
    resp = client.post(f"/internal/test-runs/{run_obj.id}/live-scores/", {"turn": 1, "scores": []}, format="json")
    assert resp.status_code == 404


def test_live_scores_requires_service_token(run_obj):
    resp = APIClient().post(f"/internal/test-runs/{run_obj.id}/live-scores/", {"turn": 1, "scores": []}, format="json")
    assert resp.status_code in (401, 403)


def test_live_scores_merge_by_field(tenant_a, in_tenant, run_obj):
    """Two POSTs for the same field must overwrite, not append."""
    client = _svc_client(tenant_a)
    first = {"turn": 1, "scores": [{"field": "safety", "score": 0.5, "passed": False, "reasoning": "meh"}]}
    client.post(f"/internal/test-runs/{run_obj.id}/live-scores/", first, format="json")

    second = {"turn": 2, "scores": [{"field": "safety", "score": 0.9, "passed": True, "reasoning": "ok"}]}
    client.post(f"/internal/test-runs/{run_obj.id}/live-scores/", second, format="json")

    with in_tenant(tenant_a):
        run_obj.refresh_from_db()
    scores = run_obj.live_scores["scores"]
    safety_scores = [s for s in scores if s["field"] == "safety"]
    assert len(safety_scores) == 1, "field should be merged, not appended"
    assert safety_scores[0]["score"] == 0.9


def test_live_scores_multiple_fields_merged(tenant_a, in_tenant, run_obj):
    """First POST writes safety; second POST adds goal_completion — both survive."""
    client = _svc_client(tenant_a)
    client.post(f"/internal/test-runs/{run_obj.id}/live-scores/",
                {"turn": 1, "scores": [{"field": "safety", "score": 0.8, "passed": True, "reasoning": "good"}]},
                format="json")
    client.post(f"/internal/test-runs/{run_obj.id}/live-scores/",
                {"turn": 1, "scores": [{"field": "goal_completion", "score": 0.7, "passed": True, "reasoning": "ok"}]},
                format="json")

    with in_tenant(tenant_a):
        run_obj.refresh_from_db()
    fields = {s["field"] for s in run_obj.live_scores["scores"]}
    assert fields == {"safety", "goal_completion"}


# --------------------------------------------------------------------------- ScopedIdentityUserRateThrottle

def _throttle():
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.throttling import ScopedIdentityUserRateThrottle
    t = ScopedIdentityUserRateThrottle()
    t.scope = "user"
    t.rate = "300/min"
    return t


def test_throttle_keys_service_account_on_tenant(tenant_a):
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.authentication import ServiceAccount
    t = _throttle()
    req = SimpleNamespace(user=ServiceAccount(name="api-key-client", tenant=tenant_a), META={})
    key = t.get_cache_key(req, view=None)
    assert f"tenant:{tenant_a.id}" in key


def test_throttle_keys_human_user_on_pk():
    t = _throttle()
    req = SimpleNamespace(user=SimpleNamespace(is_authenticated=True, pk=42), META={})
    key = t.get_cache_key(req, view=None)
    assert key.endswith("42")


def test_throttle_anonymous_falls_back_to_ip():
    from django.contrib.auth.models import AnonymousUser
    t = _throttle()
    req = SimpleNamespace(user=AnonymousUser(), META={"REMOTE_ADDR": "203.0.113.7"})
    key = t.get_cache_key(req, view=None)
    assert "203.0.113.7" in key
