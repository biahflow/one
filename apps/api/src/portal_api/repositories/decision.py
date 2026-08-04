"""Decision repository (project-scoped)."""

from __future__ import annotations

from portal_api.models import Decision
from portal_api.repositories.base import TenantScopedRepository


class DecisionRepository(TenantScopedRepository[Decision]):
    model = Decision
