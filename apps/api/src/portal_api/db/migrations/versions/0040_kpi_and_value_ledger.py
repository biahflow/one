"""o KPI do projeto e o Value Ledger do mandato (Language Map v1.1, ADR 0085)

Revision ID: 0040_kpi_and_value_ledger
Revises: 0039_journey_canonical_stage
Create Date: 2026-09-02

Duas tabelas novas e uma coluna aditiva em ``digital_employee``. O ``upgrade()``
não apaga dado (ADR 0066), e a decisão que ele cita é a **ADR 0085** — obrigatória
porque as duas tabelas nascem com ``ENABLE ROW LEVEL SECURITY``, ``CREATE POLICY``
e ``GRANT``, que é o gatilho estrutural da regra 4 do `AGENTS.md`.

**``kpi`` é escopo de projeto e usa o predicado simples da 0007.** O snapshot
manda ``kpis[]`` por projeto, e quem os lê é ``build_dashboard`` — que roda com as
GUCs de segundo estágio fixadas por ``access.scoped_project``. É a mesma forma de
``milestone`` e ``digital_employee``: ``organization_id = portal.current_org() AND
project_id = portal.current_project()``, comparação de coluna denormalizada, sem
subconsulta.

**``value_ledger_entry`` é escopo de mandato, e por isso o predicado é outro.** A
tabela não tem ``project_id`` — a entrada pertence ao Engagement, e o Pulse a
manda em fan-out no snapshot de todos os projetos dele. O predicado de tenant puro
(``organization_id = portal.current_org()``) seria **largo demais** pelo argumento
que a 0037 já escreveu para o programa: numa conta com dois mandatos, quem foi
convidado para um projeto passaria a ler o valor gerado do outro. E o predicado da
0037 — vínculo por ``membership`` — seria largo pelo outro lado, porque aqui não é
``GET /me`` que lê: é o dashboard de **um** projeto, com tenant fixado.

Daí o ``EXISTS`` sobre ``project``: a entrada é visível quando o **projeto
corrente** pertence ao mandato dela. É a tradução literal de "o Value Ledger deste
mandato, visto de dentro de um projeto dele", e ela herda a barreira do projeto
sem reimplementá-la — a policy de ``project`` (0007 §3) consulta ``membership``,
cuja policy é GUC pura, então não há recursão.

``organization_id`` entra no predicado **junto** do ``EXISTS``, e não em vez dele:
sem ele, uma GUC de projeto sem GUC de organização leria o mandato inteiro. Com os
dois, contexto ausente devolve zero linhas, que é o desenho da 0007.

**Nenhum ``INSERT``/``UPDATE``/``DELETE`` para ``portal_app``, nas duas.** KPI e
valor gerado nascem do snapshot sob ``portal_system``, como fase, entregável e
Engagement: o portal não origina status (ADR 0006/0008). Um caminho de requisição
capaz de escrever o próprio Outcome é um caminho capaz de falsear o próprio
resultado — o mesmo argumento que a ADR 0039 escreveu para o funil.

``portal_admin`` ganha leitura pela GUC de terceiro estágio, como ``engagement`` na
0037: as telas de ``/admin`` são escopadas por organização.

A coluna ``kpi_external_ids`` é ``NOT NULL`` com ``server_default '[]'`` pelo
argumento do ``requires_gate`` da 0039: toda linha anterior a esta migração não
referencia KPI nenhum, e lista vazia é exatamente isso — não é aterro, é o estado
verdadeiro. Sem ``GRANT`` novo: ``digital_employee`` já tem os seus desde a 0007, e
uma coluna a mais numa tabela ``SELECT``-only continua ``SELECT``-only.

Sem índice em ``kpi.external_id`` além do único: ele é lido por ``project_id`` (o
dashboard carrega os KPIs do projeto inteiro) e a unicidade
``(project_id, external_id)`` já é o índice que o casamento por id usa.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0040_kpi_and_value_ledger'
down_revision: str | None = '0039_journey_canonical_stage'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Escopo de projeto: o predicado simples da 0007, sobre colunas denormalizadas.
KPI_POLICIES = """
CREATE POLICY kpi_tenant_read ON kpi FOR SELECT
  USING (organization_id = portal.current_org()
     AND project_id = portal.current_project());
"""

# Escopo de mandato: ver o docstring. O `EXISTS` liga o mandato da entrada ao
# projeto corrente, e o `organization_id` mantém "contexto ausente devolve zero".
LEDGER_POLICIES = """
CREATE POLICY value_ledger_entry_tenant_read ON value_ledger_entry FOR SELECT
  USING (organization_id = portal.current_org()
     AND EXISTS (SELECT 1 FROM project p
                  WHERE p.id = portal.current_project()
                    AND p.engagement_id = value_ledger_entry.engagement_id));
"""

ADMIN_POLICIES = """
CREATE POLICY kpi_admin_read ON kpi
  FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());

CREATE POLICY value_ledger_entry_admin_read ON value_ledger_entry
  FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());

