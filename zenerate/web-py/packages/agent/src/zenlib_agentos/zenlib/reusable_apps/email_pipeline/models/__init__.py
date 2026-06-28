"""Add your models here.

Phase 1: ``LogicalThread``, ``RoleInboxLink``, ``Message``, ``ProcessedEvent``.
Phase 2: ``ApprovalDraft``.
Phase 4: ``InternalComment``.

All inherit ``ActivityTenantBaseModel`` from
``zenlib.reusable_apps.multitenant.models``. The base provides tenant FK,
soft-delete, last-activity tracking, and RLS — you do not write RLS
migrations or repeat the tenant field.

Re-export public symbols here so callers can do
``from email_pipeline.models import LogicalThread``.
"""
