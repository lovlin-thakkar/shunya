"""Two middlewares — context first, RLS second."""

from __future__ import annotations

from typing import Callable

from django.db import connection
from django.http import HttpRequest, HttpResponse

from . import context
from .models import Tenant


class MultitenantContextMiddleware:
    """Resolve tenant from auth headers; bind to ContextVar for the request."""

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tenant = self._resolve_tenant(request)
        token = context.current_tenant.set(tenant)
        try:
            return self.get_response(request)
        finally:
            context.current_tenant.reset(token)

    def _resolve_tenant(self, request: HttpRequest) -> Tenant | None:
        # Knox token: "Authorization: Token <knox> <tenant_id>"
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Token "):
            parts = auth[6:].split()
            if len(parts) == 2:
                return self._fetch(parts[1])

        # Service token: X-Service-Token + X-Tenant-Id
        service_token = request.headers.get("X-Service-Token")
        tenant_id = request.headers.get("X-Tenant-Id")
        if service_token and tenant_id:
            return self._fetch(tenant_id)

        return None

    @staticmethod
    def _fetch(tenant_id: str | int) -> Tenant | None:
        try:
            return Tenant.objects.get(id=int(tenant_id), is_active=True)
        except (Tenant.DoesNotExist, ValueError, TypeError):
            return None


class MultitenantRLSMiddleware:
    """SET LOCAL app.current_tenant_id on the DB connection per request."""

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tenant = context.current_tenant.get()
        if tenant is not None:
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT set_config('app.current_tenant_id', %s, true)",
                    [str(tenant.id)],
                )
        return self.get_response(request)

