"""o degrau da FDE e a decisão da fase (Language Map v1.1, ADR 0081)

Revision ID: 0039_journey_canonical_stage
Revises: 0038_notification_link_rename
Create Date: 2026-08-28

Três colunas em ``project_phase``, dois tipos novos, e **nenhuma policy, RLS ou GRANT**:
a tabela já tem os três desde a ``0003_journey_and_roi``, e quem escreve aqui é o sync
sob ``portal_system``, como em toda coluna desta tabela. A migração é puramente aditiva
(ADR 0066) — o ``upgrade()`` não apaga dado.

Até aqui a jornada atravessava a fronteira com **nome e estado**, e o degrau da
metodologia FDE — DISCOVER · PRIORITIZE · FEASIBILITY · PROVE · SCALE · OPTIMIZE — não
tinha coluna. O Biahflow já carrega ``canonical_stage`` e ``gate_outcome`` no modelo
dele; nenhum dos dois entrava na projeção, então o cliente lia o **rótulo** da fase
("Prove", "Descoberta", "Activation") sem nada que dissesse a qual degrau ela pertence,
e a decisão que fecha um gate não existia em lugar nenhum deste lado.

**As duas primeiras colunas são nullable, e por motivos diferentes** — é o que faz
serem duas e não uma:

- ``canonical_stage`` é ``NULL`` quando a fase **não tem equivalente FDE**. A origem
  manda ``""`` nesse caso, e o exemplo é real: uma fase ``Activation``, operacional da
  Biahflow. Isso é legítimo por desenho e não falta de dado. O caminho proibido é o
  inverso do de sempre: **não se deriva o degrau do nome da fase**. Um casador por
  rótulo carimbaria ``prove`` numa fase chamada "Prova de conceito" que a metodologia
  não reconhece, e o erro sairia com a autoridade de um enum.
- ``gate_decision`` é ``NULL`` quando **ninguém decidiu ainda**.

``requires_gate`` é ``NOT NULL`` com ``server_default false``, e é ele que separa os
dois sentidos do ``NULL`` acima: sem ele, "fase que não tem gate" e "gate ainda por
decidir" seriam indistinguíveis, e a tela teria de escolher entre calar sobre as duas
ou afirmar uma espera sobre fase que nunca terá decisão. O default é ``false`` porque
um Biahflow anterior a esta fatia não manda a chave, e a leitura conservadora da
ausência é a que faz a tela calar.

**Por que os tipos nascem por ``CREATE TYPE`` explícito**: ``op.add_column`` não emite
``CREATE TYPE``, como a ``0006`` já registrou ao acrescentar ``pending_origin``.

Sem índice nas três: são lidas sempre pelas fases do projeto que a projeção acabou de
carregar por ``project_id``, e nenhuma consulta filtra ou ordena por elas — um índice
que ninguém usa é custo de escrita a cada webhook (mesmo argumento da ``0031``).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0039_journey_canonical_stage'
down_revision: str | None = '0038_notification_link_rename'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Os seis degraus da tabela §4 do Language Map, na ordem em que ela os escreve.
_CANONICAL_STAGES = (
    'discover',
    'prioritize',
    'feasibility',
    'prove',
    'scale',
    'optimize',
)

#: A decisão de gate da D7 — ``GateDecision``, nunca ``GateOutcome``.
_GATE_DECISIONS = ('go', 'conditional_go', 'redesign', 'no_go')


def upgrade() -> None:
    # ``op.add_column`` não emite CREATE TYPE (ver ``0006_portal_sync_fields``).
    canonical_stage = postgresql.ENUM(*_CANONICAL_STAGES, name='canonical_stage')
    canonical_stage.create(op.get_bind(), checkfirst=True)
    gate_decision = postgresql.ENUM(*_GATE_DECISIONS, name='gate_decision')
    gate_decision.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'project_phase',
        sa.Column(
            'canonical_stage',
            postgresql.ENUM(*_CANONICAL_STAGES, name='canonical_stage', create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        'project_phase',
        sa.Column(
            'gate_decision',
            postgresql.ENUM(*_GATE_DECISIONS, name='gate_decision', create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        'project_phase',
        sa.Column(
            'requires_gate',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('project_phase', 'requires_gate')
    op.drop_column('project_phase', 'gate_decision')
    op.drop_column('project_phase', 'canonical_stage')
    op.execute('DROP TYPE IF EXISTS gate_decision')
    op.execute('DROP TYPE IF EXISTS canonical_stage')
