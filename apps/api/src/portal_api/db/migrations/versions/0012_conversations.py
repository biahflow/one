"""conversas persistidas, com citações e feedback (ADR 0015)

Revision ID: 0012_conversations
Revises: 0011_document_index
Create Date: 2026-08-04

A primeira escrita **nova** que ``portal_app`` ganha desde a 0009, e a única em
que o caminho de requisição *origina* o dado em vez de ler o que outro produziu.
A 0011 negou INSERT em ``document_chunk`` com o argumento de que quem pode gravar
trecho pode gravar a evidência que quer ver citada; a 0009 negou INSERT em
``notification`` porque o produtor é o sync. Aqui a pergunta é do próprio
usuário: exigir um worker para gravar o que a requisição acabou de saber trocaria
uma garantia real por uma cerimônia.

O que fica no lugar da garantia é um invariante, não um privilégio:
``conversation_message`` **nunca é fonte de recuperação**. ``ai/retrieval.py`` não
a lê, e ``test_chat_ai.py`` prova que uma frase plantada num turno anterior não
vira citação no seguinte. É isso — e não a RLS — que impede alguém de escrever a
própria evidência.

Duas coisas a RLS faz, e as duas importam:

* **dono no predicado** (``user_id = portal.current_user_id()``), como em
  ``notification``: dois clientes do mesmo projeto não leem a conversa um do
  outro;
* **feedback por GRANT de coluna.** ``portal_app`` recebe
  ``UPDATE (feedback, feedback_comment, feedback_at, updated_at)`` e nada mais. A
  pessoa avalia a resposta; não reescreve o texto nem as citações que ela
  mostrou. Uma policy decide quais *linhas*, nunca quais *colunas* — é a mesma
  razão do ``GRANT UPDATE (read_at, updated_at)`` da 0009, e é o que faz do
  histórico um registro em vez de uma alegação editável.

``last_message_at`` está fora de ``updated_at`` de propósito: marcar um feedback
não é conversar, e a lista de threads ordena pela conversa, não pelo carimbo.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0012_conversations'
down_revision: str | None = '0011_document_index'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tenant (org + projeto) *e* dono. O meta-teste de `test_rls_isolation.py` cobra
# a policy de toda tabela com organization_id; o `user_id` é o que estas duas
# acrescentam, e os casos de conversa alheia são quem cobra isso.
POLICIES = """
CREATE POLICY conversation_own_read ON conversation FOR SELECT TO portal_app
  USING (organization_id = portal.current_org()
     AND project_id = portal.current_project()
     AND user_id = portal.current_user_id());

CREATE POLICY conversation_own_insert ON conversation FOR INSERT TO portal_app
  WITH CHECK (organization_id = portal.current_org()
          AND project_id = portal.current_project()
          AND user_id = portal.current_user_id());

CREATE POLICY conversation_own_update ON conversation FOR UPDATE TO portal_app
  USING (organization_id = portal.current_org()
     AND project_id = portal.current_project()
     AND user_id = portal.current_user_id())
  WITH CHECK (organization_id = portal.current_org()
          AND project_id = portal.current_project()
          AND user_id = portal.current_user_id());

CREATE POLICY conversation_message_own_read ON conversation_message
  FOR SELECT TO portal_app
  USING (organization_id = portal.current_org()
     AND project_id = portal.current_project()
     AND user_id = portal.current_user_id());

CREATE POLICY conversation_message_own_insert ON conversation_message
  FOR INSERT TO portal_app
  WITH CHECK (organization_id = portal.current_org()
          AND project_id = portal.current_project()
          AND user_id = portal.current_user_id());

CREATE POLICY conversation_message_own_update ON conversation_message
  FOR UPDATE TO portal_app
  USING (organization_id = portal.current_org()
     AND project_id = portal.current_project()
     AND user_id = portal.current_user_id())
  WITH CHECK (organization_id = portal.current_org()
          AND project_id = portal.current_project()
          AND user_id = portal.current_user_id());
"""

# Sem DELETE: apagar conversa por organização é retenção, item da Fase 5, e
# quando chegar não será o caminho de requisição a fazê-lo. O que existe hoje é o
# CASCADE de projeto e de usuário.
#
# `updated_at` acompanha as duas colunas de escrita porque o `onupdate` do
# TimestampMixin o inclui em todo UPDATE — carimbo de que a linha mudou, não
# autoridade sobre o conteúdo.
GRANTS = """
GRANT SELECT, INSERT ON portal.conversation TO portal_app;
GRANT UPDATE (last_message_at, updated_at) ON portal.conversation TO portal_app;

