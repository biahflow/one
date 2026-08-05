"""varredura do arquivo antes de ele virar índice (Fase 5, ADR 0017)

Revision ID: 0014_document_scan
Revises: 0013_drive_connector
Create Date: 2026-08-05

Duas coisas, e a segunda é mais barata do que a 0013 fazia supor.

**1. ``document_scan_state``, um tipo novo.** É eixo próprio e não mais um valor
em ``document_ingest_state`` porque as duas colunas respondem perguntas
diferentes — "este arquivo é seguro" e "este arquivo virou texto citável" — e o
mesmo documento pode ser ``clean`` e ``failed`` ao mesmo tempo. Juntá-las
tornaria uma revarredura (assinatura nova sobre arquivo antigo) inexprimível.

O ``server_default`` é ``skipped`` e não ``clean``: as linhas que já existem
foram indexadas antes de existir varredura, e carimbá-las de "limpo" seria o
banco afirmar o que ninguém verificou. ``pending`` também não serve — mandaria
todo o acervo para uma fila de revarredura que esta migração não pede e que o
worker trataria como trabalho novo.

**2. ``rejected`` em ``document_ingest_state``, por ``ADD VALUE``.** A 0013
precisou recriar ``document_origin`` inteiro, com reescrita da tabela sob
``ACCESS EXCLUSIVE``, e vale registrar por que aqui não: a restrição do Postgres
é sobre **usar** um valor adicionado antes de a transação fechar, não sobre
adicioná-lo. Lá o índice parcial criado logo abaixo usava ``'drive'``; aqui nada
nesta migração menciona ``'rejected'`` — quem vai escrevê-lo é o worker, muito
depois do commit. Então o caminho barato é o correto, e a tabela não é reescrita.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0014_document_scan'
down_revision: str | None = '0013_drive_connector'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    scan_state = postgresql.ENUM(
        'pending', 'clean', 'infected', 'skipped', 'error', name='document_scan_state'
    )
    scan_state.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'document',
        sa.Column(
            'scan_state',
            postgresql.ENUM(
                'pending',
                'clean',
                'infected',
                'skipped',
                'error',
                name='document_scan_state',
                create_type=False,
            ),
            server_default='skipped',
            nullable=False,
        ),
    )
    op.add_column('document', sa.Column('scan_error', sa.Text(), nullable=True))
    op.add_column(
        'document', sa.Column('scanned_at', sa.DateTime(timezone=True), nullable=True)
    )

    op.execute("ALTER TYPE document_ingest_state ADD VALUE IF NOT EXISTS 'rejected'")


def downgrade() -> None:
    op.drop_column('document', 'scanned_at')
    op.drop_column('document', 'scan_error')
    op.drop_column('document', 'scan_state')
    op.execute('DROP TYPE IF EXISTS document_scan_state')

    # Tirar um valor de enum exige recriar o tipo — e antes disso reassentar as
    # linhas que o usam, senão o `USING` falha na primeira delas. `failed` é o
    # destino honesto: o documento de fato não virou índice, e o motivo continua
    # legível em `ingest_error`.
    op.execute(
        "UPDATE document SET ingest_state = 'failed' WHERE ingest_state = 'rejected'"
    )
    op.execute('ALTER TYPE document_ingest_state RENAME TO document_ingest_state_old')
    op.execute(
        "CREATE TYPE document_ingest_state AS ENUM "
        "('pending', 'indexed', 'failed', 'unsupported')"
    )
    op.execute("ALTER TABLE document ALTER COLUMN ingest_state DROP DEFAULT")
    op.execute(
        'ALTER TABLE document ALTER COLUMN ingest_state TYPE document_ingest_state '
        'USING ingest_state::text::document_ingest_state'
    )
    op.execute("ALTER TABLE document ALTER COLUMN ingest_state SET DEFAULT 'pending'")
    op.execute('DROP TYPE document_ingest_state_old')
