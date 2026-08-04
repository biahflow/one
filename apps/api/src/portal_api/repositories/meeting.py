"""Meeting repository (project-scoped)."""

from __future__ import annotations

from portal_api.models import Meeting
from portal_api.repositories.base import TenantScopedRepository


class MeetingRepository(TenantScopedRepository[Meeting]):
    model = Meeting
