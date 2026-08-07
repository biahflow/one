"""os degraus de valor do cliente, carimbados e imutáveis (Fase 7, RFC 001, ADR 0039)

Revision ID: 0024_onboarding_step
Revises: 0023_project_source_deleted_at
Create Date: 2026-08-07

Uma tabela, escopada por **organização** — a pergunta da RFC 001 é sobre a relação
do cliente com o produto, e um cliente pode ter mais de um projeto. É a forma de
``organization_retention_policy`` (0015): ``TenantMixin`` sem ``project_id``.

**``portal_app`` não recebe policy nenhuma**, e é a decisão que carrega a tabela.
O papel de requisição herda o ``SELECT`` das default privileges do ``roles.sql`` e
lê zero linhas, porque nenhuma policy é ``TO portal_app`` — a mesma forma de
``agent_api_key`` (0010) e ``project_drive_connection`` (0013). Escrita ele não
tem de jeito nenhum: **um caminho de requisição capaz de escrever o próprio degrau
é um caminho capaz de falsear o próprio engajamento**. Quem carimba é o sistema,
em transação própria, no precedente do ``chat_limit.consume`` (0017).

**Ninguém recebe ``UPDATE``**, nem o sistema. O carimbo é imutável por desenho: a
``UniqueConstraint (organization_id, step)`` mais ``ON CONFLICT DO NOTHING`` fazem
a segunda ocorrência não ter efeito, e sem GRANT de ``UPDATE`` não há caminho para
reescrever a data. Primeira vez é primeira vez — é a única métrica que interessa,
o *time-to-first-value*, e reescrevê-la a destruiria. É o mesmo argumento que
impede reescrever o que uma chamada de IA custou (0018) e as citações que uma
resposta mostrou (0015).

``portal_admin`` recebe ``SELECT`` porque a tela de cliente travado é o passo 3 da
RFC e virá; ``DELETE`` porque o apagamento por decisão precisa alcançar estes
degraus. E aqui há uma armadilha que esta migração não resolve sozinha: o funil é
escopado por organização e a linha ``organization`` **fica** no apagamento (0015),
então o CASCADE não o alcança. Quem o apaga é o ``retention._erase``, à mão, ao
lado da ``membership``.

O ``reached_at`` é separado do ``created_at`` do mixin porque quem carimba pode não
ser quem observou: o degrau do entregável chega pelo sync, e a data que interessa é
a do fato.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0024_onboarding_step'
down_revision: str | None = '0023_project_source_deleted_at'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Nenhuma policy ``TO portal_app``. Ver o docstring: a regra não é sobre ele.
ADMIN_POLICIES = """
CREATE POLICY onboarding_step_admin_read ON onboarding_step
  FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());

CREATE POLICY onboarding_step_admin_delete ON onboarding_step
  FOR DELETE TO portal_admin
  USING (organization_id = portal.current_admin_org());
"""

ADMIN_GRANTS = """
GRANT SELECT, DELETE ON portal.onboarding_step TO portal_admin;
"""

SYSTEM_GRANTS = """
GRANT SELECT, INSERT, DELETE ON portal.onboarding_step TO portal_system;
"""


def _when_role_exists(role: str, *statements: str) -> str:
    """Roda o SQL só onde ``roles.sql`` criou o papel — mesmo formato da 0010/0015/0017/0018."""
    body = "\n".join(statements)
    return f"""
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
            RAISE NOTICE '{role} is absent; skipping (run roles.sql)';
            RETURN;
          END IF;
          EXECUTE $sql${body}$sql$;
        END
        $do$;
    """


def upgrade() -> None:
    op.create_table(
        'onboarding_step',
        sa.Column(
            'step',
            sa.Enum(
                'first_login',
                'first_document_opened',
                'first_pending_answered',
                'first_chat_turn',
                'first_roi_seen',
                'first_deliverable_delivered',
                name='onboarding_step_name',
            ),
            nullable=False,
        ),
        sa.Column('reached_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'step', name='uq_onboarding_step_org_step'),
    )
    op.create_index(
        op.f('ix_onboarding_step_organization_id'), 'onboarding_step', ['organization_id']
    )

    op.execute('ALTER TABLE onboarding_step ENABLE ROW LEVEL SECURITY')
    op.execute(_when_role_exists('portal_admin', ADMIN_POLICIES, ADMIN_GRANTS))
    op.execute(_when_role_exists('portal_system', SYSTEM_GRANTS))


def downgrade() -> None:
    op.execute(
        _when_role_exists('portal_system', 'REVOKE ALL ON portal.onboarding_step FROM portal_system;')
    )
    op.execute(
        _when_role_exists('portal_admin', 'REVOKE ALL ON portal.onboarding_step FROM portal_admin;')
    )
    op.drop_index(op.f('ix_onboarding_step_organization_id'), table_name='onboarding_step')
    op.drop_table('onboarding_step')
    op.execute('DROP TYPE IF EXISTS onboarding_step_name')
