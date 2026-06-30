"""Tests for the authenticated, tenant-scoped recording endpoint.

Recordings used to be served by an unauthenticated `GET /recordings/<file>.wav`
view (access control was "the UUID is unguessable"). They are now streamed
through `GET /api/v1/test-runs/<id>/recording/`, which requires auth and is
scoped to the caller's tenant. These tests pin that behaviour.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from zenlib.reusable_apps.multitenant.models import Tenant
from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import (
    Agent,
    Scenario,
    TestRun,
    TenantAPIKey,
)


def _client_for(tenant: Tenant, in_tenant) -> APIClient:
    client = APIClient()
    with in_tenant(tenant):
        _, raw = TenantAPIKey.generate(tenant)
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    return client


def _make_run(tenant: Tenant, in_tenant) -> TestRun:
    with in_tenant(tenant):
        agent = Agent.objects.create(name="Rec Agent", system_prompt="x")
        scenario = Scenario.objects.create(
            name="rec_scenario",
            yaml_content="name: rec_scenario\npersona: x\nsteps: []",
            persona="customer",
        )
        return TestRun.objects.create(
            agent=agent, scenario=scenario, mode=TestRun.Mode.AUDIO
        )


def _write_recording(settings, tmp_path, run: TestRun) -> bytes:
    settings.RECORDINGS_DIR = str(tmp_path)
    data = b"RIFF\x00\x00\x00\x00WAVEfmt fake-wav-bytes"
    (tmp_path / f"{run.id}.wav").write_bytes(data)
    return data


def test_recording_requires_auth(tenant_a, in_tenant):
    run = _make_run(tenant_a, in_tenant)
    resp = APIClient().get(f"/api/v1/test-runs/{run.id}/recording/")
    assert resp.status_code == 401


def test_recording_returns_wav_for_own_tenant(tenant_a, in_tenant, settings, tmp_path):
    run = _make_run(tenant_a, in_tenant)
    data = _write_recording(settings, tmp_path, run)

    client = _client_for(tenant_a, in_tenant)
    resp = client.get(f"/api/v1/test-runs/{run.id}/recording/")

    assert resp.status_code == 200
    assert resp["Content-Type"] == "audio/wav"
    assert b"".join(resp.streaming_content) == data


def test_recording_cross_tenant_is_denied(tenant_a, tenant_b, in_tenant, settings, tmp_path):
    """Tenant B must not be able to read Tenant A's recording even though the
    file exists on disk — get_object() filters by tenant, so it 404s."""
    run = _make_run(tenant_a, in_tenant)
    _write_recording(settings, tmp_path, run)

    client_b = _client_for(tenant_b, in_tenant)
    resp = client_b.get(f"/api/v1/test-runs/{run.id}/recording/")

    assert resp.status_code == 404


def test_recording_missing_file_returns_404(tenant_a, in_tenant, settings, tmp_path):
    run = _make_run(tenant_a, in_tenant)
    settings.RECORDINGS_DIR = str(tmp_path)  # dir exists, file does not

    client = _client_for(tenant_a, in_tenant)
    resp = client.get(f"/api/v1/test-runs/{run.id}/recording/")

    assert resp.status_code == 404
