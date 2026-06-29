"""Shared pytest fixtures."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from zenlib.reusable_apps.multitenant import context
from zenlib.reusable_apps.multitenant.models import Tenant


@pytest.fixture
def tenant_a(db) -> Tenant:
    return Tenant.objects.create(name="Tenant A", slug="tenant-a", service_token="svc-a")


@pytest.fixture
def tenant_b(db) -> Tenant:
    return Tenant.objects.create(name="Tenant B", slug="tenant-b", service_token="svc-b")


@pytest.fixture
def in_tenant():
    """``with in_tenant(t):`` scopes the block to tenant ``t``."""

    @contextmanager
    def _scope(tenant: Tenant):
        token = context.current_tenant.set(tenant)
        try:
            yield tenant
        finally:
            context.current_tenant.reset(token)

    return _scope


@pytest.fixture
def service_headers():
    """Headers a pipecat → django internal call carries. Caller supplies tenant."""

    def _headers(tenant: Tenant) -> dict:
        return {
            "HTTP_X_SERVICE_TOKEN": settings.SERVICE_TOKEN,
            "HTTP_X_TENANT_ID": str(tenant.id),
        }

    return _headers


@pytest.fixture
def api_key_headers(db, in_tenant):
    """Headers a CLI client carries. Creates and returns Api-Key for a tenant."""
    from zenlib_agentos.zenlib.reusable_apps.voice_qa.models import TenantAPIKey

    def _headers(tenant: Tenant) -> dict:
        with in_tenant(tenant):
            raw_key, _ = TenantAPIKey.generate(tenant)
        return {"HTTP_AUTHORIZATION": f"Api-Key {raw_key}"}

    return _headers


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()
