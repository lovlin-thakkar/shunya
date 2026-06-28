"""Reference tests for multitenant plumbing.

Model your ``tests/email_pipeline/test_rls.py`` after these once you've
added ``LogicalThread`` and friends.
"""

from __future__ import annotations

import pytest
from django.db import connection

from zenlib.reusable_apps.multitenant import context
from zenlib.reusable_apps.multitenant.models import Tenant

pytestmark = pytest.mark.django_db


def test_tenant_round_trip(tenant_a):
    fetched = Tenant.objects.get(slug="tenant-a")
    assert fetched.id == tenant_a.id
    assert fetched.service_token == "svc-a"


def test_context_var_holds_tenant(tenant_a, tenant_b, in_tenant):
    with in_tenant(tenant_a):
        assert context.current_tenant.get() == tenant_a
    with in_tenant(tenant_b):
        assert context.current_tenant.get() == tenant_b


def test_session_setting_round_trip(tenant_a):
    """Pattern: the RLS middleware calls set_config(...) per request.
    Reproduces what the middleware does and confirms the GUC sticks.
    """
    with connection.cursor() as cur:
        cur.execute(
            "SELECT set_config('app.current_tenant_id', %s, true)",
            [str(tenant_a.id)],
        )
        cur.execute("SELECT current_setting('app.current_tenant_id', true)")
        assert cur.fetchone()[0] == str(tenant_a.id)
