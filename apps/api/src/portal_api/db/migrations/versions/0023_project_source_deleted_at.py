"""o projeto apagado no Biahflow, e a coluna que só o webhook preenche (Fase 6, ADR 0037)

Revision ID: 0023_project_source_deleted_at
Revises: 0022_project_archived_at
Create Date: 2026-08-07

Uma coluna, nullable, e nenhum GRANT nem policy novos — ``project`` já tem os dois,
e quem escreve aqui é o webhook sob ``portal_system``, como em toda coluna desta
tabela.

**Separada de ``archived_at``**, pelo argumento da migração 0022 levado um passo
adiante. Lá as duas perguntas eram "qual o andamento" e "acabou"; aqui são "acabou"
e "ainda existe na fonte". Arquivamento é reversível e vem **no snapshot** —
``sync_snapshot`` o atribui incondicionalmente a cada sincronização, porque ``None``
significa restaurado. Exclusão é terminal e chega **só pelo webhook**, porque depois
dela não há snapshot nenhum: a rota de leitura do Biahflow responde 404 para um id
que não existe mais. Uma coluna só faria o sync apagar o fato no dia em que um
snapshot voltasse a existir, e um id reusado é problema diferente deste.

O que a coluna conserta: até aqui, apagar um projeto no Biahflow não emitia nada (os
receivers de lá eram todos ``post_save``), então o portal seguia mostrando ao cliente
um projeto morto **como ativo**, para sempre — e mesmo com o evento, o 404 do
snapshot não distingue "foi apagado" de "id de outra base", que é a ADR 0036 um nível
acima. Agora o Biahflow declara ``event: "deleted"`` e este lado carimba o fato.

O portal **não apaga nada** ao receber o aviso, e é deliberado: documento é a
evidência de uma citação já dada (ADR 0017), e apagar tenant é decisão de pessoa, pelo
pedido de apagamento que o worker executa — nunca por uma rota HTTP.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0023_project_source_deleted_at'
down_revision: str | None = '0022_project_archived_at'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'project',
        sa.Column('source_deleted_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('project', 'source_deleted_at')
