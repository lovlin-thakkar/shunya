"""Per-request tenant scope, stored in a ContextVar."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .models import Tenant

current_tenant: ContextVar[Optional["Tenant"]] = ContextVar(
    "current_tenant", default=None
)


def get_current_tenant_id() -> Optional[int]:
    t = current_tenant.get()
    return t.id if t is not None else None
