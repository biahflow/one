"""o frescor e a versão que o snapshot nunca teve (Fase 7, ADR 0076)

Revision ID: 0031_projection_freshness
Revises: 0030_whatsapp_reply_kind
Create Date: 2026-08-27

Três colunas, todas nullable, e nenhum GRANT nem policy novos — ``project`` já tem os
dois, e quem escreve aqui é o sync sob ``portal_system``, como em toda coluna desta
tabela. A migração é puramente aditiva (ADR 0066): o ``upgrade()`` não apaga dado.

Ela cita a **ADR 0076** porque a mudança é de **contrato de integração** (regra 4 do
``AGENTS.md``): o snapshot do Biahflow passa a ser um contrato de projeção versionado,
com duas grandezas novas no envelope, e não apenas mais um campo denormalizado.

O que as colunas consertam é uma lacuna medida (dossiê da Issue #62): o portal não tinha
**nenhuma** noção de frescor. Não havia ``observed_at`` nem ``synced_at``, a tela mostrava
``source`` fixo em ``"live"``, e a ADR 0026 já havia **removido** um "Atualizado há 2 dias"
justamente por ser frescor inventado. Se o Biahflow parasse de sincronizar, o cliente veria
o último estado como se fosse o de agora, sem indicação nenhuma. E não havia defesa contra
snapshot fora de ordem: o sync é idempotente por **substituição** (apaga e reinsere fases,
marcos, decisões e pendências), então um webhook reentregue ou atrasado dispara um fetch, e
o fetch de um estado mais velho era aplicado por cima do mais novo sem que nada percebesse.

**Por que três colunas e não uma.** ``observed_at`` é a hora em que a **origem observou** o
estado; ``synced_at`` é a hora em que o **portal copiou**. São grandezas diferentes, e
colapsá-las faria a segunda passar pela primeira — a falsa precisão que ``results.py``
recusa. O fallback declarado na ADR 0076 é exatamente isto: se o Biahflow ainda não carimba
``observed_at``, o portal grava ``synced_at = now()`` e a projeção **rotula como cópia**
("sincronizado há X", nunca "observado há X"). Uma resposta pior à mesma pergunta, dita
honestamente, no precedente do embedder offline e do ``scan_state=skipped``.

``projection_version`` é o inteiro monotônico por projeto que a origem incrementa a cada
mudança de estado projetável. Existe separado da hora porque hora não basta: dois
``observed_at`` podem empatar, e o relógio da origem pode regredir. É o que torna a
reconciliação determinística.

``nullable`` nas três, e a nulidade é significativa: toda linha existente nasce sem elas, e
um Biahflow anterior a esta fatia simplesmente não manda os campos. Ausência é **ausência de
afirmação**, nunca "versão zero" — que faria a reconciliação ler o desconhecido como o mais
velho possível e recusar snapshots legítimos. ``NOT NULL`` também quebraria o ``upgrade``
sobre os dados que já estão lá.

Sem índice: as três são lidas sempre pelo projeto já em mãos (o ``sync_snapshot`` acabou de
resolver a linha por ``organization_id`` + ``slug``, e o dashboard projeta do próprio
``Project``). Nenhuma consulta filtra ou ordena por elas, e um índice que ninguém usa é
custo de escrita a cada webhook.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0031_projection_freshness'
down_revision: str | None = '0030_whatsapp_reply_kind'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'project',
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'project',
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'project',
        sa.Column('projection_version', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('project', 'projection_version')
    op.drop_column('project', 'synced_at')
    op.drop_column('project', 'observed_at')
