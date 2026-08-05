"""conector do Google Drive: pasta autorizada por projeto (ADR 0016)

Revision ID: 0013_drive_connector
Revises: 0012_conversations
Create Date: 2026-08-04

Três coisas, e as três têm justificativa própria.

**1. ``document_origin`` ganha ``drive``.** Não é reuso de ``DocumentSource.drive``,
que já existe e quer dizer outra coisa: aquele marca o documento que o Biahflow
espelha como metadado e link, sem arquivo nenhum. Os dois falam do Drive e
significam o oposto — "existe lá" contra "veio de lá e está indexado aqui". Sem o
terceiro valor, ou o ``DELETE ... WHERE origin='biahflow'`` do ``sync_snapshot``
apagaria o conteúdo sincronizado, ou o sync do Drive apagaria o que a
administração enviou. É o mesmo argumento que criou a coluna na 0011.

O valor entra **recriando o tipo**, e não por ``ALTER TYPE ... ADD VALUE``. A
diferença é a razão de esta migração parecer mais barulhenta do que precisaria:
o Postgres aceita adicionar o valor dentro de uma transação, mas recusa **usá-lo**
antes que ela feche ("unsafe use of new value of enum type") — e o índice do item
2 usa. Como o ``env.py`` roda o upgrade inteiro numa transação só, dividir em duas
revisões não resolveria; recriar o tipo, sim, porque a restrição é sobre valor
adicionado e não sobre tipo criado. O custo é uma reescrita da tabela ``document``
sob ``ACCESS EXCLUSIVE``, aceitável no tamanho dela e declarado aqui para quem
rodar isto num banco grande saber o que esperar.

**2. Unicidade de ``(project_id, external_id)`` para o Drive.** É o que torna a
reconciliação idempotente: o arquivo é encontrado pelo id do Drive, e o banco
garante que ele não vira duas linhas quando dois syncs se cruzam.

O predicado tem de ser ``origin = 'drive'`` — comparação de enum, que é
``IMMUTABLE``. ``origin::text = 'drive'`` seria a saída óbvia para o problema do
parágrafo acima e **não funciona**: o Postgres recusa uma função não-imutável num
predicado de índice, e o cast de enum para texto é ``STABLE``. O
``__table_args__`` do modelo repete o mesmo predicado — se os dois divergirem,
``alembic check`` passa a acusar deriva a cada autogenerate.

**3. ``project_drive_connection``.** Uma linha por projeto, garantido pela tabela:
"uma pasta permitida por projeto" (FDD 003) é a fronteira em que o conector
inteiro se apoia, e duas linhas fariam "a pasta autorizada" deixar de ter
resposta.

Quem escreve é ``portal_admin`` e só ele, com o mesmo desenho de ``agent_api_key``
na 0010: policies ``TO portal_admin`` sobre ``portal.current_admin_org()``, e
``portal_app`` sem policy nenhuma — ele herda o SELECT do ``ALTER DEFAULT
PRIVILEGES`` do ``roles.sql``, mas nenhuma policy se aplica a ele, então a leitura
volta **zero linhas**. É a diferença entre "não tem permissão" e "a regra não é
sobre você", e é o que já vale para a chave de agente.

**Sem DELETE**, também como a chave de agente: desconectar limpa o segredo e
carimba ``disconnected_at``. A linha é o rastro de que a pasta esteve conectada, e
apagá-la jogaria fora a resposta a "desde quando este projeto lia aquele Drive".

O worker escreve sob ``portal_system`` (ADR 0014 §3): o tenant vem dos argumentos
de uma task enfileirada por rota de administração já autorizada, não de corpo de
requisição, então não há identificador de fora para desconfiar.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0013_drive_connector'
down_revision: str | None = '0012_conversations'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ADMIN_POLICIES = """
CREATE POLICY project_drive_connection_admin_read ON project_drive_connection
  FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());

CREATE POLICY project_drive_connection_admin_insert ON project_drive_connection
  FOR INSERT TO portal_admin
  WITH CHECK (organization_id = portal.current_admin_org());

CREATE POLICY project_drive_connection_admin_update ON project_drive_connection
  FOR UPDATE TO portal_admin
  USING (organization_id = portal.current_admin_org())
  WITH CHECK (organization_id = portal.current_admin_org());

