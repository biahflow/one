"""a decisão ancorada à fase que ela destravou (ADR 0088)

Revision ID: 0042_decision_phase_anchor
Revises: 0041_discovery_surface
Create Date: 2026-09-02

Uma coluna em ``decision``, e **nenhuma policy, RLS ou GRANT**: a tabela tem RLS desde a
``0003_journey_and_roi``, o papel de requisição já tem ``SELECT`` nela e quem escreve
aqui é o sync sob ``portal_system``, como em toda coluna desta tabela. A migração é
puramente aditiva (ADR 0066) — o ``upgrade()`` não apaga dado.

Até aqui a decisão atravessava a fronteira com título, racional, data, dono e a reunião
de onde saiu, e **não dizia que fase destravou**. O Pulse carimba ``phase_ref`` por
decisão desde 31/08/2026 (ADR 0057 e FDD 032 de lá); deste lado o campo chegava no
envelope e era descartado na ingestão, e o cliente lia a decisão numa lista solta sem
nada que a ligasse ao degrau da jornada que ela abriu.

**A coluna é ``nullable``, e a nulidade é significativa** — é o mesmo argumento do
``canonical_stage`` da ``0039``, e não o do ``requires_gate``: o produtor manda ``null``
no legado de propósito, "a lacuna é declarada em vez de mascarada por heurística". O
caminho proibido é o de sempre e aqui foi **recusado em dois gates humanos
independentes** (o nosso em 27/08/2026 e o deles na ADR 0057): não se deriva a fase de
``decided_on`` × janela da fase. Um casador por data carimbaria uma fase numa decisão
que ninguém ancorou, e o erro sairia com a autoridade de uma chave estrangeira.

**``ON DELETE SET NULL``, como o ``meeting_id`` que ela espelha.** ``sync_snapshot``
apaga e recria ``project_phase`` a cada webhook, então o vínculo só se sustenta se for
refeito na mesma transação — e no dia em que a origem remover a fase, o fato da decisão
sobrevive e volta a declarar a lacuna, que é exatamente o que o outro lado decidiu fazer
com o FK dele.

Com índice, ao contrário das três colunas da ``0039``: a leitura do dashboard junta
``decision`` a ``project_phase`` por esta coluna, que é o oposto de "nenhuma consulta
filtra ou ordena por elas". É o índice que o ``meeting_id`` já tem, pelo mesmo motivo.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0042_decision_phase_anchor'
down_revision: str | None = '0041_discovery_surface'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'decision',
        sa.Column('project_phase_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f('ix_decision_project_phase_id'), 'decision', ['project_phase_id'], unique=False
    )
    op.create_foreign_key(
        'fk_decision_project_phase_id_project_phase',
        'decision',
        'project_phase',
        ['project_phase_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_decision_project_phase_id_project_phase', 'decision', type_='foreignkey'
    )
    op.drop_index(op.f('ix_decision_project_phase_id'), table_name='decision')
    op.drop_column('decision', 'project_phase_id')
