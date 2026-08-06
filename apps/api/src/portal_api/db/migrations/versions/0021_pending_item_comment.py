"""comentário na pendência (Fase 2, ADR 0032)

Revision ID: 0021_pending_item_comment
Revises: 0020_assistant_signal_read
Create Date: 2026-08-06

A terceira tabela que o **caminho de requisição** origina, depois de
``conversation`` e ``conversation_message`` (0012) — e a primeira cujo escopo é o
**projeto** e não a pessoa.

A inversão é a decisão desta migração. As policies daquelas duas exigem
``user_id = portal.current_user_id()`` porque a conversa pertence a quem
perguntou; a ADR 0030, da semana passada, chegou a **revogar** privilégio para
manter isso de pé. Um comentário é o oposto: ele existe para ser lido pelo outro
lado, então o predicado é o de tenant simples, como ``pending_item``, e "quem
escreveu" fica na coluna em vez de no ``WHERE``. As duas conclusões opostas têm o
mesmo critério — a quem o texto foi endereçado.

**Sobre os GRANTs, e é onde uma migração dessas erra.** O ``roles.sql`` concede
``SELECT`` por *default privileges* a ``portal_app`` e a ``portal_admin`` em toda
tabela futura. Então:

* ``portal_app`` precisa só do **``INSERT``**. ``UPDATE``/``DELETE`` não vêm de
  graça, e é exatamente o que se quer — pelo argumento da ADR 0015, quem escreve
  não reescreve. Não há o que revogar aqui, ao contrário da 0020.
* ``portal_admin`` fica com o ``SELECT`` herdado e **nenhuma policy**, a forma de
  ``agent_api_key``: a regra não é sobre ele, então a leitura devolve zero
  linhas. As telas de ``/admin`` não precisam disso — o time interno lê o
  comentário pela tela do cliente, sob ``portal_app``, pelo vínculo org-wide que
  já tem.

O ``author_user_id`` é ``SET NULL`` e não ``CASCADE``: revogar o acesso de alguém
não pode reescrever a história da pendência apagando o que foi dito. É o motivo
de ``author_label`` e ``author_is_internal`` serem denormalizados na escrita.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0021_pending_item_comment'
down_revision: str | None = '0020_assistant_signal_read'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tenant simples, sem `user_id` no predicado — ver o docstring.
POLICIES = """
CREATE POLICY pending_item_comment_read ON pending_item_comment
  FOR SELECT TO portal_app
  USING (organization_id = portal.current_org()
     AND project_id = portal.current_project());

CREATE POLICY pending_item_comment_insert ON pending_item_comment
  FOR INSERT TO portal_app
  WITH CHECK (organization_id = portal.current_org()
          AND project_id = portal.current_project());
"""

# Só INSERT: o SELECT já vem do default privilege, e a ausência de UPDATE/DELETE
# é o controle, não um esquecimento.
GRANTS = """
GRANT INSERT ON portal.pending_item_comment TO portal_app;
"""


def _when_role_exists(role: str, *statements: str) -> str:
    """Mesma guarda de 0007/0008/0012/0015: sem ``roles.sql``, não há a quem conceder."""
    body = "\n".join(statements)
    return f"""
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
            RAISE NOTICE '{role} is absent; skipping the comment grants (run roles.sql)';
            RETURN;
          END IF;
          EXECUTE $sql${body}$sql$;
        END
        $do$;
    """


def upgrade() -> None:
    # O `kind` da notificação é um enum **do Postgres** (0009), então acrescentar
    # um valor no Python não basta — e o `alembic check` não acusaria, porque ele
    # compara tabelas e colunas, não rótulos de enum. Sem esta linha o primeiro
    # comentário gravaria e o aviso estouraria no worker, longe da causa.
    #
    # `ADD VALUE` roda dentro da transação da migração porque nada aqui **usa** o
    # valor novo; usá-lo no mesmo commit é o que o Postgres recusa.
    op.execute("ALTER TYPE notification_kind ADD VALUE IF NOT EXISTS 'pending_commented'")

    op.create_table(
        'pending_item_comment',
        sa.Column('pending_item_id', sa.UUID(), nullable=False),
        sa.Column('author_user_id', sa.UUID(), nullable=True),
        sa.Column('author_label', sa.String(length=160), nullable=False),
        sa.Column(
            'author_is_internal',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
        sa.Column('body', sa.String(length=2000), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['author_user_id'], ['user.id'], name=op.f('fk_pending_item_comment_author_user_id_user'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_pending_item_comment_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pending_item_id'], ['pending_item.id'], name=op.f('fk_pending_item_comment_pending_item_id_pending_item'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_pending_item_comment_project_id_project'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_pending_item_comment')),
    )
    op.create_index(op.f('ix_pending_item_comment_author_user_id'), 'pending_item_comment', ['author_user_id'], unique=False)
    op.create_index(op.f('ix_pending_item_comment_organization_id'), 'pending_item_comment', ['organization_id'], unique=False)
    op.create_index(op.f('ix_pending_item_comment_pending_item_id'), 'pending_item_comment', ['pending_item_id'], unique=False)
    op.create_index(op.f('ix_pending_item_comment_project_id'), 'pending_item_comment', ['project_id'], unique=False)

    op.execute('ALTER TABLE pending_item_comment ENABLE ROW LEVEL SECURITY')
    op.execute(POLICIES)
    op.execute(_when_role_exists('portal_app', GRANTS))


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            'portal_app',
            'REVOKE ALL ON portal.pending_item_comment FROM portal_app;',
        )
    )
    op.execute(
        """
        DROP POLICY IF EXISTS pending_item_comment_insert ON pending_item_comment;
        DROP POLICY IF EXISTS pending_item_comment_read ON pending_item_comment;
        """
    )
    op.drop_index(op.f('ix_pending_item_comment_project_id'), table_name='pending_item_comment')
    op.drop_index(op.f('ix_pending_item_comment_pending_item_id'), table_name='pending_item_comment')
    op.drop_index(op.f('ix_pending_item_comment_organization_id'), table_name='pending_item_comment')
    op.drop_index(op.f('ix_pending_item_comment_author_user_id'), table_name='pending_item_comment')
    op.drop_table('pending_item_comment')
