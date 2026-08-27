"""o aceite do cliente, append-only e imutável por privilégio (Fase 7, FDD 027, ADR 0077)

Revision ID: 0035_deliverable_acceptance
Revises: 0034_deliverable_external_ref
Create Date: 2026-08-27

A **quarta** tabela que o caminho de requisição origina, depois de
``conversation``/``conversation_message`` (0012) e ``pending_item_comment``
(0021) — e a cópia da terceira, de propósito.

**O escopo é o projeto, não a pessoa.** As policies da conversa exigem
``user_id = portal.current_user_id()`` porque a pergunta é de quem perguntou; o
aceite é o oposto, e mais fortemente do que o comentário: ele existe para o
**outro lado** projetar. Então o predicado é o de tenant simples — organização e
projeto —, e "quem decidiu" fica na coluna. O critério é o mesmo dos três casos
anteriores: a quem o registro foi endereçado.

**Sobre os GRANTs, que são o controle inteiro desta migração.** O ``roles.sql``
concede ``SELECT`` por *default privileges* ao ``portal_app`` em toda tabela
futura, então a linha abaixo é redundante nessa metade — e ela está escrita
assim mesmo, porque o que essa linha significa é o que ela **não** contém:

* ``INSERT`` sim: o cliente origina a decisão, como origina a pergunta e o
  comentário;
* ``UPDATE`` e ``DELETE`` **não**, e não é esquecimento. É o argumento da ADR
  0015 — quem escreve não reescreve — na sua aplicação mais cara até aqui: uma
  segunda decisão do cliente **acrescenta** uma linha, e a primeira aparece
  superada na leitura em vez de apagada. Não há tela de "editar aceite" porque o
  banco a recusaria; seria funcionalidade errada, não faltando. Não há o que
  revogar aqui, ao contrário da 0020.
* ``portal_admin`` fica com o ``SELECT`` herdado e **nenhuma policy**, a forma de
  ``agent_api_key`` e de ``pending_item_comment``: a regra não é sobre ele, então
  a leitura devolve zero linhas. O time interno lê o aceite pela tela do cliente,
  sob ``portal_app``, pelo vínculo org-wide que já tem.

**O vínculo é ``deliverable_external_ref`` e não uma chave estrangeira**, e é a
razão de a 0034 existir uma migração antes: ``sync_snapshot`` apaga e recria
``phase_deliverable`` a cada webhook, então um FK ao uuid do read model seria
destruído no sync seguinte — levando junto a decisão do cliente. Pelo mesmo
motivo ``phase_name`` e ``deliverable_name`` são denormalizados: um entregável
que saia do snapshot não pode deixar o registro sem dizer sobre o quê alguém
decidiu.

**Sem unicidade, e é decisão.** Um índice único por
``(project_id, deliverable_external_ref)`` transformaria "acrescentar" em
"conflitar", que é exatamente o contrário do que a tabela é. A idempotência do
retorno ao Pulse não vem de uma constraint aqui: vem de o registro ser
append-only e imutável, de modo que reenviar é reler a mesma linha (ADR 0077 §3).

O enum tem dois valores. ``superseded``/``cancelled`` **não** entram sem revisão
de design própria, e ``done`` nunca entra: quem conclui a entrega é o lifecycle
de Delivery (ADR 0067). O One registra o evento; não conclui a fase.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0035_deliverable_acceptance'
down_revision: str | None = '0034_deliverable_external_ref'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tenant simples, sem `user_id` no predicado — ver o docstring. Cópia das
# policies de `pending_item_comment` (0021).
POLICIES = """
CREATE POLICY deliverable_acceptance_read ON deliverable_acceptance
  FOR SELECT TO portal_app
  USING (organization_id = portal.current_org()
     AND project_id = portal.current_project());

CREATE POLICY deliverable_acceptance_insert ON deliverable_acceptance
  FOR INSERT TO portal_app
  WITH CHECK (organization_id = portal.current_org()
          AND project_id = portal.current_project());
"""

# A ausência de UPDATE/DELETE é o controle, não um esquecimento.
GRANTS = """
GRANT SELECT, INSERT ON portal.deliverable_acceptance TO portal_app;
"""


def _when_role_exists(role: str, *statements: str) -> str:
    """Mesma guarda de 0007/0008/0012/0015/0021: sem ``roles.sql``, não há a quem conceder."""
    body = "\n".join(statements)
    return f"""
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
            RAISE NOTICE '{role} is absent; skipping the acceptance grants (run roles.sql)';
            RETURN;
          END IF;
          EXECUTE $sql${body}$sql$;
        END
        $do$;
    """


def upgrade() -> None:
    op.create_table(
        'deliverable_acceptance',
        sa.Column('deliverable_external_ref', sa.String(length=80), nullable=False),
        sa.Column('phase_name', sa.String(length=80), nullable=False),
        sa.Column('deliverable_name', sa.String(length=160), nullable=False),
        sa.Column(
            'action',
            sa.Enum(
                'accepted',
                'changes_requested',
                name='deliverable_acceptance_action',
            ),
            nullable=False,
        ),
        sa.Column('actor_user_id', sa.UUID(), nullable=True),
        sa.Column('actor_label', sa.String(length=160), nullable=False),
        sa.Column(
            'actor_is_internal',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
        sa.Column('comment', sa.String(length=2000), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['actor_user_id'], ['user.id'], name=op.f('fk_deliverable_acceptance_actor_user_id_user'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_deliverable_acceptance_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_deliverable_acceptance_project_id_project'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_deliverable_acceptance')),
    )
    op.create_index(op.f('ix_deliverable_acceptance_actor_user_id'), 'deliverable_acceptance', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_deliverable_acceptance_deliverable_external_ref'), 'deliverable_acceptance', ['deliverable_external_ref'], unique=False)
    op.create_index(op.f('ix_deliverable_acceptance_organization_id'), 'deliverable_acceptance', ['organization_id'], unique=False)
    op.create_index(op.f('ix_deliverable_acceptance_project_id'), 'deliverable_acceptance', ['project_id'], unique=False)

    op.execute('ALTER TABLE deliverable_acceptance ENABLE ROW LEVEL SECURITY')
    op.execute(POLICIES)
    op.execute(_when_role_exists('portal_app', GRANTS))


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            'portal_app',
            'REVOKE ALL ON portal.deliverable_acceptance FROM portal_app;',
        )
    )
    op.execute(
        """
        DROP POLICY IF EXISTS deliverable_acceptance_insert ON deliverable_acceptance;
        DROP POLICY IF EXISTS deliverable_acceptance_read ON deliverable_acceptance;
        """
    )
    op.drop_index(op.f('ix_deliverable_acceptance_project_id'), table_name='deliverable_acceptance')
    op.drop_index(op.f('ix_deliverable_acceptance_organization_id'), table_name='deliverable_acceptance')
    op.drop_index(op.f('ix_deliverable_acceptance_deliverable_external_ref'), table_name='deliverable_acceptance')
    op.drop_index(op.f('ix_deliverable_acceptance_actor_user_id'), table_name='deliverable_acceptance')
    op.drop_table('deliverable_acceptance')
    op.execute('DROP TYPE deliverable_acceptance_action')
