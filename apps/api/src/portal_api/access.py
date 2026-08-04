"""Client access resolution for the portal (ADR 0002/0006, Fase 2).

The BFF passes the client's identity (email) server-to-server; here we resolve it to the
project the client is actually a member of. Returning ``None`` on any miss lets callers 404
without leaking which projects exist. In production the email comes from the OIDC session.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api.models import MemberRole, Membership, Project
from portal_api.repositories import MembershipRepository, TenantContext, UserRepository


def scoped_project(session: Session, email: str, project_id: uuid.UUID) -> Project | None:
    """The project, only if the client is a member of it; otherwise ``None``."""
    user = UserRepository(session).get_by_email(email)
    project = session.get(Project, project_id)
    if user is None or project is None:
        return None
    memberships = MembershipRepository(session, TenantContext(project.organization_id))
    if not memberships.roles_for_project(user.id, project.id):
        return None
    return project


def client_project(session: Session, email: str) -> Project | None:
    """The client's own project (first ``client_member`` membership); otherwise ``None``."""
    user = UserRepository(session).get_by_email(email)
    if user is None:
        return None
    membership = session.execute(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.role == MemberRole.client_member,
            Membership.project_id.is_not(None),
        )
    ).scalars().first()
    if membership is None or membership.project_id is None:
        return None
    return session.get(Project, membership.project_id)
