"""Membership repository (organization-scoped)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from portal_api.models import MemberRole, Membership
from portal_api.repositories.base import TenantScopedRepository


class MembershipRepository(TenantScopedRepository[Membership]):
    model = Membership

    def list_for_user(self, user_id: uuid.UUID) -> list[Membership]:
        """Every membership the user holds within the current organization."""
        stmt = select(Membership).where(
            Membership.user_id == user_id,
            Membership.organization_id == self.ctx.organization_id,
        )
        return list(self.session.execute(stmt).scalars())

    def roles_for_project(
        self, user_id: uuid.UUID, project_id: uuid.UUID
    ) -> set[MemberRole]:
        """Roles the user has on a project: its direct membership plus any
        organization-wide (null-project) membership."""
        stmt = select(Membership.role).where(
            Membership.user_id == user_id,
            Membership.organization_id == self.ctx.organization_id,
            (Membership.project_id == project_id) | (Membership.project_id.is_(None)),
        )
        return set(self.session.execute(stmt).scalars())
