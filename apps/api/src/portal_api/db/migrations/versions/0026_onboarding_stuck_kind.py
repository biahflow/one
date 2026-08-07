"""aviso de cliente travado no funil (Fase 7, RFC 001, ADR 0040)

Revision ID: 0026_onboarding_stuck_kind
Revises: 0025_onboarding_retention_window
Create Date: 2026-08-07

Um rótulo a mais em ``notification_kind``, e nada além disso: nenhuma tabela,
nenhuma policy, nenhum GRANT.

**A ausência é a decisão.** O alerta de cliente travado precisa lembrar que já
avisou, e a memória escolhida foi o ``dedupe_key`` que a ``notification`` já tem,
com ``uq_notification_user_dedupe_key`` e ``ON CONFLICT DO NOTHING`` — ``fan_out``
devolve só os ids que nasceram, e lista vazia significa "o sino já tem". A
alternativa era uma tabela ``onboarding_alert``, que custaria policy (o meta-teste
de isolamento cobra), predicado de purga e uma **terceira** exclusão à mão em
``run_erasure``, tudo para guardar um booleano. A tabela do funil não aceita
``UPDATE`` de papel nenhum (0024), nem do sistema, então marcar o próprio degrau
como "já alertado" nunca foi opção.

**Por que o ``ALTER TYPE`` roda dentro da transação da migração.** A restrição do
Postgres é sobre **usar** um valor recém-adicionado antes de a transação fechar,
não sobre adicioná-lo — e nada aqui o escreve; quem escreve é o worker, muito
depois do commit. É o mesmo caso da 0021, e o contrário da 0013, que precisou
recriar ``document_origin`` inteiro porque um índice parcial na mesma migração
usava o valor novo.

**E acrescentar o valor só no Python não bastaria**, nem seria acusado: o
``alembic check`` compara tabelas e colunas, não rótulos de enum. Sem esta linha o
primeiro alerta gravaria e o ``INSERT`` estouraria no worker, longe da causa — o
que a 0021 já tinha registrado e vale repetir, porque foi essa migração que
provou que a lição continua valendo.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0026_onboarding_stuck_kind'
down_revision: str | None = '0025_onboarding_retention_window'
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
)


def upgrade() -> None:
    op.execute(
        "ALTER TYPE notification_kind ADD VALUE IF NOT EXISTS 'onboarding_stuck'"
    )


def downgrade() -> None:
    # Tirar um valor de enum exige recriar o tipo, e antes disso reassentar as
    # linhas que o usam — senão o `USING` falha na primeira. Aqui, porém, o destino
    # honesto não é outro rótulo: um aviso de cliente travado reescrito como
    # "pendência aberta" seria um fato falso na caixa de alguém. O aviso **sai**,
    # que é o que reverter esta fatia significa.
    op.execute("DELETE FROM notification WHERE kind = 'onboarding_stuck'")
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
