"""GUC names used by RLS policies."""

CONF_NAME__CURRENT_TENANT_ID = "app.current_tenant_id"
CONF_NAME__CROSS_TENANT_ACCESS = "app.cross_tenant_access"


def default_rls_options() -> dict:
    return {"enabled": True}
