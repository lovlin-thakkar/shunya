"""
Pytest configuration for django-tenants.

All @pytest.mark.django_db tests that touch TENANT_APPS (agents, testing,
monitoring) must run inside a tenant schema. This conftest creates a
disposable tenant once per session and makes it the active schema.
"""
import pytest
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Session-scoped: create the test tenant schema once, reuse across tests."""
    with django_db_blocker.unblock():
        from apps.tenants.models import Tenant, Domain
        if not Tenant.objects.filter(schema_name="test").exists():
            t = Tenant(schema_name="test", name="Test Org")
            t.save()  # triggers CREATE SCHEMA test + migrate
            Domain.objects.create(domain="test.localhost", tenant=t, is_primary=True)


@pytest.fixture(autouse=True)
def use_test_tenant(db):
    """
    Auto-used: push the 'test' schema for every test that hits the DB.
    This ensures TENANT_APPS tables (agents_agent etc.) exist.
    """
    with schema_context("test"):
        yield


@pytest.fixture
def tenant_client():
    """APIClient pre-configured with tenant Host header and auth bypassed."""
    from rest_framework.test import APIClient
    client = APIClient()
    client.defaults["HTTP_HOST"] = "test.localhost"
    return client
