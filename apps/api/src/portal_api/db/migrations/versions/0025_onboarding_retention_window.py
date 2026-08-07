"""prazo de retenção para o funil de onboarding (Fase 7, RFC 001, ADR 0039)

Revision ID: 0025_onboarding_retention_window
Revises: 0024_onboarding_step
Create Date: 2026-08-07

Uma coluna nulável em ``organization_retention_policy``, na forma das outras três.
Nulo continua significando "usa o padrão de ``config.py``" e nunca "guarda para
sempre" — a mesma regra da 0015.

Separada da 0024 de propósito: aquela cria a tabela do funil e esta lhe dá prazo.
São decisões diferentes, e quem precisar reverter só o prazo não deveria ter de
derrubar o funil junto.

O padrão (``retention_onboarding_days``, 1095 dias) é o mais longo dos quatro, e
o motivo está no ``config.py``: o *time-to-first-value* só significa alguma coisa
comparado com o de coortes anteriores, e uma janela curta apagaria a comparação
junto com o dado.

Nenhum GRANT nem policy novos: a tabela já tem os dois desde a 0015, e a coluna
nova não muda quem a escreve — continua sendo ``portal_admin`` pela rota da
ADR 0027.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0025_onboarding_retention_window'
down_revision: str | None = '0024_onboarding_step'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'organization_retention_policy',
        sa.Column('onboarding_days', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('organization_retention_policy', 'onboarding_days')
