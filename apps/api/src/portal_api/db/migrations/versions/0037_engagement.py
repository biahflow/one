"""o Engagement entre a conta e o projeto (Language Map v1.1, ADR 0079)

Revision ID: 0037_engagement
Revises: 0036_deliverable_reviewed_kind
Create Date: 2026-08-28

O nível que faltava entre **Account** e **Project**. Até aqui o One ia direto de
organização para projeto, e o agrupamento que o cliente contrata — o programa —
não existia em lugar nenhum.

**A coluna em ``project`` é ``NULL``-ável, e a nulidade é significativa.** A
ontologia diz que todo Project pertence a exatamente um Engagement, e este lado
**projeta** em vez de originar: um projeto sincronizado antes de o Biahflow
mandar a chave não tem engagement, e carimbar um seria fabricar dado. É a mesma
decisão de ``observed_at``/``projection_version`` na 0031 e de ``archived_at`` na
0022 — ausência é ausência de afirmação, nunca um valor de aterro.

**O predicado da policy do ``portal_app`` é o de ``project``, não o de tenant, e
isso foi medido.** A forma óbvia seria ``organization_id = portal.current_org()``,
que é o que ``document_chunk`` e ``pending_item`` usam. Ela devolveria **zero
linhas em ``GET /api/v1/me``**: ``access.visible_projects`` documenta que
deliberadamente *não* fixa tenant — a listagem atravessa projetos enquanto as
GUCs de segundo estágio guardam exatamente um —, então o nome do engagement seria
sempre nulo justamente na rota que alimenta o seletor da tela.

O predicado é o de ``project_member_read`` (0007) **transposto para o programa**:
vínculo organizacional (``project_id IS NULL``) alcança todo engagement da conta;
vínculo escopado a um projeto alcança só o engagement **daquele** projeto. A
tentação era parar em ``organization_member_read``, que é uma linha mais curta e
diz apenas "há vínculo com esta organização" — e é **larga demais aqui**: numa
conta com dois programas, quem foi convidado para um projeto passaria a ler o nome
do outro programa, que é exatamente a distinção que a 0007 se deu ao trabalho de
fazer entre projetos. A regra é que a segunda barreira não seja mais frouxa que a
primeira: ``visible_projects`` só alcança o engagement por um projeto visível, e a
policy diz a mesma coisa.

A subconsulta em ``project`` não recursa: a policy de ``project`` consulta
``membership``, cuja policy é GUC pura, sem subconsulta (0007 §5).

**Nenhuma escrita para ``portal_app``.** O engagement nasce do snapshot sob
``portal_system`` (``BYPASSRLS``), como fase e entregável: o portal não origina
status (ADR 0006/0008). O papel de requisição fica com o ``SELECT`` que as
*default privileges* do ``roles.sql`` já dão, e a linha explícita abaixo é o que
ela **não** contém, no argumento escrito na 0035.

``portal_admin`` ganha leitura pela GUC de terceiro estágio, como ``project`` na
0008: as telas de ``/admin`` são escopadas por organização e precisam saber de
qual programa cada projeto é.

O ``ondelete='SET NULL'`` é decisão e não default: apagar o programa não pode
apagar o projeto do cliente — ele volta a não ter agrupamento, que é o estado de
toda linha anterior a esta migração.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0037_engagement'
down_revision: str | None = '0036_deliverable_reviewed_kind'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Ver o docstring: o predicado do papel de requisição é o de `organization`
# (vínculo), não o de tenant (GUC de organização), porque `GET /me` não fixa
# tenant e é lá que este dado é lido.
POLICIES = """
CREATE POLICY engagement_member_read ON engagement
  FOR SELECT TO portal_app
  USING (EXISTS (
    SELECT 1 FROM membership m
     WHERE m.user_id = portal.current_user_id()
       AND m.organization_id = engagement.organization_id
       AND (m.project_id IS NULL
            OR EXISTS (SELECT 1 FROM project p
                        WHERE p.id = m.project_id
                          AND p.engagement_id = engagement.id))));
"""

ADMIN_POLICIES = """
CREATE POLICY engagement_admin_read ON engagement
  FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());

GRANT SELECT ON portal.engagement TO portal_admin;
"""

# A ausência de INSERT/UPDATE/DELETE é o controle, não um esquecimento.
GRANTS = """
GRANT SELECT ON portal.engagement TO portal_app;
"""


def _when_role_exists(role: str, *statements: str) -> str:
    """Mesma guarda de 0007/0008/0012/0015/0021/0035: sem ``roles.sql``, não há a quem conceder."""
    body = "\n".join(statements)
    return f"""
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
            RAISE NOTICE '{role} is absent; skipping the engagement grants (run roles.sql)';
            RETURN;
          END IF;
          EXECUTE $sql${body}$sql$;
        END
        $do$;
    """


def upgrade() -> None:
    op.create_table(
        'engagement',
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column(
            'status',
            sa.Enum('active', 'paused', 'closed', name='engagement_status'),
            nullable=False,
        ),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_engagement_organization_id_organization'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_engagement')),
        sa.UniqueConstraint('organization_id', 'slug', name='uq_engagement_organization_slug'),
    )
    op.create_index(op.f('ix_engagement_organization_id'), 'engagement', ['organization_id'], unique=False)

    op.add_column('project', sa.Column('engagement_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_project_engagement_id'), 'project', ['engagement_id'], unique=False)
    op.create_foreign_key(
        op.f('fk_project_engagement_id_engagement'),
        'project',
        'engagement',
        ['engagement_id'],
        ['id'],
        ondelete='SET NULL',
    )

    op.execute('ALTER TABLE engagement ENABLE ROW LEVEL SECURITY')
    op.execute(POLICIES)
    op.execute(_when_role_exists('portal_app', GRANTS))
    op.execute(_when_role_exists('portal_admin', ADMIN_POLICIES))


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            'portal_admin',
            'DROP POLICY IF EXISTS engagement_admin_read ON engagement;',
            'REVOKE ALL ON portal.engagement FROM portal_admin;',
        )
    )
    op.execute(
        _when_role_exists(
            'portal_app',
            'REVOKE ALL ON portal.engagement FROM portal_app;',
        )
    )
    op.execute('DROP POLICY IF EXISTS engagement_member_read ON engagement')
    op.drop_constraint(op.f('fk_project_engagement_id_engagement'), 'project', type_='foreignkey')
    op.drop_index(op.f('ix_project_engagement_id'), table_name='project')
    op.drop_column('project', 'engagement_id')
    op.drop_index(op.f('ix_engagement_organization_id'), table_name='engagement')
    op.drop_table('engagement')
    op.execute('DROP TYPE engagement_status')
