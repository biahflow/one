"""a superfície de Discovery que o cliente lê (Language Map v1.1, ADR 0086)

Revision ID: 0041_discovery_surface
Revises: 0040_kpi_and_value_ledger
Create Date: 2026-09-02

Oito tabelas novas e nenhuma coluna alterada. O ``upgrade()`` não apaga dado
(ADR 0066), e a decisão que ele cita é a **ADR 0086** — obrigatória porque as oito
nascem com ``ENABLE ROW LEVEL SECURITY``, ``CREATE POLICY`` e ``GRANT``, que é o
gatilho estrutural da regra 4 do `AGENTS.md`.

**Escopo de conta, e por isso o predicado é o mais curto do repositório.** As seis
tabelas com ``organization_id`` usam ``organization_id = portal.current_org()``, e
**não** o par com ``project_id`` da 0007: o Discovery é lido por Account no Pulse e
sai em fan-out no snapshot de todo projeto dela. Um predicado com projeto não teria
coluna com que comparar.

Isso é mais largo que o da 0040 de propósito, e o limite está declarado: **duas
pessoas convidadas para projetos diferentes da mesma conta veem o mesmo
Discovery**. É o que a conta *é* — o AS-IS, os achados e o backlog de melhoria são
dela, não de um projeto —, e é a mesma decisão que ``engagement`` tomou ao ser
legível por vínculo em vez de por projeto. Quem quisesse recortar por projeto
precisaria de um vínculo que o produtor não emite: nem processo, nem achado, nem
oportunidade carregam projeto no payload.

Contexto ausente continua devolvendo zero linhas: ``current_setting(..., true)``
é NULL sem GUC, e a comparação com NULL não casa. É o desenho da 0007.

**As duas tabelas de ligação não têm ``organization_id``, e a policy alcança a
linha pelo pai.** Elas não são uma coisa — são o fato de duas coisas se ligarem —,
e uma terceira cópia da chave de tenant seria um segundo lugar dizendo o que a dor
já diz, podendo divergir. O ``EXISTS`` é a forma que a 0040 já usou para o razão do
mandato, e não há recursão: a policy de ``pain_point`` é GUC pura.

O par ``(pai, filho)`` é chave primária, e é ele que impede a mesma ligação de
entrar duas vezes — a substituição integral do sync a recria a cada passagem, e sem
a PK um payload com id repetido duplicaria a linha em silêncio.

**Nenhum ``INSERT``/``UPDATE``/``DELETE`` para ``portal_app``, nas oito.** Como
fase, entregável, Engagement e KPI, o Discovery nasce do snapshot sob
``portal_system``: o portal não origina status (ADR 0006/0008). Aqui a ausência
guarda uma coisa específica — um caminho de requisição capaz de escrever um
``Finding`` é um caminho capaz de promover a própria hipótese a fato, que é a
regra 1 da §3 do Language Map ("nada aparece no One antes de ser revisado por
humano") escrita como privilégio.

``portal_admin`` ganha leitura pela GUC de terceiro estágio, como ``engagement`` na
0037 e ``kpi`` na 0040: as telas de ``/admin`` são escopadas por organização.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0041_discovery_surface'
down_revision: str | None = '0040_kpi_and_value_ledger'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: As seis com chave de tenant: o predicado curto, sobre a coluna denormalizada.
TENANT_TABLES = (
    "process",
    "process_step",
    "finding",
    "pain_point",
    "improvement_opportunity",
    "solution_hypothesis",
)

#: As duas de ligação: `(tabela, coluna do pai, tabela do pai)`. A policy alcança a
#: linha pelo pai, e o `organization_id` dele entra no predicado **junto** do
#: `EXISTS` — não em vez dele —, para contexto ausente continuar devolvendo zero.
LINK_TABLES = (
    ("pain_point_finding", "pain_point_id", "pain_point"),
    ("improvement_opportunity_pain_point", "improvement_opportunity_id", "improvement_opportunity"),
)


def _tenant_policy(table: str) -> str:
    return (
        f"CREATE POLICY {table}_tenant_read ON {table} FOR SELECT\n"
        f"  USING (organization_id = portal.current_org());"
    )


def _link_policy(table: str, column: str, parent: str) -> str:
    return (
        f"CREATE POLICY {table}_tenant_read ON {table} FOR SELECT\n"
        f"  USING (EXISTS (SELECT 1 FROM {parent} parent\n"
        f"                  WHERE parent.id = {table}.{column}\n"
        f"                    AND parent.organization_id = portal.current_org()));"
    )


def _admin_policy(table: str) -> str:
    return (
        f"CREATE POLICY {table}_admin_read ON {table}\n"
        f"  FOR SELECT TO portal_admin\n"
        f"  USING (organization_id = portal.current_admin_org());"
    )


def _link_admin_policy(table: str, column: str, parent: str) -> str:
    return (
        f"CREATE POLICY {table}_admin_read ON {table}\n"
        f"  FOR SELECT TO portal_admin\n"
        f"  USING (EXISTS (SELECT 1 FROM {parent} parent\n"
        f"                  WHERE parent.id = {table}.{column}\n"
        f"                    AND parent.organization_id = portal.current_admin_org()));"
    )


ALL_TABLES = TENANT_TABLES + tuple(name for name, _, _ in LINK_TABLES)

# A ausência de INSERT/UPDATE/DELETE é o controle, não um esquecimento.
GRANTS = "\n".join(f"GRANT SELECT ON portal.{table} TO portal_app;" for table in ALL_TABLES)

ADMIN_POLICIES = "\n".join(
    [_admin_policy(table) for table in TENANT_TABLES]
    + [_link_admin_policy(*link) for link in LINK_TABLES]
    + [f"GRANT SELECT ON portal.{table} TO portal_admin;" for table in ALL_TABLES]
)


def _when_role_exists(role: str, *statements: str) -> str:
    """Mesma guarda de 0007/0008/0012/0015/0021/0035/0037/0040: sem ``roles.sql``, não há a quem conceder."""
    body = "\n".join(statements)
    return f"""
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
            RAISE NOTICE '{role} is absent; skipping the discovery grants (run roles.sql)';
            RETURN;
          END IF;
          EXECUTE $sql${body}$sql$;
        END
        $do$;
    """


def upgrade() -> None:
    op.create_table(
        'process',
        sa.Column('external_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_process_organization_id_organization'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_process')),
        sa.UniqueConstraint('organization_id', 'external_id', name='uq_process_organization_id'),
    )
    op.create_index(op.f('ix_process_organization_id'), 'process', ['organization_id'], unique=False)

    op.create_table(
        'process_step',
        sa.Column('process_id', sa.UUID(), nullable=False),
        sa.Column('external_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('pessoas', sa.Text(), nullable=True),
        sa.Column('sistema', sa.Text(), nullable=True),
        sa.Column('dados', sa.Text(), nullable=True),
        sa.Column('tempo', sa.Text(), nullable=True),
        sa.Column('erro', sa.Text(), nullable=True),
        sa.Column('retrabalho', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_process_step_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['process_id'], ['process.id'], name=op.f('fk_process_step_process_id_process'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_process_step')),
        sa.UniqueConstraint('process_id', 'external_id', name='uq_process_step_process_id'),
    )
    op.create_index(op.f('ix_process_step_organization_id'), 'process_step', ['organization_id'], unique=False)
    op.create_index(op.f('ix_process_step_process_id'), 'process_step', ['process_id'], unique=False)

    op.create_table(
        'finding',
        sa.Column('external_id', sa.Integer(), nullable=False),
        sa.Column('statement', sa.Text(), nullable=False),
        sa.Column(
            'epistemic_status',
            sa.Enum('fact', 'hypothesis', 'unknown', name='epistemic_status'),
            nullable=False,
        ),
        sa.Column('confidence', sa.Integer(), nullable=True),
        sa.Column('process_id', sa.UUID(), nullable=True),
        sa.Column('step_id', sa.UUID(), nullable=True),
        sa.Column(
            'evidences',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]',
            nullable=False,
        ),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_finding_organization_id_organization'), ondelete='CASCADE'),
        # `SET NULL` e não `CASCADE`: perder a proveniência é melhor que perder o
        # achado — o argumento que `Decision.meeting_id` já escreveu.
        sa.ForeignKeyConstraint(['process_id'], ['process.id'], name=op.f('fk_finding_process_id_process'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['step_id'], ['process_step.id'], name=op.f('fk_finding_step_id_process_step'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_finding')),
        sa.UniqueConstraint('organization_id', 'external_id', name='uq_finding_organization_id'),
    )
    op.create_index(op.f('ix_finding_organization_id'), 'finding', ['organization_id'], unique=False)
    op.create_index(op.f('ix_finding_process_id'), 'finding', ['process_id'], unique=False)

    op.create_table(
        'pain_point',
        sa.Column('external_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('impact_type', sa.String(length=60), nullable=True),
        sa.Column('impact_estimate', sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column('status', sa.String(length=60), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_pain_point_organization_id_organization'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_pain_point')),
        sa.UniqueConstraint('organization_id', 'external_id', name='uq_pain_point_organization_id'),
    )
    op.create_index(op.f('ix_pain_point_organization_id'), 'pain_point', ['organization_id'], unique=False)

    op.create_table(
        'pain_point_finding',
        sa.Column('pain_point_id', sa.UUID(), nullable=False),
        sa.Column('finding_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['finding_id'], ['finding.id'], name=op.f('fk_pain_point_finding_finding_id_finding'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pain_point_id'], ['pain_point.id'], name=op.f('fk_pain_point_finding_pain_point_id_pain_point'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('pain_point_id', 'finding_id', name=op.f('pk_pain_point_finding')),
    )

    op.create_table(
        'improvement_opportunity',
        sa.Column('external_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('desired_change', sa.Text(), nullable=True),
        sa.Column('impact_hypothesis', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=60), nullable=False),
        sa.Column('priority_version', sa.Integer(), nullable=True),
        sa.Column('priority_score', sa.Integer(), nullable=True),
        sa.Column('priority_dimensions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_improvement_opportunity_organization_id_organization'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_improvement_opportunity')),
        sa.UniqueConstraint('organization_id', 'external_id', name='uq_improvement_opportunity_organization_id'),
    )
    op.create_index(op.f('ix_improvement_opportunity_organization_id'), 'improvement_opportunity', ['organization_id'], unique=False)

    op.create_table(
        'improvement_opportunity_pain_point',
        sa.Column('improvement_opportunity_id', sa.UUID(), nullable=False),
        sa.Column('pain_point_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['improvement_opportunity_id'], ['improvement_opportunity.id'], name='fk_improvement_opportunity_pain_point_opportunity', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pain_point_id'], ['pain_point.id'], name='fk_improvement_opportunity_pain_point_pain_point', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('improvement_opportunity_id', 'pain_point_id', name=op.f('pk_improvement_opportunity_pain_point')),
    )

    op.create_table(
        'solution_hypothesis',
        sa.Column('improvement_opportunity_id', sa.UUID(), nullable=False),
        sa.Column('external_id', sa.Integer(), nullable=False),
        sa.Column('statement', sa.Text(), nullable=False),
        sa.Column('intervention', sa.Text(), nullable=True),
        sa.Column('expected_effect', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=60), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['improvement_opportunity_id'], ['improvement_opportunity.id'], name='fk_solution_hypothesis_improvement_opportunity', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_solution_hypothesis_organization_id_organization'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_solution_hypothesis')),
        sa.UniqueConstraint('improvement_opportunity_id', 'external_id', name='uq_solution_hypothesis_improvement_opportunity_id'),
    )
    op.create_index(op.f('ix_solution_hypothesis_improvement_opportunity_id'), 'solution_hypothesis', ['improvement_opportunity_id'], unique=False)
    op.create_index(op.f('ix_solution_hypothesis_organization_id'), 'solution_hypothesis', ['organization_id'], unique=False)

    for table in ALL_TABLES:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
    for table in TENANT_TABLES:
        op.execute(_tenant_policy(table))
    for link in LINK_TABLES:
        op.execute(_link_policy(*link))
    op.execute(_when_role_exists('portal_app', GRANTS))
    op.execute(_when_role_exists('portal_admin', ADMIN_POLICIES))


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            'portal_admin',
            *[
                f'DROP POLICY IF EXISTS {table}_admin_read ON {table};'
                for table in reversed(ALL_TABLES)
            ],
            *[
                f'REVOKE ALL ON portal.{table} FROM portal_admin;'
                for table in reversed(ALL_TABLES)
            ],
        )
    )
    op.execute(
        _when_role_exists(
            'portal_app',
            *[
                f'REVOKE ALL ON portal.{table} FROM portal_app;'
                for table in reversed(ALL_TABLES)
            ],
        )
    )
    for table in reversed(ALL_TABLES):
        op.execute(f'DROP POLICY IF EXISTS {table}_tenant_read ON {table}')

    op.drop_index(op.f('ix_solution_hypothesis_organization_id'), table_name='solution_hypothesis')
    op.drop_index(op.f('ix_solution_hypothesis_improvement_opportunity_id'), table_name='solution_hypothesis')
    op.drop_table('solution_hypothesis')
    op.drop_table('improvement_opportunity_pain_point')
    op.drop_index(op.f('ix_improvement_opportunity_organization_id'), table_name='improvement_opportunity')
    op.drop_table('improvement_opportunity')
    op.drop_table('pain_point_finding')
    op.drop_index(op.f('ix_pain_point_organization_id'), table_name='pain_point')
    op.drop_table('pain_point')
    op.drop_index(op.f('ix_finding_process_id'), table_name='finding')
    op.drop_index(op.f('ix_finding_organization_id'), table_name='finding')
    op.drop_table('finding')
    op.drop_index(op.f('ix_process_step_process_id'), table_name='process_step')
    op.drop_index(op.f('ix_process_step_organization_id'), table_name='process_step')
    op.drop_table('process_step')
    op.drop_index(op.f('ix_process_organization_id'), table_name='process')
    op.drop_table('process')
    op.execute('DROP TYPE IF EXISTS epistemic_status')
