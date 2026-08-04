"""Audit log repository (organization-scoped, append-only)."""

from __future__ import annotations

from portal_api.models import AuditLog
from portal_api.repositories.base import TenantScopedRepository


class AuditLogRepository(TenantScopedRepository[AuditLog]):
    model = AuditLog
