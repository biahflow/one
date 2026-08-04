"""digital employees mirrored from Biahflow

Revision ID: 0005_digital_employee
Revises: 0004_project_health
Create Date: 2026-08-04

Adds the ``digital_employee`` read-model table (the AI agents delivered to the client),
mirrored from the Biahflow snapshot, plus its ``digital_employee_status`` enum. Additive only.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0005_digital_employee'
down_revision: str | None = '0004_project_health'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'digital_employee',
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('area', sa.String(length=80), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.Enum('building', 'active', 'paused', name='digital_employee_status'), nullable=False),
        sa.Column('kpi_label', sa.String(length=80), nullable=True),
        sa.Column('kpi_value', sa.String(length=80), nullable=True),
        sa.Column('hours_saved_month', sa.Numeric(precision=10, scale=1), nullable=True),
        sa.Column('roi_month', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_digital_employee_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_digital_employee_project_id_project'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_digital_employee')),
    )
    op.create_index(op.f('ix_digital_employee_organization_id'), 'digital_employee', ['organization_id'], unique=False)
    op.create_index(op.f('ix_digital_employee_project_id'), 'digital_employee', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_digital_employee_project_id'), table_name='digital_employee')
    op.drop_index(op.f('ix_digital_employee_organization_id'), table_name='digital_employee')
    op.drop_table('digital_employee')
    op.execute('DROP TYPE IF EXISTS digital_employee_status')
