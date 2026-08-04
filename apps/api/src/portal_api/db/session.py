"""Engines, sessions and the per-transaction tenant context (ADR 0010).

Three Postgres roles, three engines. ``portal_app`` is the request path and is
subject to Row-Level Security; ``portal_system`` carries ``BYPASSRLS`` for the
paths that *create* a tenant (the Biahflow webhook and the seed); and
``portal_migrator`` owns the schema and runs Alembic.

The RLS policies read their scope from GUCs set with ``set_config(..., true)``
inside the transaction, in two stages:

  stage 1  portal.subject, portal.email  → the caller's own ``user`` row
           portal.user_id                → ``membership``, and through it
                                           ``organization`` and ``project``
  stage 2  portal.organization_id,       → the project-scoped tables
           portal.project_id

Every GUC is fail-closed: ``current_setting(..., true)`` returns NULL when it
was never set, the policy predicate is then NULL rather than TRUE, and the row
is filtered out. Missing context yields zero rows, never an unscoped read.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from portal_api.config import get_settings
from portal_api.db.base import SCHEMA
from portal_api.principal import Principal

if TYPE_CHECKING:
    # Type-only: importing repositories here would pull models back through
    # portal_api.db while this module is still initializing.
    from portal_api.repositories.context import TenantContext


class DbRole(str, enum.Enum):
    """Which Postgres credential a unit of work runs under."""

    app = "app"
    system = "system"
    migration = "migration"


def _url_for(role: DbRole) -> str:
    settings = get_settings()
    url = {
        DbRole.app: settings.database_url,
        DbRole.system: settings.database_system_url,
        DbRole.migration: settings.database_migration_url,
    }[role]
    if not url:
        # Fail closed: never silently fall back to another role's credential.
        raise RuntimeError(f"No database URL configured for the {role.value} role")
    return url


@lru_cache
def get_engine(role: DbRole = DbRole.app) -> Engine:
    return create_engine(
        _url_for(role),
        pool_pre_ping=True,
        future=True,
        # Pin every connection to the portal schema so unqualified DDL and
        # reflection both target it (see portal_api.db.base).
        connect_args={"options": f"-csearch_path={SCHEMA}"},
    )


@lru_cache
def session_factory(role: DbRole = DbRole.app) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(role), expire_on_commit=False, future=True)


def reset_engines() -> None:
    """Drop the cached engines so a settings change takes effect.

    ``get_engine`` and ``get_settings`` are both ``lru_cache``d, so without this
    a test that repoints ``DATABASE_URL`` would keep the first credential — and
    would then pass under the wrong role.
    """
    get_engine.cache_clear()
    session_factory.cache_clear()


def bind_principal(session: Session, principal: Principal) -> None:
    """Stage 1: publish the verified identity to the transaction.

    Only the claims that survived signature/issuer/audience validation get in
    here. ``portal.email`` exists solely so a seeded row with no
    ``external_subject`` can be claimed on first login.
    """
    session.execute(
        text(
            "SELECT set_config('portal.subject', :subject, true),"
            "       set_config('portal.email', :email, true)"
        ),
        {"subject": principal.subject, "email": principal.email.lower()},
    )


def bind_user(session: Session, user_id: uuid.UUID) -> None:
    """Stage 1 (continued): the resolved ``user.id``, which unlocks membership."""
    session.execute(
        text("SELECT set_config('portal.user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )


def bind_tenant(session: Session, ctx: "TenantContext") -> None:
    """Stage 2: scope the transaction to one organization and project.

    Monotonic on purpose: rebinding a transaction to a different tenant is a
    programming error (a reused session), and silently allowing it would be the
    exact bug the RLS exists to prevent.
    """
    current = session.execute(
        text(
            "SELECT nullif(current_setting('portal.organization_id', true), '') AS organization_id,"
            "       nullif(current_setting('portal.project_id', true), '') AS project_id"
        )
    ).one()
    organization_id, project_id = str(ctx.organization_id), str(ctx.project_id or "")
    if current.organization_id not in (None, organization_id) or current.project_id not in (
        None,
        project_id,
    ):
        raise RuntimeError(
            "Transaction is already bound to another tenant "
            f"({current.organization_id}/{current.project_id}); refusing to rebind"
        )
    session.execute(
        text(
            "SELECT set_config('portal.organization_id', :organization_id, true),"
            "       set_config('portal.project_id', :project_id, true)"
        ),
        {"organization_id": organization_id, "project_id": project_id},
    )


@contextmanager
def get_session(
    principal: Principal | None = None, *, role: DbRole = DbRole.app
) -> Iterator[Session]:
    """Yield a session, committing on success and rolling back on error.

    Passing ``principal`` binds stage 1 immediately, so the very first statement
    already runs scoped. The context is set with ``set_config(..., true)``, which
    Postgres reverts at the end of the transaction — a plain ``SET`` would leak
    into the next request that reuses the pooled connection.
    """
    if principal is not None and role is not DbRole.app:
        raise ValueError(f"A principal cannot run under the {role.value} role")

    session = session_factory(role)()
    try:
        if principal is not None:
            bind_principal(session, principal)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
