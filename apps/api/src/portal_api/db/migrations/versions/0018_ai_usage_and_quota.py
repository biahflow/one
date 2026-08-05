"""razão de consumo de IA, teto por organização e preço com vigência (Fase 5, ADR 0022)

Revision ID: 0018_ai_usage_and_quota
Revises: 0017_chat_rate_window
Create Date: 2026-08-05

Três tabelas, três formas de policy diferentes, e cada diferença é uma decisão.

**``ai_usage_event`` dá ``INSERT`` a ``portal_app``**, o que é raro neste
repositório e tem o precedente exato da ADR 0015: o papel de requisição ganha
escrita quando ele **origina** a linha, como faz com ``conversation``. Aqui ele
origina — a chamada ao modelo acontece no caminho de requisição, e o consumo é
consequência dela. O ``WITH CHECK`` no tenant é a forma do ``agent_event`` (0010):
a linha nasce no caminho de requisição, então a RLS fica como segunda barreira
justamente ali.

Não há ``UPDATE`` nem ``DELETE`` para ninguém além do sistema, e isso é o ponto:
**ninguém reescreve o que uma chamada custou**, pela mesma razão pela qual
ninguém reescreve as citações que uma resposta mostrou (ADR 0015/0021).

**``organization_ai_quota`` é ``TO portal_admin`` e nada para ``portal_app``**,
igual a ``organization_retention_policy`` (0015). O papel de requisição herda o
SELECT das default privileges e lê zero linhas — a regra não é sobre ele. E há
uma exceção deliberada: ``portal_app`` **precisa** ler o teto para decidir se
recusa a pergunta, então ele ganha uma policy de leitura própria, restrita à
própria organização. Ler o próprio teto é diferente de administrá-lo.

**``ai_model_price`` não tem tenant nenhum.** Preço de modelo é fato do mundo.
RLS ligada e nenhuma policy de escrita para papel de requisição; a leitura é
liberada porque o cálculo do custo acontece sob ``portal_app`` e um preço não é
segredo de ninguém. Consequência a registrar aqui, porque quem ler depois vai
procurá-la: o meta-teste de ``test_rls_isolation.py`` **não** cobra policy desta
tabela, e não é esquecimento — ele cobra de toda tabela com ``organization_id``,
e esta não tem uma. Mesma situação de ``chat_rate_window`` (0017).

O ``EXCLUDE USING gist`` sobre a vigência é o mesmo da 0010 para a premissa
financeira, e pelo mesmo motivo: sem ele, "qual era o preço em março" pode ter
duas respostas e o banco não tem opinião sobre qual.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0018_ai_usage_and_quota'
down_revision: str | None = '0017_chat_rate_window'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APP_POLICIES = """
CREATE POLICY ai_usage_event_tenant_read ON ai_usage_event
  FOR SELECT TO portal_app
  USING (organization_id = portal.current_org());

CREATE POLICY ai_usage_event_tenant_insert ON ai_usage_event
  FOR INSERT TO portal_app
  WITH CHECK (organization_id = portal.current_org()
          AND project_id = portal.current_project());

CREATE POLICY organization_ai_quota_tenant_read ON organization_ai_quota
  FOR SELECT TO portal_app
  USING (organization_id = portal.current_org());

CREATE POLICY ai_model_price_read ON ai_model_price
  FOR SELECT TO portal_app
  USING (true);
"""

ADMIN_POLICIES = """
-- Ler o razão, nunca escrevê-lo. É a tela que responde "quanto este cliente
-- custou", e sem esta policy ela mostraria zero para toda organização — o pior
-- resultado possível, porque zero é um número plausível.
CREATE POLICY ai_usage_event_admin_read ON ai_usage_event
  FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());

CREATE POLICY ai_model_price_admin_read ON ai_model_price
  FOR SELECT TO portal_admin
  USING (true);

CREATE POLICY organization_ai_quota_admin_read ON organization_ai_quota
  FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());

CREATE POLICY organization_ai_quota_admin_insert ON organization_ai_quota
  FOR INSERT TO portal_admin
  WITH CHECK (organization_id = portal.current_admin_org());

CREATE POLICY organization_ai_quota_admin_update ON organization_ai_quota
  FOR UPDATE TO portal_admin
  USING (organization_id = portal.current_admin_org())
  WITH CHECK (organization_id = portal.current_admin_org());
"""

APP_GRANTS = """
GRANT SELECT, INSERT ON portal.ai_usage_event TO portal_app;
GRANT SELECT ON portal.organization_ai_quota TO portal_app;
GRANT SELECT ON portal.ai_model_price TO portal_app;
"""

ADMIN_GRANTS = """
GRANT SELECT, INSERT, UPDATE ON portal.organization_ai_quota TO portal_admin;
GRANT SELECT ON portal.ai_usage_event TO portal_admin;
GRANT SELECT ON portal.ai_model_price TO portal_admin;
"""

SYSTEM_GRANTS = """
GRANT SELECT, INSERT, UPDATE, DELETE ON portal.ai_usage_event TO portal_system;
GRANT SELECT, INSERT, UPDATE, DELETE ON portal.organization_ai_quota TO portal_system;
GRANT SELECT, INSERT, UPDATE, DELETE ON portal.ai_model_price TO portal_system;
"""

#: O preço do modelo padrão na data em que esta fatia foi escrita, para o cálculo
#: existir desde a primeira pergunta em vez de declarar lacuna até alguém lembrar.
#: Em centavos de dólar por milhão de tokens. Atualizar é abrir uma vigência nova,
#: nunca editar esta — ver `docs/runbooks/load-test.md`.
SEED_PRICE = """
INSERT INTO ai_model_price
  (id, model, effective_from, effective_to, input_cents_per_mtok, output_cents_per_mtok)
