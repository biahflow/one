"""a identidade do entregável que o sync não podia apagar (Fase 7, FDD 027, ADR 0077)

Revision ID: 0034_deliverable_external_ref
Revises: 0030_whatsapp_reply_kind
Create Date: 2026-08-27

Uma coluna, nullable, com índice — e nenhum GRANT nem policy novos, porque
``phase_deliverable`` já tem os dois e quem escreve aqui continua sendo o sync
sob ``portal_system``, como em toda coluna desta tabela.

**Por que ela precisa existir antes de qualquer aceite.** ``sync_snapshot``
começa a jornada com ``delete(PhaseDeliverable)`` e recria as linhas: o uuid de
hoje não é o de amanhã. É a armadilha que ``notifications.ITEM_ANCHOR`` já
documentava para o link do aviso — "um link por uuid nasceria apontando para uma
linha que vai deixar de existir" — e que a ADR 0077 mede de novo para o aceite,
onde o custo é maior: uma chave estrangeira do registro de aceite para o uuid do
read model seria destruída no webhook seguinte, levando junto a decisão do
cliente. O aceite ancora no id **da origem**, no precedente de
``PendingItem.external_ref`` (migração 0002) e de ``Document.external_id``.

``nullable`` e sem ``server_default``, pelo argumento do ``archived_at`` da 0022:
as linhas existentes não têm o valor e não há como inventá-lo aqui — o snapshot
seguinte as recria já com ele, porque o Biahflow manda ``id`` em cada entregável
desde a FDD 016 de lá. Preencher a coluna nesta migração exigiria adivinhar a
correspondência por nome, que é exatamente a identidade instável que a coluna
existe para substituir.

``String(80)`` e índice não-único, iguais aos do ``PendingItem.external_ref``.
**Único seria errado**, e vale o registro: a unicidade que faria sentido é por
``(project_id, external_ref)``, e nem essa é afirmável enquanto o sync escreve
por ``delete`` + ``insert`` numa transação em que a linha velha e a nova
coexistem. O escopo do aceite é o tenant, e quem o garante é a policy da tabela
de aceite — não um índice aqui.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0034_deliverable_external_ref'
down_revision: str | None = '0030_whatsapp_reply_kind'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'phase_deliverable',
        sa.Column('external_ref', sa.String(length=80), nullable=True),
    )
    op.create_index(
        op.f('ix_phase_deliverable_external_ref'),
        'phase_deliverable',
        ['external_ref'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_phase_deliverable_external_ref'), table_name='phase_deliverable'
    )
    op.drop_column('phase_deliverable', 'external_ref')
