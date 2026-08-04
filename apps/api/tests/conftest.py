"""Shared fixtures.

Data-layer tests need a real PostgreSQL (enums, JSONB, schema-qualified DDL), so
they connect to the compose Postgres. When no database is reachable the fixtures
``pytest.skip`` so the unit suite — and any CI job without a database service —
still passes.

Three roles, three fixtures (ADR 0010):

``db_session``   runs as ``portal_system`` (BYPASSRLS). Tests that arrange data
                 across tenants, and every test written before RLS existed, use
                 it and are unaffected by the policies.
``rls_session``  runs as ``portal_app``, the credential the API actually uses.
                 This is the only way to observe the policies, so
                 ``test_rls_isolation.py`` uses it exclusively.
``migrated_engine`` runs as ``portal_migrator`` to apply the migrations.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from portal_api.db.session import DbRole, get_engine

API_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = API_ROOT / "alembic.ini"
MIGRATIONS_DIR = API_ROOT / "src" / "portal_api" / "db" / "migrations"


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


@pytest.fixture
def alembic_config() -> Config:
    return _alembic_config()


@pytest.fixture(scope="session")
def migrated_engine() -> Engine:
    """Apply migrations as the schema owner, then hand back the system engine.

    The skip is driven by reachability rather than by an unset ``DATABASE_URL``,
    because the settings default already points at the local compose Postgres.
    """
    migration_engine = get_engine(DbRole.migration)
    try:
        with migration_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("PostgreSQL is not reachable; skipping database tests")

    command.upgrade(_alembic_config(), "head")
    return get_engine(DbRole.system)


@pytest.fixture(scope="session")
def app_engine(migrated_engine: Engine) -> Engine:
    """The request-path credential — subject to RLS.

    Depends on ``migrated_engine`` so the schema (and the policies) exist first.
    """
    return get_engine(DbRole.app)


def _transactional_session(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """A ``portal_system`` session, rolled back after each test."""
    yield from _transactional_session(migrated_engine)


@pytest.fixture(scope="session")
def admin_engine(migrated_engine: Engine) -> Engine:
    """The access-administration credential (ADR 0011).

    Also subject to RLS — what it has that ``portal_app`` does not is the grant
    to write ``membership`` and a set of policies keyed on the third-stage GUC.
    """
    return get_engine(DbRole.admin)


@pytest.fixture
def admin_session(admin_engine: Engine) -> Iterator[Session]:
    """A ``portal_admin`` session, rolled back after each test."""
    yield from _transactional_session(admin_engine)


@pytest.fixture
def rls_session(app_engine: Engine) -> Iterator[Session]:
    """A ``portal_app`` session — the one the policies actually apply to.

    ``set_config(..., true)`` issued through this session lands on the outer
    transaction opened here and is reverted by the rollback in teardown, so
    tenant context never leaks between tests.
    """
    yield from _transactional_session(app_engine)


@pytest.fixture
def bind_context(rls_session: Session) -> Callable[..., None]:
    """Set the RLS GUCs on ``rls_session``.

    Mirrors what ``db.session.bind_principal``/``bind_user``/``bind_tenant`` do
    at runtime, but lets a test set any subset — including none, to assert the
    fail-closed behaviour.
    """

    def _bind(
        *,
        subject: str | None = None,
        email: str | None = None,
        user_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> None:
        values = {
            "portal.subject": subject or "",
            "portal.email": (email or "").lower(),
            "portal.user_id": str(user_id) if user_id else "",
            "portal.organization_id": str(organization_id) if organization_id else "",
            "portal.project_id": str(project_id) if project_id else "",
        }
        for name, value in values.items():
            rls_session.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": name, "value": value},
            )

    return _bind


@pytest.fixture
def bind_admin_context(admin_session: Session) -> Callable[..., None]:
    """Set the GUCs on ``admin_session`` — including the third stage (ADR 0011).

    Same idea as ``bind_context``: any subset, so a test can assert what is
    visible *before* ``portal.admin_organization_id`` is published, which is the
    window in which the endpoint verifies the caller's own role.
    """

    def _bind(
        *,
        subject: str | None = None,
        email: str | None = None,
        user_id: uuid.UUID | None = None,
        admin_organization_id: uuid.UUID | None = None,
        invitee_subject: str | None = None,
    ) -> None:
        values = {
            "portal.subject": subject or "",
            "portal.email": (email or "").lower(),
            "portal.user_id": str(user_id) if user_id else "",
            "portal.admin_organization_id": (
                str(admin_organization_id) if admin_organization_id else ""
            ),
            "portal.invitee_subject": invitee_subject or "",
        }
        for name, value in values.items():
            admin_session.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": name, "value": value},
            )

    return _bind
