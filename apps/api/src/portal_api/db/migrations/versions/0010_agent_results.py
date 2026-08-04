"""agent api keys, financial assumptions and the outcome of a run (ADR 0013)

Revision ID: 0010_agent_results
Revises: 0009_notifications
Create Date: 2026-08-04

Três coisas, que só fazem sentido juntas — é o que a Fase 3 entrega:

* ``agent_api_key`` — a credencial de um agente. O tenant é propriedade da
  *chave*, não do corpo da requisição, e é isso que permite à rota de ingestão
  aceitar um ``projectId`` vindo de fora sem confiar nele. Só o prefixo fica em
  claro; o segredo vira HMAC sob um pepper de servidor;
* ``project_financial_assumption`` — valor-hora e investimento **com vigência**.
  Um ``EXCLUDE USING gist`` impede vigências sobrepostas: a premissa que explica
  um indicador de três meses atrás é uma propriedade da tabela, não uma
  esperança do código;
* colunas novas em ``agent_event`` — desfecho, intervenção humana e os inteiros
  que o produtor mandou. Aditivas, com ``server_default``, e ``agent_event``
  ganha finalmente uma policy de INSERT: até aqui ``portal_app`` só lia, porque
  nada gravava.

Sobre a policy de escrita em ``agent_event``: a alternativa seria gravar sob
``portal_system`` (BYPASSRLS), como faz o webhook do Biahflow. Seria mais fácil
e pior — o webhook roda sob ``system`` porque *cria* o tenant e não tem contexto
para ligar, enquanto aqui o tenant já é conhecido antes da primeira consulta. Dar
INSERT ao ``portal_app`` com ``WITH CHECK`` mantém o banco como segunda barreira
justamente na rota que recebe identificador de fora.

``agent_api_key`` não concede nada a ``portal_app``: o caminho de requisição do
cliente não tem por que enxergar credencial. Suas policies são ``TO portal_admin``
pelo motivo escrito na 0008 — a policy não se aplica ao papel de requisição, então
um ``set_config`` perdido lá não alcança nada.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0010_agent_results'
down_revision: str | None = '0009_notifications'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _when_role_exists(role: str, *statements: str) -> str:
    """Roda o SQL só onde ``roles.sql`` criou o papel — mesmo formato da 0008."""
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
    # 1. agent_event: desfecho e os inteiros do produtor.
    outcome = postgresql.ENUM(
        'success', 'exception_handled', 'failed', name='agent_event_outcome'
    )
    outcome.create(op.get_bind(), checkfirst=True)
    op.add_column('agent_event', sa.Column('agent_key', sa.String(length=80), nullable=True))
    op.create_index(op.f('ix_agent_event_agent_key'), 'agent_event', ['agent_key'], unique=False)
    op.add_column(
        'agent_event',
        sa.Column(
            'outcome',
            postgresql.ENUM(
                'success',
                'exception_handled',
                'failed',
                name='agent_event_outcome',
                create_type=False,
            ),
            nullable=False,
            server_default='success',
        ),
    )
    op.add_column(
        'agent_event',
        sa.Column('human_intervention', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column('agent_event', sa.Column('time_saved_seconds', sa.Integer(), nullable=True))
    op.add_column('agent_event', sa.Column('avoided_cost_cents', sa.BigInteger(), nullable=True))
    op.add_column('agent_event', sa.Column('run_reference', sa.String(length=160), nullable=True))
    op.create_index(
        'ix_agent_event_project_occurred', 'agent_event', ['project_id', 'occurred_at'], unique=False
    )

    # 2. agent_api_key.
    op.create_table(
        'agent_api_key',
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('key_prefix', sa.String(length=12), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column(
            'scopes',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default='["events:write"]',
        ),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rotated_from_id', sa.UUID(), nullable=True),
        sa.Column('created_by_user_id', sa.UUID(), nullable=True),
        sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('window_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['created_by_user_id'], ['user.id'],
            name=op.f('fk_agent_api_key_created_by_user_id_user'), ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organization.id'],
            name=op.f('fk_agent_api_key_organization_id_organization'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['project_id'], ['project.id'],
            name=op.f('fk_agent_api_key_project_id_project'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['rotated_from_id'], ['agent_api_key.id'],
            name=op.f('fk_agent_api_key_rotated_from_id_agent_api_key'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_api_key')),
        sa.UniqueConstraint('key_prefix', name='uq_agent_api_key_key_prefix'),
    )
    op.create_index(
        op.f('ix_agent_api_key_organization_id'), 'agent_api_key', ['organization_id'], unique=False
    )
    op.create_index(
        op.f('ix_agent_api_key_project_id'), 'agent_api_key', ['project_id'], unique=False
    )

    # 3. project_financial_assumption. `btree_gist` é o que permite combinar a
    # igualdade de `project_id` com a sobreposição do intervalo num só EXCLUDE.
    op.execute('CREATE EXTENSION IF NOT EXISTS btree_gist')
    op.create_table(
        'project_financial_assumption',
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('hourly_rate_cents', sa.Integer(), nullable=False),
        sa.Column('monthly_investment_cents', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='BRL'),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.UUID(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            'effective_to IS NULL OR effective_to > effective_from',
            name=op.f('ck_project_financial_assumption_effective_range'),
        ),
        sa.CheckConstraint(
            'hourly_rate_cents >= 0 AND monthly_investment_cents >= 0',
            name=op.f('ck_project_financial_assumption_non_negative'),
        ),
        sa.ForeignKeyConstraint(
            ['created_by_user_id'], ['user.id'],
            name=op.f('fk_project_financial_assumption_created_by_user_id_user'), ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organization.id'],
            name=op.f('fk_project_financial_assumption_organization_id_organization'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['project_id'], ['project.id'],
            name=op.f('fk_project_financial_assumption_project_id_project'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_project_financial_assumption')),
    )
    op.create_index(
        op.f('ix_project_financial_assumption_organization_id'),
        'project_financial_assumption', ['organization_id'], unique=False,
    )
    op.create_index(
        op.f('ix_project_financial_assumption_project_id'),
        'project_financial_assumption', ['project_id'], unique=False,
    )
    # Duas vigências do mesmo projeto não podem se cruzar. Sem isto, "qual era a
    # premissa naquele dia" passaria a ter mais de uma resposta.
    op.execute(
        """
        ALTER TABLE project_financial_assumption
          ADD CONSTRAINT uq_project_financial_assumption_no_overlap
          EXCLUDE USING gist (
            project_id WITH =,
            daterange(effective_from, effective_to, '[)') WITH &&
          )
        """
    )

    # 4. RLS. O meta-teste de `test_rls_isolation.py` cobra policy de toda tabela
    # com `organization_id`, e é ele que impede uma tabela nova de nascer aberta.
    op.execute('ALTER TABLE agent_api_key ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE project_financial_assumption ENABLE ROW LEVEL SECURITY')

    # A premissa é client-safe e é metade do aceite da fase: o cliente vê o
    # indicador e a premissa que o produziu. Leitura pelo caminho normal.
    op.execute(
        """
        CREATE POLICY project_financial_assumption_tenant_read
          ON project_financial_assumption FOR SELECT
          USING (organization_id = portal.current_org()
             AND project_id = portal.current_project())
        """
    )
    # A ingestão de evento passa a escrever pelo caminho de requisição.
    op.execute(
        """
        CREATE POLICY agent_event_tenant_insert ON agent_event FOR INSERT
          WITH CHECK (organization_id = portal.current_org()
                  AND project_id = portal.current_project())
        """
    )

    op.execute(
        _when_role_exists(
            'portal_admin',
            """
            CREATE POLICY agent_api_key_admin_read ON agent_api_key
              FOR SELECT TO portal_admin
              USING (organization_id = portal.current_admin_org());

            CREATE POLICY agent_api_key_admin_insert ON agent_api_key
              FOR INSERT TO portal_admin
              WITH CHECK (organization_id = portal.current_admin_org());

            CREATE POLICY agent_api_key_admin_update ON agent_api_key
              FOR UPDATE TO portal_admin
              USING (organization_id = portal.current_admin_org())
              WITH CHECK (organization_id = portal.current_admin_org());

            CREATE POLICY project_financial_assumption_admin_read
              ON project_financial_assumption FOR SELECT TO portal_admin
              USING (organization_id = portal.current_admin_org());

            CREATE POLICY project_financial_assumption_admin_insert
              ON project_financial_assumption FOR INSERT TO portal_admin
              WITH CHECK (organization_id = portal.current_admin_org());

            CREATE POLICY project_financial_assumption_admin_update
              ON project_financial_assumption FOR UPDATE TO portal_admin
              USING (organization_id = portal.current_admin_org())
              WITH CHECK (organization_id = portal.current_admin_org());

            GRANT SELECT, INSERT, UPDATE ON portal.agent_api_key TO portal_admin;
            GRANT SELECT, INSERT, UPDATE
              ON portal.project_financial_assumption TO portal_admin;
            """,
        )
    )

    # `portal_app` ganha INSERT no evento e SELECT na premissa — e nada na chave.
    op.execute(
        _when_role_exists(
            'portal_app',
            """
            GRANT INSERT ON portal.agent_event TO portal_app;
            GRANT SELECT ON portal.project_financial_assumption TO portal_app;
            """,
        )
    )


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            'portal_app',
            """
            REVOKE INSERT ON portal.agent_event FROM portal_app;
            REVOKE ALL ON portal.project_financial_assumption FROM portal_app;
            """,
        )
    )
    op.execute(
        _when_role_exists(
            'portal_admin',
            """
            REVOKE ALL ON portal.agent_api_key,
                          portal.project_financial_assumption FROM portal_admin;
            """,
        )
    )
    op.execute(
        """
        DROP POLICY IF EXISTS agent_event_tenant_insert ON agent_event;
        DROP POLICY IF EXISTS project_financial_assumption_admin_update
          ON project_financial_assumption;
        DROP POLICY IF EXISTS project_financial_assumption_admin_insert
          ON project_financial_assumption;
        DROP POLICY IF EXISTS project_financial_assumption_admin_read
          ON project_financial_assumption;
        DROP POLICY IF EXISTS project_financial_assumption_tenant_read
          ON project_financial_assumption;
        DROP POLICY IF EXISTS agent_api_key_admin_update ON agent_api_key;
        DROP POLICY IF EXISTS agent_api_key_admin_insert ON agent_api_key;
        DROP POLICY IF EXISTS agent_api_key_admin_read ON agent_api_key;
        """
    )
    op.drop_table('project_financial_assumption')
    op.drop_table('agent_api_key')
    op.drop_index('ix_agent_event_project_occurred', table_name='agent_event')
    op.drop_column('agent_event', 'run_reference')
    op.drop_column('agent_event', 'avoided_cost_cents')
    op.drop_column('agent_event', 'time_saved_seconds')
    op.drop_column('agent_event', 'human_intervention')
    op.drop_column('agent_event', 'outcome')
    op.drop_index(op.f('ix_agent_event_agent_key'), table_name='agent_event')
    op.drop_column('agent_event', 'agent_key')
    postgresql.ENUM(name='agent_event_outcome').drop(op.get_bind(), checkfirst=True)
