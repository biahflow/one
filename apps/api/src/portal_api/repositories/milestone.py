"""Milestone repository (project-scoped)."""

from __future__ import annotations

from portal_api.models import Milestone
from portal_api.repositories.base import TenantScopedRepository


class MilestoneRepository(TenantScopedRepository[Milestone]):
    model = Milestone
