"""sync fields for documents, meetings and pendings mirrored from Biahflow

Revision ID: 0006_portal_sync_fields
Revises: 0005_digital_employee
Create Date: 2026-08-04

Additive columns so the read model can carry the ``documents``, ``meetings`` and
``pendencias`` blocks of the Biahflow snapshot (portal_biahflow ADR 0005).

``pending_item.origin`` is the important one: the sync replaces only the pendings
mirrored from Biahflow, so the ones the chat opens when evidence is missing (ADR 0007)
survive. Existing rows were all created by the chat, hence the ``portal`` default.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0006_portal_sync_fields'
down_revision: str | None = '0005_digital_employee'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``op.add_column`` does not emit CREATE TYPE, so the enum is created explicitly first.
    pending_origin = postgresql.ENUM('biahflow', 'portal', name='pending_origin')
    pending_origin.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'pending_item',
        sa.Column(
            'origin',
            postgresql.ENUM('biahflow', 'portal', name='pending_origin', create_type=False),
            nullable=False,
            server_default='portal',
        ),
    )
    op.add_column('pending_item', sa.Column('external_ref', sa.String(length=80), nullable=True))
    op.create_index(
        op.f('ix_pending_item_external_ref'), 'pending_item', ['external_ref'], unique=False
    )

    op.add_column('document', sa.Column('link', sa.Text(), nullable=True))
    op.add_column('document', sa.Column('author_label', sa.String(length=160), nullable=True))

    op.add_column('meeting', sa.Column('status', sa.String(length=40), nullable=True))
    op.add_column(
        'meeting',
        sa.Column('has_transcript', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('meeting', 'has_transcript')
    op.drop_column('meeting', 'status')

    op.drop_column('document', 'author_label')
    op.drop_column('document', 'link')

    op.drop_index(op.f('ix_pending_item_external_ref'), table_name='pending_item')
    op.drop_column('pending_item', 'external_ref')
    op.drop_column('pending_item', 'origin')
    op.execute('DROP TYPE IF EXISTS pending_origin')
