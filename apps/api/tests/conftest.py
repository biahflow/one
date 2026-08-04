"""Shared fixtures.

Data-layer tests need a real PostgreSQL (enums, JSONB, schema-qualified DDL), so
they connect to ``DATABASE_URL`` (defaulting to the local compose Postgres). When
no database is reachable the fixtures ``pytest.skip`` so the unit suite — and the
current CI job without a database service — still passes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from portal_api.db.session import get_engine

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
    engine = get_engine()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("PostgreSQL is not reachable; skipping database tests")

    command.upgrade(_alembic_config(), "head")
    return engine


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """A session wrapped in a transaction that is rolled back after each test."""
    connection = migrated_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
