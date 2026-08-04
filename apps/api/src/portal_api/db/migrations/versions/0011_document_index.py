"""document ingestion state and the pgvector index of its chunks (ADR 0014)

Revision ID: 0011_document_index
Revises: 0010_agent_results
Create Date: 2026-08-04

O documento deixa de ser só metadado e passa a virar evidência citável:

* ``document`` ganha o estado da ingestão (``pending`` → ``indexed`` |
  ``failed`` | ``unsupported``), o hash do arquivo que foi indexado — é ele que
  faz reingestão do mesmo objeto ser no-op — e ``origin``. Este último não é
  detalhe: o sync do Biahflow apaga e recria os documentos do projeto a cada
  snapshot (ADR 0006), então sem distinguir quem originou a linha, todo arquivo
  enviado pelo portal morreria no próximo webhook. É a mesma coluna que
  ``pending_item`` ganhou na 0006, pelo mesmo motivo;
* ``document_chunk`` guarda o trecho, a localização exibida na citação e o
  vetor. A extensão ``vector`` **já existe** — é criada pelo bootstrap
  (``infra/postgres/bootstrap/roles.sql``) e pelo init do Postgres.

Sobre quem escreve o índice: ``portal_app`` fica **SELECT-only** aqui. A ADR 0013
deu INSERT ao papel de requisição na ingestão de eventos porque *aquela* rota
recebe um ``projectId`` de fora e a RLS precisava ser a segunda barreira; aqui o
tenant vem dos argumentos de uma task que só foi enfileirada por uma rota de
admin já autorizada, e quem grava é o worker sob ``portal_system``. O caminho de
requisição lê conhecimento e nunca o origina — o mesmo desenho de
``notification``.

``portal_admin`` ganha escrita em ``document`` porque a porta de entrada do
arquivo é a tela de administração, ao lado de chaves e premissas (ADR 0011/0013).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0011_document_index'
down_revision: str | None = '0010_agent_results'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 1024


def _when_role_exists(role: str, *statements: str) -> str:
    """Roda o SQL só onde ``roles.sql`` criou o papel — mesmo formato da 0008/0010."""
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
    # 1. Estado da ingestão no documento. Aditivo, com server_default: as linhas
    # que já existem vieram do snapshot e nunca foram indexadas.
    origin = postgresql.ENUM('biahflow', 'portal', name='document_origin')
    origin.create(op.get_bind(), checkfirst=True)
    ingest_state = postgresql.ENUM(
        'pending', 'indexed', 'failed', 'unsupported', name='document_ingest_state'
    )
    ingest_state.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'document',
        sa.Column(
            'origin',
            postgresql.ENUM('biahflow', 'portal', name='document_origin', create_type=False),
            nullable=False,
            server_default='biahflow',
        ),
    )
    op.add_column(
        'document',
        sa.Column(
            'ingest_state',
            postgresql.ENUM(
                'pending', 'indexed', 'failed', 'unsupported',
                name='document_ingest_state', create_type=False,
            ),
            nullable=False,
            server_default='pending',
        ),
    )
    op.add_column('document', sa.Column('ingest_error', sa.Text(), nullable=True))
    op.add_column('document', sa.Column('content_hash', sa.String(length=64), nullable=True))
    op.add_column(
        'document', sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=True)
    )

    # 2. O índice propriamente dito.
    op.create_table(
        'document_chunk',
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('location', sa.String(length=120), nullable=False),
        sa.Column('char_count', sa.Integer(), nullable=False),
        sa.Column('embedding', Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column('embedding_model', sa.String(length=80), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['document_id'], ['document.id'],
            name=op.f('fk_document_chunk_document_id_document'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organization.id'],
            name=op.f('fk_document_chunk_organization_id_organization'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['project_id'], ['project.id'],
            name=op.f('fk_document_chunk_project_id_project'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_document_chunk')),
        sa.UniqueConstraint('document_id', 'ordinal', name='uq_document_chunk_document_id'),
    )
    op.create_index(
        op.f('ix_document_chunk_document_id'), 'document_chunk', ['document_id'], unique=False
    )
    op.create_index(
        op.f('ix_document_chunk_organization_id'), 'document_chunk', ['organization_id'], unique=False
    )
    op.create_index(
        op.f('ix_document_chunk_project_id'), 'document_chunk', ['project_id'], unique=False
    )
    # HNSW com distância de cosseno: é a métrica que a recuperação usa, e um
    # índice construído para outra operação simplesmente não seria consultado.
    op.create_index(
        'ix_document_chunk_embedding',
        'document_chunk',
        ['embedding'],
        unique=False,
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'},
    )

    # 3. RLS. O meta-teste de `test_rls_isolation.py` cobra policy de toda tabela
    # com `organization_id` — é ele que impede uma tabela nova de nascer aberta.
    op.execute('ALTER TABLE document_chunk ENABLE ROW LEVEL SECURITY')
    op.execute(
        """
        CREATE POLICY document_chunk_tenant_read ON document_chunk FOR SELECT
          USING (organization_id = portal.current_org()
             AND project_id = portal.current_project())
        """
    )

    # 4. Escrita do documento pela tela de administração (ADR 0011).
    op.execute(
        _when_role_exists(
            'portal_admin',
            """
            CREATE POLICY document_admin_read ON document
              FOR SELECT TO portal_admin
              USING (organization_id = portal.current_admin_org());

            CREATE POLICY document_admin_insert ON document
              FOR INSERT TO portal_admin
              WITH CHECK (organization_id = portal.current_admin_org());

            CREATE POLICY document_admin_update ON document
              FOR UPDATE TO portal_admin
              USING (organization_id = portal.current_admin_org())
              WITH CHECK (organization_id = portal.current_admin_org());

            CREATE POLICY document_admin_delete ON document
              FOR DELETE TO portal_admin
              USING (organization_id = portal.current_admin_org());

            CREATE POLICY document_chunk_admin_read ON document_chunk
              FOR SELECT TO portal_admin
              USING (organization_id = portal.current_admin_org());

            GRANT INSERT, UPDATE, DELETE ON portal.document TO portal_admin;
            """,
        )
    )


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            'portal_admin',
            """
            REVOKE INSERT, UPDATE, DELETE ON portal.document FROM portal_admin;
            """,
        )
    )
    op.execute(
        """
        DROP POLICY IF EXISTS document_chunk_admin_read ON document_chunk;
        DROP POLICY IF EXISTS document_admin_delete ON document;
        DROP POLICY IF EXISTS document_admin_update ON document;
        DROP POLICY IF EXISTS document_admin_insert ON document;
        DROP POLICY IF EXISTS document_admin_read ON document;
        DROP POLICY IF EXISTS document_chunk_tenant_read ON document_chunk;
        """
    )
    op.drop_index('ix_document_chunk_embedding', table_name='document_chunk')
    op.drop_index(op.f('ix_document_chunk_project_id'), table_name='document_chunk')
    op.drop_index(op.f('ix_document_chunk_organization_id'), table_name='document_chunk')
    op.drop_index(op.f('ix_document_chunk_document_id'), table_name='document_chunk')
    op.drop_table('document_chunk')
    op.drop_column('document', 'indexed_at')
    op.drop_column('document', 'content_hash')
    op.drop_column('document', 'ingest_error')
    op.drop_column('document', 'ingest_state')
    op.drop_column('document', 'origin')
    postgresql.ENUM(name='document_ingest_state').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='document_origin').drop(op.get_bind(), checkfirst=True)
