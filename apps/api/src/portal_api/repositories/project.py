"""Project repository (organization-scoped)."""

from __future__ import annotations

from sqlalchemy import select

from portal_api.models import Project
from portal_api.repositories.base import TenantScopedRepository


class ProjectRepository(TenantScopedRepository[Project]):
    model = Project

    def get_by_slug(self, slug: str) -> Project | None:
        stmt = select(Project).where(
            Project.slug == slug, *self._tenant_filters()
        )
        return self.session.execute(stmt).scalar_one_or_none()
