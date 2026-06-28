"""factory_boy factories.

Add your own factories below TenantFactory.
"""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from zenlib.reusable_apps.multitenant.models import Tenant


class TenantFactory(DjangoModelFactory):
    class Meta:
        model = Tenant
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Tenant {n}")
    slug = factory.Sequence(lambda n: f"tenant-{n}")
    service_token = factory.Sequence(lambda n: f"svc-token-{n}")
    is_active = True
