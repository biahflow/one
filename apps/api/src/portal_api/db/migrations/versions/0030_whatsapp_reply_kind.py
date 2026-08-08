"""a resposta do cliente pelo canal vira aviso do time (Fase 7, FDD 021, ADR 0043)

Revision ID: 0030_whatsapp_reply_kind
Revises: 0029_whatsapp_channel
Create Date: 2026-08-07

Um rótulo a mais em ``notification_kind``, na forma exata da 0026 e pela mesma
razão de **ausência**: a resposta que chega pelo webhook precisa de destino e de
memória de idempotência, e as duas coisas a ``notification`` já tem. O destino é o
sino do time interno; a memória é o ``dedupe_key`` com
``uq_notification_user_dedupe_key`` e ``ON CONFLICT DO NOTHING``, que faz a
reentrega do mesmo evento do fornecedor não virar um segundo aviso. Uma tabela
``whatsapp_inbound`` custaria policy, purga e uma quarta exclusão à mão no
apagamento, tudo para guardar um identificador que outra coluna já guarda.

**A audiência é só o time**, como o ``onboarding_stuck``: o cliente acabou de
escrever a mensagem — avisá-lo dela seria contar-lhe o que ele mesmo digitou, que
é o ruído que a ADR 0012 nomeou ao decidir quem recebe o quê.

**Por que o ``ALTER TYPE`` roda dentro da transação**: a restrição do Postgres é
sobre *usar* o valor novo antes do commit, não sobre adicioná-lo, e nada aqui o
escreve — quem escreve é a rota do webhook, muito depois. Mesmo caso da 0021 e da
0026.

**E acrescentá-lo só no Python não bastaria, nem seria acusado**: o ``alembic
check`` compara tabelas e colunas, não rótulos de enum. Sem esta linha a primeira
resposta do cliente estouraria o ``INSERT`` na rota, longe da causa.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0030_whatsapp_reply_kind'
down_revision: str | None = '0029_whatsapp_channel'
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
)


def upgrade() -> None:
    op.execute(
        "ALTER TYPE notification_kind ADD VALUE IF NOT EXISTS 'whatsapp_reply'"
    )


def downgrade() -> None:
    # Mesmo argumento da 0026: não há rótulo honesto para onde reassentar estas
    # linhas. Uma resposta de cliente reescrita como "pendência aberta" seria um
    # fato falso na caixa de alguém — e aqui seria pior, porque o texto é do
    # cliente. O aviso sai, que é o que reverter esta fatia significa.
    op.execute("DELETE FROM notification WHERE kind = 'whatsapp_reply'")
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
