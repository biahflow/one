"""o time interno lê o sinal do assistente, e não a pergunta (Fase 6, ADR 0030)

Revision ID: 0020_assistant_signal_read
Revises: 0019_search_text_index
Create Date: 2026-08-06

Nenhuma tabela e nenhuma coluna: uma policy e um GRANT, e a forma dos dois **é**
a decisão desta fatia.

O feedback do chat é gravado desde a ADR 0015 e ninguém nunca o leu — hoje há
seis avaliações no banco local, todas ``not_helpful``, e o único caminho até
elas é o histórico da própria pessoa que avaliou. A ADR 0015 adiou a tela com o
argumento de que "sem dado acumulado ela mostraria zero"; o dado acumulou.

Mas ``conversation_message`` é uma das duas tabelas cuja linha pertence a uma
**pessoa** (a outra é ``notification``), e todas as suas policies são
``TO portal_app`` com ``user_id = portal.current_user_id()``. Ler a conversa de
outra pessoa é decisão de privacidade, não de conveniência: a pergunta do
cliente é conteúdo confidencial dele (``docs/data-classification.md``), e
``ai/service.py`` já se recusa a pôr essa pergunta no ``audit_log`` por esse
motivo exato.

Daí as duas metades, e por que são duas:

* **A policy decide quais linhas** — as da organização que o chamador
  administra, pela GUC de terceiro estágio, como todo o resto de ``admin.py``.
* **O GRANT de coluna decide quais colunas**, porque uma policy não sabe fazer
  isso. É o idioma que ``notification`` e ``user`` já usam nesta base, e aqui
  ele carrega o produto inteiro: ``text`` **fica de fora**.

O que o time interno passa a ler é a calibragem (``confidence``, ``responder``,
``model``, ``prompt_version``), se o turno abriu pendência, e o
``feedback_comment`` — que é a nota que o cliente **escolheu** escrever para
quem o atende. O que ele perguntou continua sendo dele.

``citations`` também fica de fora, e vale o registro: ela guarda rótulo de
documento e página, que o time já vê em ``/admin/conhecimento``; o que ela
acrescentaria aqui é *quais trechos foram mostrados àquela pessoa*, que é a
pergunta de novo por outro ângulo. Se um dia a calibragem precisar disso, é
outra ADR e não um GRANT a mais.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0020_assistant_signal_read'
down_revision: str | None = '0019_search_text_index'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


POLICIES = """
CREATE POLICY conversation_admin_read ON conversation
  FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());

CREATE POLICY conversation_message_admin_read ON conversation_message
  FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());
"""

# O REVOKE vem primeiro, e **sem ele o resto desta migração não restringe nada**.
#
# Medido, não deduzido: `roles.sql` faz
# `ALTER DEFAULT PRIVILEGES ... GRANT SELECT ON TABLES TO portal_admin`, então o
# papel já nascia com SELECT de **tabela** em tudo — `text` e `citations`
# inclusive. Um `GRANT SELECT (colunas)` por cima é aditivo: não tira o que já
# estava lá.
#
# O que impedia a leitura até aqui era a **ausência de policy**, não o
# privilégio. Isso significa que qualquer policy `TO portal_admin` criada nestas
# tabelas — inclusive a desta migração, se ela parasse no GRANT — teria aberto a
# pergunta do cliente no mesmo commit. A ordem REVOKE→GRANT é o que faz a lista
# de colunas ser um teto e não um enfeite.
#
# Enumeradas uma a uma de propósito: a lista explícita transforma "o time
# interno pode ler isto?" numa linha de diff que alguém aprova.
GRANTS = """
REVOKE SELECT ON portal.conversation_message FROM portal_admin;
REVOKE SELECT ON portal.conversation FROM portal_admin;

GRANT SELECT (
  id, organization_id, project_id, conversation_id, user_id, ordinal, role,
  confidence, pending_item_id, prompt_version, responder, model,
  feedback, feedback_comment, feedback_at, created_at, updated_at
) ON portal.conversation_message TO portal_admin;

-- Sem `title`, e esta é a exclusão que quase passou: o título da thread é
-- derivado da **primeira pergunta** (`conversations._title_from`), então
-- concedê-lo entregaria pela porta dos fundos exatamente o que a exclusão de
-- `text` existe para impedir. A coluna óbvia de barrar era `text`; a que teria
-- vazado assim mesmo era esta.
GRANT SELECT (
  id, organization_id, project_id, user_id, last_message_at, created_at, updated_at
) ON portal.conversation TO portal_admin;
"""


def _when_role_exists(statements: str) -> str:
    """Mesma guarda de 0007/0008/0009/0012: sem ``roles.sql``, não há a quem conceder."""
    return f"""
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'portal_admin') THEN
            RAISE NOTICE 'portal_admin is absent; skipping the assistant-signal grants (run roles.sql)';
            RETURN;
          END IF;
          EXECUTE $sql${statements}$sql$;
        END
        $do$;
    """


def upgrade() -> None:
    op.execute(POLICIES)
    op.execute(_when_role_exists(GRANTS))


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS conversation_admin_read ON conversation;")
    op.execute(
        "DROP POLICY IF EXISTS conversation_message_admin_read ON conversation_message;"
    )
    op.execute(
        _when_role_exists(
            """
            REVOKE ALL (text) ON portal.conversation_message FROM portal_admin;
            REVOKE SELECT ON portal.conversation_message FROM portal_admin;
            REVOKE SELECT ON portal.conversation FROM portal_admin;
            """
        )
    )