GRANT SELECT, INSERT ON portal.conversation_message TO portal_app;
GRANT UPDATE (feedback, feedback_comment, feedback_at, updated_at)
  ON portal.conversation_message TO portal_app;
"""


def _when_role_exists(*statements: str) -> str:
    """Mesma guarda de 0007/0008/0009: sem ``roles.sql``, não há a quem conceder."""
    body = "\n".join(statements)
    return f"""
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'portal_app') THEN
            RAISE NOTICE 'portal_app is absent; skipping the conversation grants (run roles.sql)';
            RETURN;
          END IF;
          EXECUTE $sql${body}$sql$;
        END
        $do$;
    """


def upgrade() -> None:
    role = postgresql.ENUM('user', 'assistant', name='conversation_role')
    role.create(op.get_bind(), checkfirst=True)
    confidence = postgresql.ENUM(
        'grounded', 'insufficient_context', name='message_confidence'
    )
    confidence.create(op.get_bind(), checkfirst=True)
    feedback = postgresql.ENUM('helpful', 'not_helpful', name='message_feedback')
    feedback.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'conversation',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_conversation_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_conversation_project_id_project'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_conversation_user_id_user'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_conversation')),
    )
    op.create_index(op.f('ix_conversation_organization_id'), 'conversation', ['organization_id'], unique=False)
    op.create_index(op.f('ix_conversation_project_id'), 'conversation', ['project_id'], unique=False)
    op.create_index(op.f('ix_conversation_user_id'), 'conversation', ['user_id'], unique=False)

    op.create_table(
        'conversation_message',
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('role', postgresql.ENUM('user', 'assistant', name='conversation_role', create_type=False), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('confidence', postgresql.ENUM('grounded', 'insufficient_context', name='message_confidence', create_type=False), nullable=True),
        sa.Column('citations', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('pending_item_id', sa.UUID(), nullable=True),
        sa.Column('feedback', postgresql.ENUM('helpful', 'not_helpful', name='message_feedback', create_type=False), nullable=True),
        sa.Column('feedback_comment', sa.String(length=500), nullable=True),
        sa.Column('feedback_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.id'], name=op.f('fk_conversation_message_conversation_id_conversation'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_conversation_message_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pending_item_id'], ['pending_item.id'], name=op.f('fk_conversation_message_pending_item_id_pending_item'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_conversation_message_project_id_project'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_conversation_message_user_id_user'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_conversation_message')),
        sa.UniqueConstraint('conversation_id', 'ordinal', name='uq_conversation_message_conversation_id'),
    )
    op.create_index(op.f('ix_conversation_message_conversation_id'), 'conversation_message', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_conversation_message_organization_id'), 'conversation_message', ['organization_id'], unique=False)
    op.create_index(op.f('ix_conversation_message_project_id'), 'conversation_message', ['project_id'], unique=False)
    op.create_index(op.f('ix_conversation_message_user_id'), 'conversation_message', ['user_id'], unique=False)

    op.execute('ALTER TABLE conversation ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE conversation_message ENABLE ROW LEVEL SECURITY')
    op.execute(_when_role_exists(POLICIES, GRANTS))


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            """
            REVOKE ALL ON portal.conversation_message FROM portal_app;
            REVOKE ALL ON portal.conversation FROM portal_app;
            """
        )
    )
    op.execute(
        """
        DROP POLICY IF EXISTS conversation_message_own_update ON conversation_message;
        DROP POLICY IF EXISTS conversation_message_own_insert ON conversation_message;
        DROP POLICY IF EXISTS conversation_message_own_read ON conversation_message;
        DROP POLICY IF EXISTS conversation_own_update ON conversation;
        DROP POLICY IF EXISTS conversation_own_insert ON conversation;
        DROP POLICY IF EXISTS conversation_own_read ON conversation;
        """
    )
    op.drop_index(op.f('ix_conversation_message_user_id'), table_name='conversation_message')
    op.drop_index(op.f('ix_conversation_message_project_id'), table_name='conversation_message')
    op.drop_index(op.f('ix_conversation_message_organization_id'), table_name='conversation_message')
    op.drop_index(op.f('ix_conversation_message_conversation_id'), table_name='conversation_message')
    op.drop_table('conversation_message')
    op.drop_index(op.f('ix_conversation_user_id'), table_name='conversation')
    op.drop_index(op.f('ix_conversation_project_id'), table_name='conversation')
    op.drop_index(op.f('ix_conversation_organization_id'), table_name='conversation')
    op.drop_table('conversation')
    postgresql.ENUM(name='message_feedback').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='message_confidence').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='conversation_role').drop(op.get_bind(), checkfirst=True)
