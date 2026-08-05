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
from portal_api.db.session import DbRole, get_engine

# Import models so every table is registered on Base.metadata.
import portal_api.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    # `disable_existing_loggers=False` **não** é cosmético (ADR 0018). O padrão
    # do `fileConfig` é `True`, e ele marca `disabled` em todo logger já criado
    # que o `alembic.ini` não nomeia — ou seja, em todos os `portal_api.*`.
    # Quem roda a migração no mesmo processo em que a aplicação vive (o
    # `conftest.py` da suíte faz isso antes dos testes) ficava sem uma linha de
    # log depois dela, e a telemetria desta fase seria a primeira vítima.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    # portal_migrator owns the schema: DDL, and exemption from RLS by ownership
    # (the policies use ENABLE, not FORCE, precisely so backfills still work).
    connectable = get_engine(DbRole.migration)
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
