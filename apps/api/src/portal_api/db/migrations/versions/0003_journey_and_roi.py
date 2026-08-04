"""journey phases, deliverables and project ROI

Revision ID: 0003_journey_and_roi
Revises: 0002_knowledge_and_events
Create Date: 2026-08-04

Adds the transformation-journey read model in the ``portal`` schema (search_path
pinned by the engine): ``project_phase`` and ``phase_deliverable`` (mirrored from the
Biahflow snapshot), plus their ``phase_state``/``deliverable_state`` enums, and the
ROI / next-meeting projection columns on ``project``. Additive only.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0003_journey_and_roi'
down_revision: str | None = '0002_knowledge_and_events'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('project', sa.Column('roi_net', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('project', sa.Column('roi_ratio', sa.Float(), nullable=True))
    op.add_column('project', sa.Column('next_meeting_title', sa.String(length=200), nullable=True))
    op.add_column('project', sa.Column('next_meeting_date', sa.Date(), nullable=True))

    op.create_table(
        'project_phase',
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('position', sa.Integer(), server_default='0', nullable=False),
        sa.Column('state', sa.Enum('locked', 'active', 'done', name='phase_state'), nullable=False),
        sa.Column('target_date', sa.Date(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_project_phase_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_project_phase_project_id_project'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_project_phase')),
    )
    op.create_index(op.f('ix_project_phase_organization_id'), 'project_phase', ['organization_id'], unique=False)
    op.create_index(op.f('ix_project_phase_project_id'), 'project_phase', ['project_id'], unique=False)

    op.create_table(
        'phase_deliverable',
        sa.Column('phase_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('position', sa.Integer(), server_default='0', nullable=False),
        sa.Column('state', sa.Enum('pending', 'delivered', name='deliverable_state'), nullable=False),
        sa.Column('link', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_phase_deliverable_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['phase_id'], ['project_phase.id'], name=op.f('fk_phase_deliverable_phase_id_project_phase'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_phase_deliverable_project_id_project'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_phase_deliverable')),
    )
    op.create_index(op.f('ix_phase_deliverable_organization_id'), 'phase_deliverable', ['organization_id'], unique=False)
    op.create_index(op.f('ix_phase_deliverable_phase_id'), 'phase_deliverable', ['phase_id'], unique=False)
    op.create_index(op.f('ix_phase_deliverable_project_id'), 'phase_deliverable', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_phase_deliverable_project_id'), table_name='phase_deliverable')
    op.drop_index(op.f('ix_phase_deliverable_phase_id'), table_name='phase_deliverable')
    op.drop_index(op.f('ix_phase_deliverable_organization_id'), table_name='phase_deliverable')
    op.drop_table('phase_deliverable')
    op.drop_index(op.f('ix_project_phase_project_id'), table_name='project_phase')
    op.drop_index(op.f('ix_project_phase_organization_id'), table_name='project_phase')
    op.drop_table('project_phase')
    op.drop_column('project', 'next_meeting_date')
    op.drop_column('project', 'next_meeting_title')
    op.drop_column('project', 'roi_ratio')
    op.drop_column('project', 'roi_net')
    # Enum types are not dropped by drop_table; remove those this revision introduced.
    op.execute('DROP TYPE IF EXISTS deliverable_state')
    op.execute('DROP TYPE IF EXISTS phase_state')
