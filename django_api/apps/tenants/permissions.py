from rest_framework.permissions import BasePermission

from .models import TenantAPIKey


class HasTenantAPIKey(BasePermission):
    def has_permission(self, request, view):
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth.startswith("Api-Key "):
            return False
        raw_key = auth[len("Api-Key "):]
        return TenantAPIKey.authenticate(raw_key) is not None
