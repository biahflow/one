"""Tenant isolation at the database level (ADR 0010).

Every other permission test in this suite goes through a repository or through
``access.py``. These go around both: they run raw ``select()`` under the
``portal_app`` credential, which is exactly what ``biahflow.build_dashboard``
does. If a policy is missing or wrong, only this file notices.

The rows are committed by a ``portal_system`` session, because ``rls_session``
is a different connection and would not see an open transaction's writes.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from portal_api.db.session import DbRole, get_session
from portal_api.models import (
    MemberRole,
    Membership,
    Milestone,
    Organization,
    PendingItem,
    PendingState,
    Project,
    ProjectStatus,
    User,
)
from portal_api.principal import Principal

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Tenant:
    organization_id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    subject: str
    email: str
    milestone_id: uuid.UUID


@pytest.fixture(scope="session")
def tenants(migrated_engine: Engine) -> Iterator[tuple[Tenant, Tenant]]:
    """Two fully-populated tenants, committed so another connection sees them.

    Session-scoped because the teardown deletes committed rows from a *different*
    connection: a function-scoped fixture would be finalized before
    ``rls_session``, and the DELETE would then wait forever on the still-open
    transaction of the test that attempted a rejected INSERT (the aborted write
    leaves its xid in progress). Session scope puts the cleanup after every
    function-scoped connection is closed. The tests only read, or attempt writes
    that are rejected or rolled back, so sharing the rows is safe.
    """
    tag = uuid.uuid4().hex[:8]
    built: list[Tenant] = []

    with Session(migrated_engine) as session:
        for name in ("acme", "globex"):
            org = Organization(name=name.title(), slug=f"{name}-{tag}")
            session.add(org)
            session.flush()

            project = Project(
                organization_id=org.id,
                name=f"{name.title()} Project",
                slug=f"{name}-project-{tag}",
                status=ProjectStatus.in_implementation,
            )
            session.add(project)
            session.flush()

            user = User(
                email=f"{name}-{tag}@example.com",
                full_name=f"{name.title()} Client",
                external_subject=f"sub-{name}-{tag}",
            )
            session.add(user)
            session.flush()

            session.add(
                Membership(
                    organization_id=org.id,
                    project_id=project.id,
                    user_id=user.id,
                    role=MemberRole.client_member,
                )
            )
            milestone = Milestone(
                organization_id=org.id,
                project_id=project.id,
                title=f"Kickoff {name}",
            )
            session.add(milestone)
            session.flush()

            built.append(
                Tenant(
                    organization_id=org.id,
                    project_id=project.id,
                    user_id=user.id,
                    subject=user.external_subject or "",
                    email=user.email,
                    milestone_id=milestone.id,
                )
            )
        session.commit()

    yield built[0], built[1]

    with Session(migrated_engine) as session:
        session.execute(
            delete(Organization).where(
                Organization.id.in_([t.organization_id for t in built])
            )
        )
        session.execute(delete(User).where(User.id.in_([t.user_id for t in built])))
        session.commit()


def _bind_full(bind_context, tenant: Tenant) -> None:
    bind_context(
        subject=tenant.subject,
        email=tenant.email,
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        project_id=tenant.project_id,
    )


# 1 — the invariant everything else rests on ------------------------------------


def test_the_app_role_is_neither_superuser_nor_bypassrls(rls_session: Session) -> None:
    """Guard against a misconfigured DATABASE_URL silently disabling RLS.

    A superuser ignores policies unconditionally, so pointing DATABASE_URL at
    ``portal`` would make every other test here pass while proving nothing.
    """
    row = rls_session.execute(
        text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
    ).one()

    assert row.rolsuper is False
    assert row.rolbypassrls is False


def test_reads_without_any_context_return_nothing(
    rls_session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    """Fail-closed: an unset GUC is NULL, the predicate is not TRUE, no rows."""
    assert rls_session.execute(select(Milestone)).scalars().all() == []
    assert rls_session.execute(select(Project)).scalars().all() == []
    assert rls_session.execute(select(Organization)).scalars().all() == []
    assert rls_session.execute(select(Membership)).scalars().all() == []
    assert rls_session.execute(select(PendingItem)).scalars().all() == []


# 2 — scoping --------------------------------------------------------------------


def test_context_scopes_reads_to_one_tenant(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant_a, tenant_b = tenants
    _bind_full(bind_context, tenant_a)

    milestones = rls_session.execute(select(Milestone)).scalars().all()

    assert [m.id for m in milestones] == [tenant_a.milestone_id]
    assert tenant_b.milestone_id not in {m.id for m in milestones}


def test_another_tenants_row_is_unreachable_even_by_primary_key(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """Holding the UUID is not authorization — the IDOR case from the threat model."""
    tenant_a, tenant_b = tenants
    _bind_full(bind_context, tenant_a)

    assert rls_session.get(Milestone, tenant_b.milestone_id) is None
    assert rls_session.get(Project, tenant_b.project_id) is None
    assert rls_session.get(Organization, tenant_b.organization_id) is None


def test_project_and_organization_follow_membership(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """This is what preserves "404, never 403": a non-member resolves to None."""
    tenant_a, _ = tenants
    # Only stage 1 — the project policy must work before the org is known.
    bind_context(subject=tenant_a.subject, email=tenant_a.email, user_id=tenant_a.user_id)

    projects = rls_session.execute(select(Project)).scalars().all()
    organizations = rls_session.execute(select(Organization)).scalars().all()

    assert [p.id for p in projects] == [tenant_a.project_id]
    assert [o.id for o in organizations] == [tenant_a.organization_id]


def test_membership_is_visible_only_to_its_own_user(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant_a, tenant_b = tenants
    bind_context(subject=tenant_a.subject, email=tenant_a.email, user_id=tenant_a.user_id)

    memberships = rls_session.execute(select(Membership)).scalars().all()

    assert {m.user_id for m in memberships} == {tenant_a.user_id}
    assert tenant_b.user_id not in {m.user_id for m in memberships}


# 3 — writes ----------------------------------------------------------------------


def test_insert_into_another_tenant_is_rejected(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant_a, tenant_b = tenants
    _bind_full(bind_context, tenant_a)

    rls_session.add(
        PendingItem(
            organization_id=tenant_b.organization_id,
            project_id=tenant_b.project_id,
            title="Smuggled",
            state=PendingState.open,
        )
    )

    with pytest.raises(ProgrammingError, match="row-level security"):
        rls_session.flush()


def test_the_read_model_is_not_writable_by_the_app_role(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """Biahflow is the source of truth (ADR 0006/0008), enforced in the database."""
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(
            text("UPDATE milestone SET title = 'tampered' WHERE id = :id"),
            {"id": tenant_a.milestone_id},
        )


def test_a_user_cannot_provision_a_row_for_another_subject(
    rls_session: Session, bind_context
) -> None:
    tag = uuid.uuid4().hex[:8]
    bind_context(subject=f"sub-honest-{tag}", email=f"honest-{tag}@example.com")

    rls_session.add(
        User(
            email=f"honest-{tag}@example.com",
            full_name="Impersonator",
            external_subject=f"sub-someone-else-{tag}",
        )
    )

    with pytest.raises(ProgrammingError, match="row-level security"):
        rls_session.flush()


def test_a_user_row_belonging_to_someone_else_is_invisible(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant_a, tenant_b = tenants
    bind_context(subject=tenant_a.subject, email=tenant_a.email, user_id=tenant_a.user_id)

    users = rls_session.execute(select(User)).scalars().all()

    assert [u.id for u in users] == [tenant_a.user_id]
    assert rls_session.get(User, tenant_b.user_id) is None


# 4 — the system path -------------------------------------------------------------


def test_the_system_role_bypasses_the_policies(
    db_session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    """Without this the Biahflow webhook could not create a tenant at all."""
    tenant_a, tenant_b = tenants

    visible = {m.id for m in db_session.execute(select(Milestone)).scalars().all()}

    assert {tenant_a.milestone_id, tenant_b.milestone_id} <= visible


# 5 — the pooled connection -------------------------------------------------------


def test_context_does_not_leak_into_the_next_transaction(
    tenants: tuple[Tenant, Tenant],
) -> None:
    """``set_config(..., true)`` is transaction-local; a bare SET would leak.

    Uses ``get_session`` rather than the fixtures so the connection really is
    returned to the pool and picked up again.
    """
    tenant_a, _ = tenants
    principal = Principal(
        subject=tenant_a.subject, email=tenant_a.email, full_name="Acme Client"
    )

    with get_session(principal) as session:
        assert session.execute(
            text("SELECT current_setting('portal.subject', true)")
        ).scalar() == tenant_a.subject

    with get_session() as session:
        leaked = session.execute(
            text(
                "SELECT nullif(current_setting('portal.subject', true), '') AS subject,"
                "       nullif(current_setting('portal.organization_id', true), '') AS organization_id"
            )
        ).one()

    assert leaked.subject is None
    assert leaked.organization_id is None


def test_a_principal_cannot_run_under_the_system_role() -> None:
    principal = Principal(subject="sub-x", email="x@example.com", full_name="X")

    with pytest.raises(ValueError, match="system role"):
        with get_session(principal, role=DbRole.system):
            pass  # pragma: no cover - the context manager raises on entry


# 6 — the guard that protects future phases ---------------------------------------


def test_every_tenant_table_has_rls_enabled_and_a_policy(db_session: Session) -> None:
    """A table added in a later phase without a policy fails CI on its own.

    This is the piece that keeps the control from eroding: the Fase 4 knowledge
    tables will carry ``organization_id`` too, and forgetting the policy there
    would silently reopen cross-tenant reads.
    """
    unprotected = db_session.execute(
        text(
            """
            SELECT c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_attribute a ON a.attrelid = c.oid
             WHERE n.nspname = 'portal'
               AND c.relkind = 'r'
               AND a.attname = 'organization_id'
               AND NOT a.attisdropped
               AND (NOT c.relrowsecurity
                    OR NOT EXISTS (SELECT 1 FROM pg_policies p
                                    WHERE p.schemaname = n.nspname
                                      AND p.tablename = c.relname))
            """
        )
    ).scalars().all()

    assert unprotected == [], f"tables with organization_id but no RLS: {unprotected}"
