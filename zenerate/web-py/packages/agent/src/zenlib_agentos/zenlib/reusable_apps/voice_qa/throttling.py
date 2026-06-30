"""Throttling for voice_qa.

DRF's stock ``UserRateThrottle`` keys the rate bucket on ``request.user.pk``.
Our non-human callers (API keys, pipecat service token) authenticate as a
``ServiceAccount`` which has no ``pk`` — so the stock throttle raised
``AttributeError: 'ServiceAccount' object has no attribute 'pk'`` and 500'd
*every* authenticated Api-Key / service-token request. This subclass keys those
callers on their tenant id instead, and leaves human (Knox) users on their pk.
"""

from __future__ import annotations

from rest_framework.throttling import UserRateThrottle

from .authentication import ServiceAccount


class ScopedIdentityUserRateThrottle(UserRateThrottle):
    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if isinstance(user, ServiceAccount):
            # Stable per-tenant bucket for API-key / service-token callers.
            ident = f"tenant:{user.tenant.id}"
        elif user and user.is_authenticated:
            ident = user.pk
        else:
            # Unauthenticated — fall back to the client IP.
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
