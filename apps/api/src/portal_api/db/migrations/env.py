"""Alembic environment.

The database URL comes from application settings, not alembic.ini, so the same
configuration drives runtime and migrations. The engine pins ``search_path`` to
the ``portal`` schema (see portal_api.db.session), so unqualified DDL and
reflection both target it and autogenerate compares cleanly.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

from portal_api.db.base import SCHEMA, Base
from portal_api.db.session import get_engine

# Import models so every table is registered on Base.metadata.
import portal_api.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    connectable = get_engine()
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            # Kept inside the Alembic-managed transaction so it commits with the
            # migration (SQLAlchemy 2.0 does not autocommit). The Postgres init
            # script already creates this schema; this guard covers envs that skip it.
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported; a database connection is required.")

run_migrations_online()
