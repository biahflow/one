"""prazo dos dados e pedido de apagamento (Fase 5, ADR 0017)

Revision ID: 0015_retention_and_erasure
Revises: 0014_document_scan
Create Date: 2026-08-05

Duas tabelas, ambas por organização e nenhuma por projeto — as primeiras assim no
repositório. "Por quanto tempo os dados ficam" e "apague tudo" não são perguntas
que se façam projeto a projeto, e modelá-las por projeto obrigaria a resposta a
ser montada por soma, com o risco de dois projetos da mesma organização
discordarem sobre o prazo dela.

**Por que não colunas em ``organization``.** Aquela linha vem do snapshot do
Biahflow e o ``sync_snapshot`` faz upsert nela; um prazo guardado ali seria
sobrescrito pelo primeiro webhook que não soubesse dele. É a lição que já criou
``document.origin`` e ``pending_item.origin``.

**As policies são ``TO portal_admin``, e ``portal_app`` não ganha nenhuma.** Mesma
forma de ``agent_api_key`` e de ``project_drive_connection`` (0010/0013): o papel
do caminho de requisição herda o SELECT do ``ALTER DEFAULT PRIVILEGES`` do
``roles.sql``, mas nenhuma policy se aplica a ele, então a leitura volta **zero
linhas**. Não é uma permissão faltando — é a regra não ser sobre ele. Aqui isso
importa por um motivo específico: o cliente não deve poder ler a data em que os
dados dele serão apagados numa tela que não foi feita para dizer isso.

Quem executa a poda e o expurgo é ``portal_system``, que passa por cima das
policies por desenho — e é justamente por isso que a rota HTTP não apaga nada
(ADR 0015: "quando o expurgo chegar, não será o caminho de requisição a fazê-lo").
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0015_retention_and_erasure'
down_revision: str | None = '0014_document_scan'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ADMIN_POLICIES = """
CREATE POLICY organization_retention_policy_admin_read ON organization_retention_policy
  FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());

CREATE POLICY organization_retention_policy_admin_insert ON organization_retention_policy
  FOR INSERT TO portal_admin
  WITH CHECK (organization_id = portal.current_admin_org());

CREATE POLICY organization_retention_policy_admin_update ON organization_retention_policy
  FOR UPDATE TO portal_admin
  USING (organization_id = portal.current_admin_org())
  WITH CHECK (organization_id = portal.current_admin_org());

CREATE POLICY data_erasure_request_admin_read ON data_erasure_request
  FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());

CREATE POLICY data_erasure_request_admin_insert ON data_erasure_request
  FOR INSERT TO portal_admin
  WITH CHECK (organization_id = portal.current_admin_org());

GRANT SELECT, INSERT, UPDATE ON portal.organization_retention_policy TO portal_admin;
-- Sem UPDATE nem DELETE no pedido: quem o cumpre é o worker sob `portal_system`,
-- e quem pediu não deve poder reescrever o registro do que foi pedido. É a mesma
-- razão pela qual `notification` só aceita UPDATE de coluna (ADR 0012) — o
-- registro do que aconteceu não pertence a quem o provocou.
GRANT SELECT, INSERT ON portal.data_erasure_request TO portal_admin;
"""


def _when_role_exists(role: str, *statements: str) -> str:
    """Roda o SQL só onde ``roles.sql`` criou o papel — mesmo formato da 0010/0011/0013."""
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
        'organization_retention_policy',
        sa.Column('notification_days', sa.Integer(), nullable=True),
        sa.Column('agent_event_days', sa.Integer(), nullable=True),
        sa.Column('conversation_days', sa.Integer(), nullable=True),
        sa.Column('updated_by_user_id', sa.UUID(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_organization_retention_policy_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['user.id'], name=op.f('fk_organization_retention_policy_updated_by_user_id_user'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_organization_retention_policy')),
        sa.UniqueConstraint('organization_id', name='uq_organization_retention_policy_organization_id'),
    )
    op.create_index(op.f('ix_organization_retention_policy_organization_id'), 'organization_retention_policy', ['organization_id'], unique=False)

    erasure_state = postgresql.ENUM(
        'pending', 'running', 'completed', 'failed', name='erasure_state'
    )
    erasure_state.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'data_erasure_request',
        sa.Column(
            'state',
            postgresql.ENUM(
                'pending', 'running', 'completed', 'failed',
                name='erasure_state',
                create_type=False,
            ),
            server_default='pending',
            nullable=False,
        ),
        sa.Column('requested_by_user_id', sa.UUID(), nullable=True),
        sa.Column('requested_reason', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('removed', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_data_erasure_request_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requested_by_user_id'], ['user.id'], name=op.f('fk_data_erasure_request_requested_by_user_id_user'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_data_erasure_request')),
    )
    op.create_index(op.f('ix_data_erasure_request_organization_id'), 'data_erasure_request', ['organization_id'], unique=False)

    op.execute('ALTER TABLE organization_retention_policy ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE data_erasure_request ENABLE ROW LEVEL SECURITY')
    op.execute(_when_role_exists('portal_admin', ADMIN_POLICIES))


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            'portal_admin',
            'REVOKE ALL ON portal.data_erasure_request FROM portal_admin;',
            'REVOKE ALL ON portal.organization_retention_policy FROM portal_admin;',
        )
    )
    op.execute(
        """
        DROP POLICY IF EXISTS data_erasure_request_admin_insert ON data_erasure_request;
        DROP POLICY IF EXISTS data_erasure_request_admin_read ON data_erasure_request;
        DROP POLICY IF EXISTS organization_retention_policy_admin_update ON organization_retention_policy;
        DROP POLICY IF EXISTS organization_retention_policy_admin_insert ON organization_retention_policy;
        DROP POLICY IF EXISTS organization_retention_policy_admin_read ON organization_retention_policy;
        """
    )
    op.drop_index(op.f('ix_data_erasure_request_organization_id'), table_name='data_erasure_request')
    op.drop_table('data_erasure_request')
    postgresql.ENUM(name='erasure_state').drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f('ix_organization_retention_policy_organization_id'), table_name='organization_retention_policy')
    op.drop_table('organization_retention_policy')
