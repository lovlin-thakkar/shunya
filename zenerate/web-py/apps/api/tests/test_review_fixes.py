"""Regression tests for the code-review security fixes.

Covers:
  * SSRF guard now rejects IPv6 / IPv4-mapped internal addresses (#3)
  * Agent mutation lockdown: delete is blocked, sync-managed fields are read-only (#22)
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from zenlib.reusable_apps.multitenant.models import Tenant
from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import Agent, TenantAPIKey
from zenlib_agentos.zenlib.reusable_apps.voice_qa.services.ssrf import is_safe_webhook_url


def _client(tenant: Tenant, in_tenant) -> APIClient:
    client = APIClient()
    with in_tenant(tenant):
        _, raw = TenantAPIKey.generate(tenant)
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    return client


# --- #3 SSRF: IPv6 / mapped-address coverage --------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "http://[::1]/hook",                 # IPv6 loopback literal
        "http://[::ffff:127.0.0.1]/hook",    # IPv4-mapped IPv6 loopback
        "http://[fe80::1]/hook",             # IPv6 link-local
        "http://[fc00::1]/hook",             # IPv6 unique-local (private)
        "http://127.0.0.1/hook",             # IPv4 loopback
        "http://10.1.2.3/hook",              # IPv4 private
    ],
)
def test_ssrf_blocks_internal_addresses(url):
    assert is_safe_webhook_url(url) is False


@pytest.mark.parametrize("url", ["https://93.184.216.34/hook", "https://1.1.1.1/hook"])
def test_ssrf_allows_public_ip_literals(url):
    assert is_safe_webhook_url(url) is True


# --- #22 Agent mutation lockdown --------------------------------------------

def test_agent_delete_is_blocked(tenant_a, in_tenant):
    client = _client(tenant_a, in_tenant)
    with in_tenant(tenant_a):
        agent = Agent.objects.create(
            name="Synced", system_prompt="",
            target_type=Agent.TargetType.ELEVENLABS, el_agent_id="agent_1",
        )
    resp = client.delete(f"/api/v1/agents/{agent.id}/")
    assert resp.status_code == 405
    with in_tenant(tenant_a):
        assert Agent.objects.filter(id=agent.id).exists()


def test_agent_patch_ignores_sync_managed_fields_but_allows_dynamic_vars(tenant_a, in_tenant):
    client = _client(tenant_a, in_tenant)
    with in_tenant(tenant_a):
        agent = Agent.objects.create(
            name="Original Name", system_prompt="orig",
            target_type=Agent.TargetType.ELEVENLABS, el_agent_id="agent_2",
        )
    resp = client.patch(
        f"/api/v1/agents/{agent.id}/",
        {"name": "Hacked Name", "dynamic_variables": {"company": "Acme"}},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    with in_tenant(tenant_a):
        agent.refresh_from_db()
    # Sync-managed field is read-only → unchanged.
    assert agent.name == "Original Name"
    # User-owned field is writable.
    assert agent.dynamic_variables == {"company": "Acme"}