GRANT SELECT, INSERT, UPDATE ON portal.project_drive_connection TO portal_admin;
"""


def _when_role_exists(role: str, *statements: str) -> str:
    """Roda o SQL só onde ``roles.sql`` criou o papel — mesmo formato da 0010/0011."""
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
    # 1. O terceiro valor de origem, por recriação do tipo. Ver a docstring: um
    # `ADD VALUE` deixaria o valor inutilizável até a transação fechar, e o índice
    # do passo 2 o usa.
    op.execute("ALTER TYPE document_origin RENAME TO document_origin_old")
    op.execute("CREATE TYPE document_origin AS ENUM ('biahflow', 'portal', 'drive')")
    op.execute("ALTER TABLE document ALTER COLUMN origin DROP DEFAULT")
    op.execute(
        "ALTER TABLE document ALTER COLUMN origin TYPE document_origin "
        "USING origin::text::document_origin"
    )
    op.execute("ALTER TABLE document ALTER COLUMN origin SET DEFAULT 'biahflow'")
    op.execute("DROP TYPE document_origin_old")

    # 2. Unicidade do par (projeto, id do Drive).
    op.create_index(
        'uq_document_project_id_external_id',
        'document',
        ['project_id', 'external_id'],
        unique=True,
        postgresql_where=sa.text("origin = 'drive'"),
    )

    # 3. A conexão.
    sync_state = postgresql.ENUM('idle', 'running', 'failed', name='drive_sync_state')
    sync_state.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'project_drive_connection',
        sa.Column('folder_id', sa.String(length=255), nullable=True),
        sa.Column('folder_name', sa.String(length=255), nullable=True),
        sa.Column('google_account_email', sa.String(length=320), nullable=True),
        sa.Column('refresh_token_sealed', sa.Text(), nullable=True),
        sa.Column('granted_scope', sa.Text(), nullable=True),
        sa.Column('connected_by_user_id', sa.UUID(), nullable=True),
        sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('disconnected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('oauth_state_hash', sa.String(length=64), nullable=True),
        sa.Column('oauth_state_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('oauth_code_verifier', sa.String(length=128), nullable=True),
        sa.Column('oauth_requested_by_user_id', sa.UUID(), nullable=True),
        sa.Column(
            'sync_state',
            postgresql.ENUM(
                'idle', 'running', 'failed', name='drive_sync_state', create_type=False
            ),
            server_default='idle',
            nullable=False,
        ),
        sa.Column('sync_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_error', sa.Text(), nullable=True),
        sa.Column('last_sync_stats', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['connected_by_user_id'], ['user.id'], name=op.f('fk_project_drive_connection_connected_by_user_id_user'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['oauth_requested_by_user_id'], ['user.id'], name=op.f('fk_project_drive_connection_oauth_requested_by_user_id_user'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_project_drive_connection_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_project_drive_connection_project_id_project'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_project_drive_connection')),
        sa.UniqueConstraint('project_id', name='uq_project_drive_connection_project_id'),
    )
    op.create_index(op.f('ix_project_drive_connection_organization_id'), 'project_drive_connection', ['organization_id'], unique=False)
    op.create_index(op.f('ix_project_drive_connection_project_id'), 'project_drive_connection', ['project_id'], unique=False)

    op.execute('ALTER TABLE project_drive_connection ENABLE ROW LEVEL SECURITY')
    op.execute(_when_role_exists('portal_admin', ADMIN_POLICIES))


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            'portal_admin',
            'REVOKE ALL ON portal.project_drive_connection FROM portal_admin;',
        )
    )
    op.execute(
        """
        DROP POLICY IF EXISTS project_drive_connection_admin_update ON project_drive_connection;
        DROP POLICY IF EXISTS project_drive_connection_admin_insert ON project_drive_connection;
        DROP POLICY IF EXISTS project_drive_connection_admin_read ON project_drive_connection;
        """
    )
    op.drop_index(op.f('ix_project_drive_connection_project_id'), table_name='project_drive_connection')
    op.drop_index(op.f('ix_project_drive_connection_organization_id'), table_name='project_drive_connection')
    op.drop_table('project_drive_connection')
    postgresql.ENUM(name='drive_sync_state').drop(op.get_bind(), checkfirst=True)

    op.drop_index(
        'uq_document_project_id_external_id',
        table_name='document',
        postgresql_where=sa.text("origin = 'drive'"),
    )

    # O espelho do passo 1, na ordem inversa.
    #
    # As linhas que já usam 'drive' viram 'portal': o downgrade desfaz o schema,
    # não a sincronização, e deixar a coluna com um valor que o tipo novo não tem
    # faria o `ALTER COLUMN ... TYPE` falhar no meio.
    op.execute("UPDATE document SET origin = 'portal' WHERE origin = 'drive'")
    op.execute("ALTER TYPE document_origin RENAME TO document_origin_old")
    op.execute("CREATE TYPE document_origin AS ENUM ('biahflow', 'portal')")
    op.execute("ALTER TABLE document ALTER COLUMN origin DROP DEFAULT")
    op.execute(
        "ALTER TABLE document ALTER COLUMN origin TYPE document_origin "
        "USING origin::text::document_origin"
    )
    op.execute("ALTER TABLE document ALTER COLUMN origin SET DEFAULT 'biahflow'")
    op.execute("DROP TYPE document_origin_old")
