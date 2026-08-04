"""Project authorization for the portal (ADR 0002/0006/0010).

The membership — not the realm role — decides what a caller reaches: a realm role
cannot say *which project*. Every miss returns ``None`` so the caller answers 404
and never leaks which projects exist.

**Every resolver here binds the tenant context on the happy path.** That is a
deliberate side effect: the RLS policies on the project-scoped tables read
``portal.organization_id``/``portal.project_id``, so an endpoint that resolved a
project without binding would go on to read zero rows — a silent empty dashboard
instead of an error. Keeping the bind next to the authorization decision means no
endpoint has to remember it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api.db.session import bind_tenant
from portal_api.models import MemberRole, Membership, Project, User
from portal_api.repositories import MembershipRepository, TenantContext

ANY_MEMBER = frozenset(MemberRole)
ADMIN_ONLY = frozenset({MemberRole.internal_admin})


def require_project(
    session: Session,
    user: User,
    project_id: uuid.UUID,
    allowed: frozenset[MemberRole] = ANY_MEMBER,
) -> Project | None:
    """The project, if the user holds one of ``allowed`` roles on it.

    ``session.get`` is already filtered by the ``project`` policy, so a
    non-member gets ``None`` from the database itself; the role check on top is
    what turns "is a member" into "may do *this*".
    """
    project = session.get(Project, project_id)
    if project is None:
        return None

    memberships = MembershipRepository(session, TenantContext(project.organization_id))
    if not memberships.roles_for_project(user.id, project.id) & allowed:
        return None

    bind_tenant(session, TenantContext(project.organization_id, project.id))
    return project


def scoped_project(
    session: Session, user: User, project_id: uuid.UUID
) -> Project | None:
    """The project by id, for any kind of membership."""
    return require_project(session, user, project_id, ANY_MEMBER)


def default_project(session: Session, user: User) -> Project | None:
    """The project to show when the caller did not name one.

    A client has a direct membership and that is the answer. Internal staff
    usually carry an organization-wide membership (``project_id IS NULL``), which
    used to resolve to nothing at all — they now land on the organization's most
    recent project.
    """
    # The membership policy already restricts this to the caller's own rows.
    memberships = list(
        session.execute(
            select(Membership)
            .where(Membership.user_id == user.id)
            .order_by(Membership.created_at.desc())
        ).scalars()
    )

    project: Project | None = None
    direct = next((m for m in memberships if m.project_id is not None), None)
    if direct is not None:
        project = session.get(Project, direct.project_id)
    else:
        org_wide = next((m for m in memberships if m.project_id is None), None)
        if org_wide is not None:
            project = session.execute(
                select(Project)
                .where(Project.organization_id == org_wide.organization_id)
                .order_by(Project.created_at.desc())
            ).scalars().first()

    if project is None:
        return None

    bind_tenant(session, TenantContext(project.organization_id, project.id))
    return project


def visible_projects(
    session: Session, user: User
) -> list[tuple[Project, set[MemberRole]]]:
    """Every project the caller can reach, with the roles held on each.

    Feeds ``GET /api/v1/me``, and deliberately does **not** bind a tenant: the
    listing spans projects while the stage-2 GUCs hold exactly one.
    """
    memberships = list(
        session.execute(
            select(Membership).where(Membership.user_id == user.id)
        ).scalars()
    )
    organizations = {m.organization_id for m in memberships}
    if not organizations:
        return []

    # The project policy already narrows this to what the memberships cover.
    projects = list(
        session.execute(
            select(Project)
            .where(Project.organization_id.in_(organizations))
            .order_by(Project.created_at.desc())
        ).scalars()
    )
    return [
        (
            project,
            {
                m.role
                for m in memberships
                if m.organization_id == project.organization_id
                and m.project_id in (None, project.id)
            },
        )
        for project in projects
    ]
