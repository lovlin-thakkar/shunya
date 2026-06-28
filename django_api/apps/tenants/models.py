import hashlib
import secrets

from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class Tenant(TenantMixin):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    auto_create_schema = True

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    pass


class TenantAPIKey(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_keys")
    key_hash = models.CharField(max_length=64, unique=True)
    key_prefix = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "tenants"

    @classmethod
    def generate(cls, tenant):
        raw = secrets.token_hex(32)
        prefix = raw[:8]
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        obj = cls.objects.create(tenant=tenant, key_hash=key_hash, key_prefix=prefix)
        return obj, raw

    @classmethod
    def authenticate(cls, raw_key):
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        try:
            return cls.objects.select_related("tenant").get(key_hash=key_hash)
        except cls.DoesNotExist:
            return None

    def __str__(self):
        return f"{self.key_prefix}... ({self.tenant.name})"
