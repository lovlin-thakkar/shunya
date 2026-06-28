"""Auto-filtering managers for tenant + soft-delete."""

from __future__ import annotations

from typing import Any

from django.db import models

from . import context


class TenantAutoFilter:
    def filter_queryset(self, qs: models.QuerySet) -> models.QuerySet:
        tenant = context.current_tenant.get()
        if tenant is None:
            return qs
        return qs.filter(tenant_id=tenant.id)


class SoftDeleteAutoFilter:
    def filter_queryset(self, qs: models.QuerySet) -> models.QuerySet:
        return qs.filter(is_deleted=False)


class AutoFilteringManager(models.Manager):
    _filters: tuple[Any, ...] = ()

    def get_queryset(self) -> models.QuerySet:
        qs = super().get_queryset()
        for f in self._filters:
            qs = f.filter_queryset(qs)
        return qs

    def all_with_deleted(self) -> models.QuerySet:
        qs = super().get_queryset()
        for f in self._filters:
            if isinstance(f, SoftDeleteAutoFilter):
                continue
            qs = f.filter_queryset(qs)
        return qs

    @classmethod
    def factory(cls, *filters: Any) -> type["AutoFilteringManager"]:
        return type(
            "ConcreteAutoFilteringManager",
            (cls,),
            {"_filters": tuple(filters)},
        )
