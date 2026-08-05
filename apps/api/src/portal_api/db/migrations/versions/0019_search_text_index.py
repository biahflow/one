"""o índice que a busca lexical usa (Fase 6, ADR 0024)

Revision ID: 0019_search_text_index
Revises: 0018_ai_usage_and_quota
Create Date: 2026-08-05

Um índice, nenhuma tabela e nenhum GRANT — e as três ausências são a fatia
inteira.

**Nenhuma tabela nova**, então nenhuma policy nova: a busca lê o que já existe
(``document``, ``meeting``, ``pending_item``, ``milestone`` e
``document_chunk``), todas com policy desde a migração ``0007`` e todas
SELECT-only para ``portal_app``. É o que faz esta migração não acionar o
meta-teste de ``test_rls_isolation.py`` sem que isso seja uma dispensa.

**Nenhum GRANT**, pelo mesmo motivo: procurar é ler, e o papel de requisição já
lê estas tabelas. Uma busca que precisasse de privilégio novo estaria alcançando
alguma coisa que a tela não mostra, que é exatamente o que a ADR 0024 recusa.

**A expressão não está digitada aqui.** Ela vem de ``textfold.index_expression``,
a mesma função que ``DocumentChunk.__table_args__`` e ``search.py`` usam. Um
índice funcional só é usado quando a expressão da consulta é idêntica à dele,
caractere a caractere — e "idêntica" mantida por três cópias digitadas é a forma
de o índice parar de ser usado sem nada ficar vermelho. O ``alembic check`` cobra
que a declaração e o banco concordem; ele não teria como cobrar que a *consulta*
concorde com os dois.
"""

from collections.abc import Sequence

from alembic import op

from portal_api.textfold import index_expression

# revision identifiers, used by Alembic.
revision: str = '0019_search_text_index'
down_revision: str | None = '0018_ai_usage_and_quota'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_NAME = 'ix_document_chunk_text_fts'


def upgrade() -> None:
    op.execute(
        f'CREATE INDEX {INDEX_NAME} ON document_chunk '
        f'USING gin ({index_expression("text")})'
    )


def downgrade() -> None:
    op.execute(f'DROP INDEX {INDEX_NAME}')
