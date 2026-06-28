"""RLS policy primitives.

Models inheriting ``TenantAwareMixin`` declare ``RowLevelSecurityMeta``
listing the policies to attach to their table. This module provides the
policy class + builder functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Policy:
    """A single RLS policy: name + USING clause + optional WITH CHECK."""

    name: str
    using_condition: str
    for_clause: str = "ALL"     # ALL | SELECT | INSERT | UPDATE | DELETE
    with_check_condition: str | None = None

    def create_sql(self, table: str) -> str:
        lines = [
            f"DROP POLICY IF EXISTS {self.name} ON {table};",
            f"CREATE POLICY {self.name} ON {table}",
            f"    FOR {self.for_clause}",
            f"    USING ({self.using_condition})",
        ]
        if self.with_check_condition:
            lines.append(f"    WITH CHECK ({self.with_check_condition})")
        return "\n".join(lines) + ";"

    def drop_sql(self, table: str) -> str:
        return f"DROP POLICY IF EXISTS {self.name} ON {table};"


def enable_rls_sql(table: str, policies: Iterable[Policy]) -> str:
    parts = [f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"]
    for p in policies:
        parts.append(p.create_sql(table))
    return "\n".join(parts)


def disable_rls_sql(table: str, policies: Iterable[Policy]) -> str:
    parts = [p.drop_sql(table) for p in policies]
    parts.append(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    return "\n".join(parts)


# --- Concrete policy builders shared by TenantAwareMixin ------------------

def build_tenant_user_policy(tenant_id_field: str = "tenant_id") -> Policy:
    """Allow access only when the row's tenant matches the session setting."""
    cond = (
        f"coalesce(current_setting('app.current_tenant_id', true), '0')::int "
        f"= {tenant_id_field}"
    )
    return Policy(
        name="multitenant_rls__current_tenant_only",
        using_condition=cond,
        with_check_condition=cond,
    )


def build_cross_tenant_policy() -> Policy:
    """Escape hatch for admin / migrations.

    Bypasses tenant filtering when ``app.cross_tenant_access`` is true.
    Middleware never sets this — only management commands and tests do.
    """
    return Policy(
        name="multitenant_rls__cross_tenant",
        using_condition=(
            "coalesce(current_setting('app.cross_tenant_access', true), 'false')"
            "::boolean"
        ),
    )