GRANT SELECT ON portal.kpi TO portal_admin;
GRANT SELECT ON portal.value_ledger_entry TO portal_admin;
"""

# A ausência de INSERT/UPDATE/DELETE é o controle, não um esquecimento.
GRANTS = """
GRANT SELECT ON portal.kpi TO portal_app;
GRANT SELECT ON portal.value_ledger_entry TO portal_app;
"""


def _when_role_exists(role: str, *statements: str) -> str:
    """Mesma guarda de 0007/0008/0012/0015/0021/0035/0037: sem ``roles.sql``, não há a quem conceder."""
    body = "\n".join(statements)
    return f"""
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
            RAISE NOTICE '{role} is absent; skipping the kpi/value ledger grants (run roles.sql)';
            RETURN;
          END IF;
          EXECUTE $sql${body}$sql$;
        END
        $do$;
    """


def upgrade() -> None:
    op.create_table(
        'kpi',
        sa.Column('external_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('definition', sa.Text(), nullable=True),
        sa.Column('formula', sa.Text(), nullable=True),
        sa.Column('unit', sa.String(length=40), nullable=True),
        sa.Column('direction', sa.String(length=20), nullable=True),
        sa.Column('data_source', sa.String(length=200), nullable=True),
        sa.Column('cadence', sa.String(length=40), nullable=True),
        sa.Column('target', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('baseline_value', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('baseline_period_start', sa.Date(), nullable=True),
        sa.Column('baseline_period_end', sa.Date(), nullable=True),
        sa.Column('baseline_measured_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('baseline_confidence', sa.Integer(), nullable=True),
        sa.Column('outcome_value', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('outcome_period_start', sa.Date(), nullable=True),
        sa.Column('outcome_period_end', sa.Date(), nullable=True),
        sa.Column('outcome_measured_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('outcome_confidence', sa.Integer(), nullable=True),
        sa.Column(
            'monitoring',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]',
            nullable=False,
        ),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_kpi_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_kpi_project_id_project'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_kpi')),
        sa.UniqueConstraint('project_id', 'external_id', name='uq_kpi_project_external_id'),
    )
    op.create_index(op.f('ix_kpi_organization_id'), 'kpi', ['organization_id'], unique=False)
    op.create_index(op.f('ix_kpi_project_id'), 'kpi', ['project_id'], unique=False)

    op.create_table(
        'value_ledger_entry',
        sa.Column('engagement_id', sa.UUID(), nullable=False),
        sa.Column('external_id', sa.Integer(), nullable=False),
        sa.Column('value_type', sa.String(length=60), nullable=False),
        sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('attribution_method', sa.Text(), nullable=False),
        sa.Column('kpi_external_id', sa.Integer(), nullable=True),
        sa.Column('outcome_measured_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['engagement_id'], ['engagement.id'], name=op.f('fk_value_ledger_entry_engagement_id_engagement'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_value_ledger_entry_organization_id_organization'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_value_ledger_entry')),
        sa.UniqueConstraint('engagement_id', 'external_id', name='uq_value_ledger_entry_engagement_id'),
    )
    op.create_index(op.f('ix_value_ledger_entry_engagement_id'), 'value_ledger_entry', ['engagement_id'], unique=False)
    op.create_index(op.f('ix_value_ledger_entry_organization_id'), 'value_ledger_entry', ['organization_id'], unique=False)

    op.add_column(
        'digital_employee',
        sa.Column(
            'kpi_external_ids',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]',
            nullable=False,
        ),
    )

    op.execute('ALTER TABLE kpi ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE value_ledger_entry ENABLE ROW LEVEL SECURITY')
    op.execute(KPI_POLICIES)
    op.execute(LEDGER_POLICIES)
    op.execute(_when_role_exists('portal_app', GRANTS))
    op.execute(_when_role_exists('portal_admin', ADMIN_POLICIES))


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            'portal_admin',
            'DROP POLICY IF EXISTS value_ledger_entry_admin_read ON value_ledger_entry;',
            'DROP POLICY IF EXISTS kpi_admin_read ON kpi;',
            'REVOKE ALL ON portal.value_ledger_entry FROM portal_admin;',
            'REVOKE ALL ON portal.kpi FROM portal_admin;',
        )
    )
    op.execute(
        _when_role_exists(
            'portal_app',
            'REVOKE ALL ON portal.value_ledger_entry FROM portal_app;',
            'REVOKE ALL ON portal.kpi FROM portal_app;',
        )
    )
    op.execute('DROP POLICY IF EXISTS value_ledger_entry_tenant_read ON value_ledger_entry')
    op.execute('DROP POLICY IF EXISTS kpi_tenant_read ON kpi')
    op.drop_column('digital_employee', 'kpi_external_ids')
    op.drop_index(op.f('ix_value_ledger_entry_organization_id'), table_name='value_ledger_entry')
    op.drop_index(op.f('ix_value_ledger_entry_engagement_id'), table_name='value_ledger_entry')
    op.drop_table('value_ledger_entry')
    op.drop_index(op.f('ix_kpi_project_id'), table_name='kpi')
    op.drop_index(op.f('ix_kpi_organization_id'), table_name='kpi')
    op.drop_table('kpi')
