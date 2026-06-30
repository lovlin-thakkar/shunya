"""Shared pytest fixtures."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from zenlib.reusable_apps.multitenant import context
from zenlib.reusable_apps.multitenant.models import Tenant


@pytest.fixture(autouse=True)
def _isolate_tenant_context():
    """Prevent tenant-context bleed between tests. Celery tasks (and any code that
    runs run_scenario_task.apply()) call context.current_tenant.set() without
    resetting — harmless in a worker, but it leaks across tests and breaks RLS
    scoping for whatever runs next. Clear it after every test."""
    yield
    context.current_tenant.set(None)


@pytest.fixture
def tenant_a(db) -> Tenant:
    return Tenant.objects.create(name="Tenant A", slug="tenant-a")


@pytest.fixture
def tenant_b(db) -> Tenant:
    return Tenant.objects.create(name="Tenant B", slug="tenant-b")


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
            _, raw_key = TenantAPIKey.generate(tenant)  # generate() returns (obj, raw)
        return {"HTTP_AUTHORIZATION": f"Api-Key {raw_key}"}

    return _headers


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()