VALUES
  (gen_random_uuid(), 'claude-opus-5', DATE '2026-01-01', NULL, 500, 2500)
ON CONFLICT DO NOTHING;
"""


def _when_role_exists(role: str, *statements: str) -> str:
    """Roda o SQL só onde ``roles.sql`` criou o papel — mesmo formato da 0010/0015/0017."""
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
        'ai_usage_event',
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('model', sa.String(length=120), nullable=True),
        sa.Column('responder', sa.String(length=32), nullable=False),
        sa.Column('input_tokens', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('output_tokens', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['organization.id'],
            name=op.f('fk_ai_usage_event_organization_id_organization'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['project_id'],
            ['project.id'],
            name=op.f('fk_ai_usage_event_project_id_project'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_usage_event')),
    )
    op.create_index(
        op.f('ix_ai_usage_event_occurred_at'), 'ai_usage_event', ['occurred_at'], unique=False
    )
    op.create_index(
        op.f('ix_ai_usage_event_organization_id'),
        'ai_usage_event',
        ['organization_id'],
        unique=False,
    )
    op.create_index(
        'ix_ai_usage_event_org_occurred',
        'ai_usage_event',
        ['organization_id', 'occurred_at'],
        unique=False,
    )
    op.create_index(
        op.f('ix_ai_usage_event_project_id'), 'ai_usage_event', ['project_id'], unique=False
    )

    op.create_table(
        'organization_ai_quota',
        sa.Column('monthly_limit_cents', sa.BigInteger(), nullable=True),
        sa.Column('updated_by_user_id', sa.UUID(), nullable=True),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['organization.id'],
            name=op.f('fk_organization_ai_quota_organization_id_organization'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['updated_by_user_id'],
            ['user.id'],
            name=op.f('fk_organization_ai_quota_updated_by_user_id_user'),
            ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_organization_ai_quota')),
        sa.UniqueConstraint(
            'organization_id', name='uq_organization_ai_quota_organization_id'
        ),
    )
    op.create_index(
        op.f('ix_organization_ai_quota_organization_id'),
        'organization_ai_quota',
        ['organization_id'],
        unique=False,
    )

    op.create_table(
        'ai_model_price',
        sa.Column('model', sa.String(length=120), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('input_cents_per_mtok', sa.Integer(), nullable=False),
        sa.Column('output_cents_per_mtok', sa.Integer(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_model_price')),
    )
    op.create_index(op.f('ix_ai_model_price_model'), 'ai_model_price', ['model'], unique=False)

    # Duas vigências do mesmo modelo não podem se sobrepor — mesma construção da
    # premissa financeira (0010). `btree_gist` já entrou no bootstrap e nas
    # extensões da 0010; o restore da ADR 0019 depende disso e é onde a lição foi
    # aprendida.
    op.execute(
        """
        ALTER TABLE ai_model_price
          ADD CONSTRAINT ck_ai_model_price_effective_range
          EXCLUDE USING gist (
            model WITH =,
            daterange(effective_from, effective_to, '[)') WITH &&
          )
        """
    )

    op.execute('ALTER TABLE ai_usage_event ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE organization_ai_quota ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE ai_model_price ENABLE ROW LEVEL SECURITY')

    op.execute(_when_role_exists('portal_app', APP_POLICIES, APP_GRANTS))
    op.execute(_when_role_exists('portal_admin', ADMIN_POLICIES, ADMIN_GRANTS))
    op.execute(_when_role_exists('portal_system', SYSTEM_GRANTS))

    op.execute(SEED_PRICE)


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            'portal_system',
            'REVOKE ALL ON portal.ai_usage_event FROM portal_system;',
            'REVOKE ALL ON portal.organization_ai_quota FROM portal_system;',
            'REVOKE ALL ON portal.ai_model_price FROM portal_system;',
        )
    )
    op.execute(
        _when_role_exists(
            'portal_admin',
            'REVOKE ALL ON portal.organization_ai_quota FROM portal_admin;',
            'REVOKE ALL ON portal.ai_usage_event FROM portal_admin;',
            'REVOKE ALL ON portal.ai_model_price FROM portal_admin;',
        )
    )
    op.execute(
        _when_role_exists(
            'portal_app',
            'REVOKE ALL ON portal.ai_usage_event FROM portal_app;',
            'REVOKE ALL ON portal.organization_ai_quota FROM portal_app;',
            'REVOKE ALL ON portal.ai_model_price FROM portal_app;',
        )
    )
    op.drop_index(op.f('ix_ai_model_price_model'), table_name='ai_model_price')
    op.drop_table('ai_model_price')
    op.drop_index(
        op.f('ix_organization_ai_quota_organization_id'), table_name='organization_ai_quota'
    )
    op.drop_table('organization_ai_quota')
    op.drop_index(op.f('ix_ai_usage_event_project_id'), table_name='ai_usage_event')
    op.drop_index('ix_ai_usage_event_org_occurred', table_name='ai_usage_event')
    op.drop_index(op.f('ix_ai_usage_event_organization_id'), table_name='ai_usage_event')
    op.drop_index(op.f('ix_ai_usage_event_occurred_at'), table_name='ai_usage_event')
    op.drop_table('ai_usage_event')
