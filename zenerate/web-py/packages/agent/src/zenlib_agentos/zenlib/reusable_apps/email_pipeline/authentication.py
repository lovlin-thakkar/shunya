"""Service-to-service authentication for ``email-py`` → ``web-py``.

``email-py`` sends two headers on every request:

  * ``X-Service-Token``  — shared secret (matches ``settings.SERVICE_TOKEN``)
  * ``X-Tenant-Id``      — tenant id the call should be scoped to

We validate both, set ``context.current_tenant`` so RLS works, and
set ``request.user`` to a ``ServiceAccount`` instance.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework import authentication, exceptions, permissions

from zenlib.reusable_apps.multitenant import context
from zenlib.reusable_apps.multitenant.models import Tenant


class ServiceAccount:
    """Stand-in 'user' for service-to-service calls."""

    is_authenticated = True
    is_anonymous = False
    is_active = True
    is_staff = False
    is_superuser = False

    def __init__(self, name: str, tenant: Tenant):
        self.username = f"service:{name}"
        self.name = name
        self.tenant = tenant

    def __str__(self) -> str:
        return self.username


class ServiceTokenAuthentication(authentication.BaseAuthentication):
    """DRF authentication class for service tokens."""

    def authenticate(self, request):
        token = request.headers.get("X-Service-Token")
        tenant_id = request.headers.get("X-Tenant-Id")
        if not token or not tenant_id:
            return None  # let other auth classes (Knox) try

        if token != settings.SERVICE_TOKEN:
            raise exceptions.AuthenticationFailed("invalid service token")

        try:
            tenant = Tenant.objects.get(id=int(tenant_id), is_active=True)
        except (Tenant.DoesNotExist, ValueError, TypeError) as exc:
            raise exceptions.AuthenticationFailed("unknown tenant") from exc

        context.current_tenant.set(tenant)
        return (ServiceAccount(name="email-py", tenant=tenant), None)

    def authenticate_header(self, request):
        return "ServiceToken"


class IsServiceAccount(permissions.BasePermission):
    """Permission: caller must be authenticated as a service account."""

    def has_permission(self, request, view):
        return isinstance(request.user, ServiceAccount)
