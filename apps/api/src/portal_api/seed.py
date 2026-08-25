"""Local seed: the realm's users, and a project for them to look at (ADR 0010).

Run it with ``python -m portal_api.seed``; the ``api-seed`` service in the
compose does exactly that on every ``up``. Idempotent by construction, so it is
safe to re-run.

**The realm and this file are two halves of one fact.** Keycloak's realm import
accepts a fixed ``"id"`` per user, and that id *is* the ``sub`` claim — so the
subjects in ``SEED_USERS`` are the same UUIDs written in
``infra/keycloak/portal-local-realm.json``. That is what lets a seeded row carry
``external_subject`` from the start instead of waiting to be linked by e-mail on
first login. ``test_seed_matches_realm.py`` fails the build if the two drift.

The project data enters through ``biahflow.sync_snapshot`` with a versioned
snapshot, the very same door the webhook uses — the portal still originates no
status of its own (ADR 0006/0008), and local development gets a real dashboard
without the Biahflow stack, which lives in another repository.

Runs as ``portal_system``: this is a path that *creates* a tenant, so there is
no context to bind and RLS would (correctly) deny the writes.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from portal_api.db.session import DbRole, get_session
from portal_api.integrations import biahflow
from portal_api.models import MemberRole, Membership, Project, User

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = Path(__file__).parent / "seed_data" / "biahflow-snapshot.json"


@dataclass(frozen=True)
class SeedUser:
    """A realm user and the membership it should hold in the portal.

    ``subject`` is the Keycloak user id; ``role`` doubles as the realm role name
    because ``MemberRole`` is aligned 1:1 with the roles in the realm.
    """

    subject: str
    email: str
    full_name: str
    role: MemberRole

    @property
    def is_internal(self) -> bool:
        return self.role is not MemberRole.client_member


SEED_USERS: tuple[SeedUser, ...] = (
    SeedUser(
        subject="00000000-0000-4000-8000-000000000001",
        email="marina.farias@acme.com.br",
        full_name="Marina Farias",
        role=MemberRole.client_member,
    ),
    SeedUser(
        subject="00000000-0000-4000-8000-000000000002",
        email="helena.dias@biahflow.ai",
        full_name="Helena Dias",
        role=MemberRole.internal_admin,
    ),
    SeedUser(
        subject="00000000-0000-4000-8000-000000000003",
        email="rafael.costa@biahflow.ai",
        full_name="Rafael Costa",
        role=MemberRole.internal_member,
    ),
)


def load_snapshot() -> dict[str, Any]:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _upsert_user(session: Session, seed_user: SeedUser) -> User:
    """The user row, matched by subject first and by e-mail as a fallback.

    The e-mail fallback exists because ``ensure_demo_client`` (the webhook under
    ``DEMO_MODE``) may have created the same person without a subject. Claiming
    that row here is the same link ``identity.resolve_user`` would do on first
    login — doing it now just means the row is complete before anyone logs in.
    """
    user = session.execute(
        select(User).where(User.external_subject == seed_user.subject)
    ).scalar_one_or_none()
    if user is None:
        user = session.execute(
            select(User).where(func.lower(User.email) == seed_user.email)
        ).scalar_one_or_none()
    if user is None:
        user = User(email=seed_user.email)
        session.add(user)

    user.email = seed_user.email
    user.full_name = seed_user.full_name
    user.external_subject = seed_user.subject
    user.is_internal = seed_user.is_internal
    session.flush()
    return user


def _upsert_membership(
    session: Session, user: User, project: Project, seed_user: SeedUser
) -> Membership:
    """One membership per seeded user.

    Clients get a membership on the project itself; internal staff get an
    organization-wide one (``project_id IS NULL``), which is what
    ``access.default_project`` resolves to the organization's latest project.
    """
    project_id: uuid.UUID | None = (
        project.id if seed_user.role is MemberRole.client_member else None
    )
    # `uq_membership_user_project` does not dedupe the org-wide rows — Postgres
    # treats NULLs as distinct — so the lookup is explicit about it.
    scope = (
        Membership.project_id == project_id
        if project_id is not None
        else Membership.project_id.is_(None)
    )
    # E filtra pela organização, sem o que a busca não identifica uma linha.
    # Isto só passou a importar quando a **segunda** organização passou a
    # existir: o bootstrap da ADR 0025 dá a quem administra um vínculo de escopo
    # organizacional na organização nova, então uma pessoa interna acumula um
    # `project_id IS NULL` por organização — e o `scalar_one_or_none` acima
    # estourava `MultipleResultsFound`, derrubando o `api-seed` a cada
    # `docker compose up`.
    membership = session.execute(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organization_id == project.organization_id,
            scope,
        )
    ).scalar_one_or_none()
    if membership is None:
        membership = Membership(
            organization_id=project.organization_id,
            project_id=project_id,
            user_id=user.id,
            role=seed_user.role,
        )
        session.add(membership)
    else:
        membership.organization_id = project.organization_id
        membership.role = seed_user.role
    session.flush()
    return membership


def seed(session: Session) -> Project:
    """Apply the snapshot and the seeded users. Returns the seeded project."""
    project = biahflow.sync_snapshot(session, load_snapshot())
    for seed_user in SEED_USERS:
        user = _upsert_user(session, seed_user)
        _upsert_membership(session, user, project, seed_user)
    return project


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with get_session(role=DbRole.system) as session:
        project = seed(session)
        logger.info(
            "seed.applied project=%s users=%d", project.slug, len(SEED_USERS)
        )


if __name__ == "__main__":
    main()
