"""Tenant root + base classes every tenant-scoped model inherits.

Public API:

  * ``Tenant``                   — the data-isolation boundary.
  * ``LastActivityTrackerMixin`` — abstract; ``created_at``, ``updated_at``.
  * ``TenantAwareMixin``         — abstract; adds tenant FK + auto-populate
                                   + RLS policy.
  * ``ActivityTenantBaseModel``  — abstract; combines the two + soft-delete.
                                   **Every tenant-scoped model in this repo
                                   inherits this.**
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_migrate
from django.dispatch import receiver

from zenlib.django_utils.db.pg_rls import (
    build_cross_tenant_policy,
    build_tenant_user_policy,
    enable_rls_sql,
)

from . import context
from .managers import AutoFilteringManager, SoftDeleteAutoFilter, TenantAutoFilter
from .settings import default_rls_options


class LastActivityTrackerMixin(models.Model):
    """Tracks created/updated timestamps. Abstract."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Tenant(LastActivityTrackerMixin, models.Model):
    """Data-isolation boundary. Not tenant-scoped itself."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=64, unique=True)
    service_token = models.CharField(max_length=128, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "multitenant_tenant"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class TenantAwareMixin(models.Model):
    """Adds ``tenant`` FK + auto-populate + RLS policy. Abstract."""

    objects = AutoFilteringManager.factory(TenantAutoFilter())()

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s",
    )

    # When set to a related-field path (e.g. "logical_thread"), ``save()``
    # will infer ``tenant`` from that related object instead of from
    # ``context.current_tenant``.
    __infer_tenant_from__: str | None = None

    class Meta:
        abstract = True
        indexes = [models.Index(fields=["tenant"])]

    class RowLevelSecurityMeta:
        row_level_security = default_rls_options()
        policies = (build_tenant_user_policy(), build_cross_tenant_policy())

    def save(self, *args, **kwargs):
        self._populate_tenant_if_needed()
        self._raise_on_tenant_missing()
        return super().save(*args, **kwargs)

    def _populate_tenant_if_needed(self) -> None:
        if self.pk or self.tenant_id:
            return
        inferred = self._infer_tenant_from_related()
        if inferred is not None:
            self.tenant = inferred
            return
        ctx_tenant = context.current_tenant.get()
        if ctx_tenant is not None:
            self.tenant = ctx_tenant

    def _raise_on_tenant_missing(self) -> None:
        if not self.tenant_id:
            raise ValidationError(
                {
                    "tenant": (
                        "Tenant is required. Set ``context.current_tenant`` "
                        "or pass ``tenant=`` explicitly."
                    )
                },
                code="tenant_missing",
            )

    def _infer_tenant_from_related(self) -> Tenant | None:
        path = type(self).__infer_tenant_from__
        if not path:
            return None
        try:
            related = getattr(self, path, None)
        except Exception:
            return None
        return getattr(related, "tenant", None)


class ActivityTenantBaseModel(LastActivityTrackerMixin, TenantAwareMixin):
    """Base every tenant-scoped model in this repo inherits.

    Adds soft-delete on top of ``TenantAwareMixin``.
    """

    objects = AutoFilteringManager.factory(
        SoftDeleteAutoFilter(), TenantAutoFilter()
    )()

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantAwareMixin.Meta):
        abstract = True

    def delete(self, using=None, keep_parents=False):
        """Soft-delete by default."""
        from django.utils import timezone

        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)


# --- Auto-apply RLS policies after every migration ----------------------

@receiver(post_migrate)
def _apply_rls_policies(sender, app_config, **kwargs):
    """Walk all concrete models that declare ``RowLevelSecurityMeta`` and
    emit policy SQL. Idempotent (DROP IF EXISTS then CREATE).
    """
    from django.apps import apps
    from django.db import connection

    for model in apps.get_models():
        rls_meta = getattr(model, "RowLevelSecurityMeta", None)
        if rls_meta is None:
            continue
        if not getattr(rls_meta, "row_level_security", {}).get("enabled"):
            continue
        policies = getattr(rls_meta, "policies", ())
        if not policies:
            continue
        sql = enable_rls_sql(model._meta.db_table, policies)
        with connection.cursor() as cur:
            cur.execute(sql)
