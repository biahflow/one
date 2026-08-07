"""o sétimo degrau do funil, agora que o Biahflow o afirma (Fase 7, RFC 001, ADR 0041)

Revision ID: 0027_artifact_accepted_step
Revises: 0026_onboarding_stuck_kind
Create Date: 2026-08-07

Um rótulo a mais em ``onboarding_step_name``, e nada além disso: nenhuma tabela,
nenhuma policy, nenhum GRANT — a ``onboarding_step`` da 0024 já os tem todos, e o
degrau novo é uma linha dela como as outras seis.

**O que muda não é o banco, é quem produz.** A 0024 nasceu com seis valores e o
enum do Python trazia a razão do sétimo faltar escrita no docstring: *"o snapshot
do Biahflow não carrega nada de artefato […] ele entra quando o outro lado o
afirmar"*. O outro lado afirmou (FDD 031 de lá), então ele entra. Declarar o valor
antes disso teria sido o painel sem escritor da ADR 0033, que é o defeito que a
ordem inteira da Fase 7 existe para não repetir.

**Por que o ``ALTER TYPE`` roda dentro da transação da migração.** A restrição do
Postgres é sobre **usar** um valor recém-adicionado antes de a transação fechar,
não sobre adicioná-lo — e nada aqui o escreve; quem escreve é o `sync_snapshot`,
muito depois do commit. É o mesmo caso da 0021 e da 0026, e o contrário da 0013,
que precisou recriar ``document_origin`` inteiro porque um índice parcial na mesma
migração usava o valor novo.

**E acrescentar o valor só no Python não bastaria**, nem seria acusado: o
``alembic check`` compara tabelas e colunas, não rótulos de enum. Sem esta linha o
primeiro snapshot com artefato aceito estouraria dentro do worker, longe da causa
— lição que a 0021 registrou, a 0026 repetiu e esta confirma pela terceira vez.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0027_artifact_accepted_step'
down_revision: str | None = '0026_onboarding_stuck_kind'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STEPS_BEFORE = (
    'first_login',
    'first_document_opened',
    'first_pending_answered',
    'first_chat_turn',
    'first_roi_seen',
    'first_deliverable_delivered',
)


def upgrade() -> None:
    op.execute(
        "ALTER TYPE onboarding_step_name ADD VALUE IF NOT EXISTS 'artifact_accepted'"
    )


def downgrade() -> None:
    # Tirar um valor de enum exige recriar o tipo, e antes disso reassentar as
    # linhas que o usam. Aqui o destino honesto é **apagá-las**, e não remapeá-las
    # para outro degrau: o carimbo é imutável por desenho (0024, nenhum papel tem
    # `UPDATE`), e reescrever "aprovou um artefato" como "fez o primeiro login"
    # seria inventar um fato — exatamente o que a imutabilidade protege. Reverter
    # esta fatia significa que o portal deixou de saber a data do ganho, e o
    # `_anchor` volta a contar do convite.
    op.execute("DELETE FROM onboarding_step WHERE step = 'artifact_accepted'")
    op.execute('ALTER TYPE onboarding_step_name RENAME TO onboarding_step_name_old')
    op.execute(
        'CREATE TYPE onboarding_step_name AS ENUM ('
        + ', '.join(f"'{step}'" for step in _STEPS_BEFORE)
        + ')'
    )
    op.execute(
        'ALTER TABLE onboarding_step ALTER COLUMN step TYPE onboarding_step_name '
        'USING step::text::onboarding_step_name'
    )
    op.execute('DROP TYPE onboarding_step_name_old')
