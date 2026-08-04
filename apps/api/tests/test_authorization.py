"""Negative permission cases through the real HTTP stack (AGENTS.md #6, ADR 0010).

Only ``bearer_principal`` is overridden — token validation has its own file. From
there down everything is real: the endpoints open a session under ``portal_app``,
resolve the user, and read through the RLS policies. So a "404" here means the
denial survived the whole chain, not that a mock said no.

The rows are committed by a ``portal_system`` session because the app answers on
a different connection and would not see an open transaction's writes.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from portal_api.auth import bearer_principal
from portal_api.main import app
from portal_api.models import (
    AuditLog,
    MemberRole,
    Membership,
    Organization,
    PendingItem,
    Project,
    ProjectStatus,
    User,
)
from portal_api.principal import Principal

pytestmark = pytest.mark.integration

client = TestClient(app)


@dataclass(frozen=True)
class Actor:
    subject: str
    email: str
    full_name: str
    realm_roles: tuple[str, ...] = ("client_member",)


@dataclass(frozen=True)
class Tenant:
    organization_id: uuid.UUID
    organization_name: str
    project_id: uuid.UUID
    project_name: str
    client: Actor


@dataclass(frozen=True)
class World:
    acme: Tenant
    globex: Tenant
    staff: Actor
    seeded: Actor  # exists in the database with no external_subject yet


@pytest.fixture(scope="session")
def world(migrated_engine: Engine) -> Iterator[World]:
    tag = uuid.uuid4().hex[:8]
    tenants: dict[str, Tenant] = {}

    with Session(migrated_engine) as session:
        for name in ("acme", "globex"):
            organization = Organization(name=name.title(), slug=f"{name}-{tag}")
            session.add(organization)
            session.flush()

            project = Project(
                organization_id=organization.id,
                name=f"Automação {name.title()}",
                slug=f"{name}-project-{tag}",
                status=ProjectStatus.in_implementation,
            )
            session.add(project)
            session.flush()

            user = User(
                email=f"cliente-{name}-{tag}@example.com",
                full_name=f"Cliente {name.title()}",
                external_subject=f"sub-cliente-{name}-{tag}",
            )
            session.add(user)
            session.flush()
            session.add(
                Membership(
                    organization_id=organization.id,
                    project_id=project.id,
                    user_id=user.id,
                    role=MemberRole.client_member,
                )
            )

            tenants[name] = Tenant(
                organization_id=organization.id,
                organization_name=organization.name,
                project_id=project.id,
                project_name=project.name,
                client=Actor(user.external_subject or "", user.email, user.full_name),
            )

        # Staff: organization-wide membership, no project — the case that used to
        # resolve to nothing at all.
        staff = User(
            email=f"ops-{tag}@portallabs.test",
            full_name="Ops Portal Labs",
            external_subject=f"sub-ops-{tag}",
            is_internal=True,
        )
        session.add(staff)
        session.flush()
        session.add(
            Membership(
                organization_id=tenants["acme"].organization_id,
                project_id=None,
                user_id=staff.id,
                role=MemberRole.internal_admin,
            )
        )

        # Seeded like the versioned seed does: known e-mail, no subject yet.
        seeded = User(
            email=f"semeado-{tag}@example.com",
            full_name="Cliente Semeado",
            external_subject=None,
        )
        session.add(seeded)
        session.flush()
        session.add(
            Membership(
                organization_id=tenants["acme"].organization_id,
                project_id=tenants["acme"].project_id,
                user_id=seeded.id,
                role=MemberRole.client_member,
            )
        )
        session.commit()

        built = World(
            acme=tenants["acme"],
            globex=tenants["globex"],
            staff=Actor(
                staff.external_subject or "",
                staff.email,
                staff.full_name,
                ("internal_admin",),
            ),
            seeded=Actor(f"sub-semeado-{tag}", seeded.email, seeded.full_name),
        )

    yield built

    with Session(migrated_engine) as session:
        session.execute(
            delete(Organization).where(
                Organization.id.in_(
                    [built.acme.organization_id, built.globex.organization_id]
                )
            )
        )
        session.execute(delete(User).where(User.email.like(f"%-{tag}@%")))
        session.commit()


@pytest.fixture
def authenticated() -> Iterator[Callable[[Actor], None]]:
    """Swap in a verified principal, exactly as a good token would produce."""

    def _as(actor: Actor) -> None:
        app.dependency_overrides[bearer_principal] = lambda: Principal(
            subject=actor.subject,
            email=actor.email,
            full_name=actor.full_name,
            realm_roles=frozenset(actor.realm_roles),
        )

    yield _as
    app.dependency_overrides.clear()


# --- cross-tenant ---------------------------------------------------------


def test_a_client_cannot_reach_another_tenants_project(world: World, authenticated) -> None:
    """404 and not 403: the answer must not reveal that the project exists."""
    authenticated(world.acme.client)

    mine = client.get(f"/api/v1/projects/{world.acme.project_id}/dashboard")
    theirs = client.get(f"/api/v1/projects/{world.globex.project_id}/dashboard")

    assert mine.status_code == 200
    assert mine.json()["project"] == world.acme.project_name
    assert theirs.status_code == 404


def test_me_lists_only_the_callers_own_projects(world: World, authenticated) -> None:
    authenticated(world.acme.client)

    body = client.get("/api/v1/me").json()

    assert [p["id"] for p in body["projects"]] == [str(world.acme.project_id)]
    assert body["organization"] == world.acme.organization_name
    assert body["roles"] == ["client_member"]
    assert world.globex.project_name not in repr(body)


def test_me_dashboard_resolves_the_clients_own_project(world: World, authenticated) -> None:
    authenticated(world.acme.client)

    body = client.get("/api/v1/me/dashboard").json()

    assert body["project"] == world.acme.project_name
    assert body["organization"] == world.acme.organization_name


# --- identity without authorization ---------------------------------------


def test_an_authenticated_user_without_membership_authorizes_nothing(
    world: World, authenticated, db_session: Session
) -> None:
    """Authentication is not authorization — and the difference is visible.

    The user row is provisioned on first login, so the portal can greet them, and
    every project query still resolves to nothing.
    """
    stranger = Actor(
        subject=f"sub-stranger-{uuid.uuid4().hex[:8]}",
        email=f"stranger-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Estranho",
    )
    authenticated(stranger)

    me = client.get("/api/v1/me")
    dashboard = client.get("/api/v1/me/dashboard")
    project = client.get(f"/api/v1/projects/{world.acme.project_id}/dashboard")

    assert me.status_code == 200
    assert me.json()["projects"] == []
    assert dashboard.status_code == 404
    assert project.status_code == 404

    provisioned = db_session.execute(
        select(User).where(User.external_subject == stranger.subject)
    ).scalar_one()
    assert provisioned.email == stranger.email
    db_session.execute(delete(User).where(User.id == provisioned.id))
    db_session.commit()


def test_a_seeded_row_is_claimed_on_first_login(
    world: World, authenticated, db_session: Session
) -> None:
    """The realm and the versioned seed meet here: the e-mail links, the sub sticks."""
    authenticated(world.seeded)

    body = client.get("/api/v1/me/dashboard").json()

    assert body["project"] == world.acme.project_name
    linked = db_session.execute(
        select(User).where(User.email == world.seeded.email)
    ).scalar_one()
    assert linked.external_subject == world.seeded.subject


# --- roles ----------------------------------------------------------------


def test_agent_events_are_closed_to_clients(world: World, authenticated) -> None:
    """Was anonymous under DEMO_MODE; a membership alone is no longer enough."""
    authenticated(world.acme.client)

    response = client.post(
        "/api/v1/agent-events",
        json={
            "event_id": str(uuid.uuid4()),
            "project_id": str(world.acme.project_id),
            "occurred_at": "2026-08-03",
            "agent_key": "finance-agent",
            "time_saved_seconds": 120,
            "avoided_cost_cents": 5000,
            "run_reference": "run-001",
        },
    )

    assert response.status_code == 404


def test_internal_staff_reach_the_organizations_project(world: World, authenticated) -> None:
    """The org-wide membership carries no project id, and used to 404 for staff."""
    authenticated(world.staff)

    dashboard = client.get("/api/v1/me/dashboard")
    event = client.post(
        "/api/v1/agent-events",
        json={
            "event_id": str(uuid.uuid4()),
            "project_id": str(world.acme.project_id),
            "occurred_at": "2026-08-03",
            "agent_key": "finance-agent",
            "time_saved_seconds": 120,
            "avoided_cost_cents": 5000,
            "run_reference": "run-001",
        },
    )

    assert dashboard.status_code == 200
    assert dashboard.json()["project"] == world.acme.project_name
    assert event.status_code == 202


def test_staff_cannot_post_events_for_another_organization(world: World, authenticated) -> None:
    authenticated(world.staff)

    response = client.post(
        "/api/v1/agent-events",
        json={
            "event_id": str(uuid.uuid4()),
            "project_id": str(world.globex.project_id),
            "occurred_at": "2026-08-03",
            "agent_key": "finance-agent",
            "time_saved_seconds": 120,
            "avoided_cost_cents": 5000,
            "run_reference": "run-001",
        },
    )

    assert response.status_code == 404


# --- the app role's only writes -------------------------------------------


def test_a_gap_in_the_chat_writes_a_pendencia_and_an_audit_entry(
    world: World, authenticated, db_session: Session
) -> None:
    """The two inserts ``portal_app`` is allowed to make, exercised end to end.

    ``audit_log`` grants INSERT and no SELECT, so this also pins the mapper down:
    an ``INSERT ... RETURNING`` there would need a read the policy denies.
    """
    authenticated(world.acme.client)

    response = client.post(
        "/api/v1/chat",
        json={"question": "Qual é a política de retenção de dados do contrato?"},
    )

    assert response.status_code == 200
    assert response.json()["pending_created"] is True

    pendings = db_session.execute(
        select(PendingItem).where(PendingItem.project_id == world.acme.project_id)
    ).scalars().all()
    assert len(pendings) == 1

    entry = db_session.execute(
        select(AuditLog).where(AuditLog.organization_id == world.acme.organization_id)
    ).scalars().one()
    assert entry.action == "chat.pending_created"
    assert entry.entity_id == pendings[0].id
    # Não anônima: o autor da pergunta fica registrado.
    assert entry.actor_user_id is not None
