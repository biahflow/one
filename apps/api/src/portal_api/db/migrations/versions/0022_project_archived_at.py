"""o projeto encerrado no Biahflow, e a coluna que o portal não tinha (Fase 6, ADR 0036)

Revision ID: 0022_project_archived_at
Revises: 0021_pending_item_comment
Create Date: 2026-08-06

Uma coluna, nullable, e nenhum GRANT nem policy novos — ``project`` já tem os
dois, e quem escreve aqui é o sync sob ``portal_system``, como em toda coluna
desta tabela.

O que merece registro é por que ela existe **separada de** ``status``.

``ProjectStatus`` descreve o andamento: ``discovery``, ``in_implementation``,
``live``, ``paused``. Arquivamento é ortogonal a isso — um projeto encerrado
tinha um andamento no momento em que acabou, e é essa a informação que
``status`` carrega. Acrescentar ``archived`` ao enum faria "pausado" e
"encerrado" disputarem a mesma coluna, e o segundo apagaria o primeiro: depois
de restaurar, ninguém saberia dizer se o projeto estava pausado ou em
implementação quando foi arquivado. Duas perguntas, duas colunas.

O que a coluna conserta é um travamento medido em 06/08/2026. Arquivar um
projeto no Biahflow emite webhook (lá o ``archive()`` é um ``save()``), mas a
rota de snapshot filtrava ``archived_at__isnull=True`` — então o portal vinha
buscar o estado novo e levava **404**, que ele não tem como distinguir de "este
id nunca existiu". O webhook respondia 500, nada era gravado, e a tela do
cliente seguia mostrando como ativo um projeto que a fonte da verdade havia
encerrado. Todo webhook seguinte batia no mesmo 404, então a divergência durava
o quanto durasse o arquivamento.

``nullable`` e não ``server_default``: ``NULL`` é "ativo", que é o estado de
todo projeto existente, e é para ``NULL`` que o sync devolve a coluna quando
alguém restaura o projeto pelo Biahflow — a interface de lá arquiva e
desarquiva **por item** (``?archived=1`` + ``POST /unarchive/``), então um campo
que só soubesse ir deixaria projetos eternamente marcados como encerrados
depois de um arquivamento desfeito.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0022_project_archived_at'
down_revision: str | None = '0021_pending_item_comment'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'project',
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('project', 'archived_at')
