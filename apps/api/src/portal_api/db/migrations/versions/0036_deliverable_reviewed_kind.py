"""a decisão do cliente vira aviso do time (Fase 7, FDD 027, ADR 0077)

Revision ID: 0036_deliverable_reviewed_kind
Revises: 0035_deliverable_acceptance
Create Date: 2026-08-27

Um rótulo a mais em ``notification_kind``, na forma exata da 0026 e da 0030.

**A audiência é só o time**, como as duas anteriores, e por um motivo que soma os
dois: o cliente **acabou de tomar** a decisão — devolvê-la a ele seria contar-lhe
o que ele mesmo decidiu — e quem precisa agir é a operação. A entrada em
``notifications.AUDIENCE`` é obrigatória e vai no mesmo commit: o
``.get(kind, _CLIENT_ONLY)`` de ``recipients`` tem o cliente como padrão, então
esquecê-la mandaria ao cliente o aviso do próprio aceite.

**Uma espécie e não duas**, com a decisão no título e no ``dedupe_key``: quem lê
a fila precisa de "o cliente revisou" com os dois desfechos juntos.

**Por que o ``ALTER TYPE`` roda dentro da transação**: a restrição do Postgres é
sobre *usar* o valor novo antes do commit, não sobre adicioná-lo, e nada aqui o
escreve — quem escreve é a task pós-commit da rota de aceite, muito depois. Mesmo
caso da 0021, da 0026 e da 0030.

**E acrescentá-lo só no Python não bastaria, nem seria acusado**: o ``alembic
check`` compara tabelas e colunas, não rótulos de enum. Sem esta linha o primeiro
aceite gravaria e o aviso estouraria no worker, longe da causa.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0036_deliverable_reviewed_kind'
down_revision: str | None = '0035_deliverable_acceptance'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS_BEFORE = (
    'milestone_done',
    'phase_advanced',
    'deliverable_delivered',
    'document_added',
    'meeting_scheduled',
    'transcript_ready',
    'pending_opened',
    'pending_resolved',
    'pending_commented',
    'project_status_changed',
    'onboarding_stuck',
    'whatsapp_reply',
)


def upgrade() -> None:
    op.execute(
        "ALTER TYPE notification_kind ADD VALUE IF NOT EXISTS 'deliverable_reviewed'"
    )


def downgrade() -> None:
    # Mesmo argumento da 0026 e da 0030: não há rótulo honesto para onde
    # reassentar estas linhas. Um aceite do cliente reescrito como "entregável
    # liberado" seria um fato falso na caixa de alguém, e com a agravante de
    # inverter quem decidiu o quê. O aviso sai — a decisão continua gravada em
    # `deliverable_acceptance`, que é a fonte da verdade (ADR 0077).
    op.execute("DELETE FROM notification WHERE kind = 'deliverable_reviewed'")
    op.execute('ALTER TYPE notification_kind RENAME TO notification_kind_old')
    op.execute(
        'CREATE TYPE notification_kind AS ENUM ('
        + ', '.join(f"'{kind}'" for kind in _KINDS_BEFORE)
        + ')'
    )
    op.execute(
        'ALTER TABLE notification ALTER COLUMN kind TYPE notification_kind '
        'USING kind::text::notification_kind'
    )
    op.execute('DROP TYPE notification_kind_old')
