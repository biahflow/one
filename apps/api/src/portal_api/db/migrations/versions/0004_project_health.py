"""friendly project health from Biahflow

Revision ID: 0004_project_health
Revises: 0003_journey_and_roi
Create Date: 2026-08-04

Adds the friendly health projection columns on ``project`` (label + colour level),
denormalized from the Biahflow snapshot. Additive only; no internal score/signals.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0004_project_health'
down_revision: str | None = '0003_journey_and_roi'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('project', sa.Column('health_label', sa.String(length=60), nullable=True))
    op.add_column('project', sa.Column('health_level', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('project', 'health_level')
    op.drop_column('project', 'health_label')
