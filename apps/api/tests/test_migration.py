"""The baseline migration applies cleanly and matches the models."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

pytestmark = pytest.mark.integration


def test_head_creates_the_expected_tables(migrated_engine: Engine) -> None:
    tables = set(inspect(migrated_engine).get_table_names(schema="portal"))
    assert {
        "organization",
        "user",
        "project",
        "membership",
        "milestone",
        "delivery",
        "pending_item",
        "audit_log",
        "project_phase",
        "phase_deliverable",
    } <= tables


def test_models_and_migration_do_not_drift(
    migrated_engine: Engine, alembic_config: Config
) -> None:
    # alembic check raises if autogenerate would produce new operations.
    command.check(alembic_config)
