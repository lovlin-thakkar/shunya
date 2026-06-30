"""Authentication classes for voice_qa.

Two auth paths:
  TenantAPIKeyAuthentication — CLI / external callers using Api-Key header.
  ServiceTokenAuthentication — pipecat → django internal calls (global secret).
"""

from __future__ import annotations

import hmac

from django.conf import settings
from rest_framework import authentication, exceptions, permissions

from zenlib.reusable_apps.multitenant import context
from zenlib.reusable_apps.multitenant.models import Tenant


class ServiceAccount:
    """Stand-in 'user' for non-human callers (API keys, service tokens)."""

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


class TenantAPIKeyAuthentication(authentication.BaseAuthentication):
    """DRF authenticator for hashed per-tenant API keys (Authorization: Api-Key <raw>)."""

    def authenticate(self, request):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Api-Key "):
            return None

        raw_key = auth[8:].strip()
        from .models import TenantAPIKey
        tenant = TenantAPIKey.authenticate(raw_key)
        if tenant is None:
            raise exceptions.AuthenticationFailed("Invalid API key.")

        context.current_tenant.set(tenant)
        return (ServiceAccount(name="api-key-client", tenant=tenant), None)

    def authenticate_header(self, request):
        return "Api-Key"


class ServiceTokenAuthentication(authentication.BaseAuthentication):
    """DRF authenticator for pipecat → django service calls (X-Service-Token header)."""

    def authenticate(self, request):
        token = request.headers.get("X-Service-Token")
        tenant_id = request.headers.get("X-Tenant-Id")
        if not token or not tenant_id:
            return None

        # TODO(security): this is a single global SERVICE_TOKEN and the caller
        # picks the tenant via the X-Tenant-Id header. If the token leaks, it
        # grants access to ANY tenant (scoped only by a client-supplied header).
        # Internal views re-check resource.tenant_id vs the header as a backstop,
        # but the real fix is per-service tokens or signing the tenant id into the
        # token. (Note: Tenant.service_token was unused dead code and was removed.)
        if not hmac.compare_digest(token, settings.SERVICE_TOKEN):
            raise exceptions.AuthenticationFailed("Invalid service token.")

        try:
            tenant = Tenant.objects.get(id=int(tenant_id), is_active=True)
        except (Tenant.DoesNotExist, ValueError, TypeError) as exc:
            raise exceptions.AuthenticationFailed("Unknown tenant.") from exc

        context.current_tenant.set(tenant)
        return (ServiceAccount(name="pipecat", tenant=tenant), None)

    def authenticate_header(self, request):
        return "ServiceToken"


class IsServiceAccount(permissions.BasePermission):
    """Permission: caller must be a ServiceAccount (API key or service token)."""

    def has_permission(self, request, view):
        return isinstance(request.user, ServiceAccount)
