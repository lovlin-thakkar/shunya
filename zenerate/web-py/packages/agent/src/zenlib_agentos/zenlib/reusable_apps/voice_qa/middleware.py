"""TenantAPIKeyMiddleware — resolves tenant from Api-Key header before RLS middleware runs.

Sits between MultitenantContextMiddleware and MultitenantRLSMiddleware in the
middleware stack. If the ContextVar is already set (Knox or service-token path),
this is a no-op.
"""

from __future__ import annotations

from typing import Callable

from django.http import HttpRequest, HttpResponse

from zenlib.reusable_apps.multitenant import context


class TenantAPIKeyMiddleware:
    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if context.current_tenant.get() is None:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Api-Key "):
                raw_key = auth[8:].strip()
                self._resolve(raw_key)
        return self.get_response(request)

    @staticmethod
    def _resolve(raw_key: str) -> None:
        from .models import TenantAPIKey
        tenant = TenantAPIKey.authenticate(raw_key)
        if tenant is not None:
            context.current_tenant.set(tenant)
