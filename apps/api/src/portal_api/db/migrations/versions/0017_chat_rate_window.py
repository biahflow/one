"""a janela do chat, por pessoa (Fase 5, ADR 0021)

Revision ID: 0017_chat_rate_window
Revises: 0016_conversation_prompt_stamp
Create Date: 2026-08-05

Uma tabela, três colunas, nenhuma policy — e cada uma dessas três ausências é
uma decisão.

**Sem ``organization_id`` e sem ``project_id``.** O limite é propriedade de uma
pessoa, como ``user``, que também não carrega tenant. Por projeto seria pior que
inútil: deixaria alguém abrir N projetos de cota, o oposto do que o controle
quer. Consequência a registrar aqui, porque quem ler depois vai procurá-la: o
meta-teste de ``test_rls_isolation.py`` **não** cobra policy desta tabela, e não
é esquecimento — ele cobra de toda tabela com ``organization_id``, e esta não
tem uma.

**RLS ligada, e nenhuma policy ``TO portal_app``.** Mesma forma de
``project_drive_connection`` e ``agent_api_key``: o papel de requisição herda
``SELECT`` das default privileges do ``roles.sql``, mas nenhuma regra se aplica
a ele, então a leitura devolve zero linhas. A regra não é sobre você. Quem lê e
escreve é ``portal_system``, em transação própria e **anterior** à do chat — se
o contador vivesse na transação do chat, um lock ficaria aberto atravessando a
chamada ao modelo, e um chat revertido devolveria cota de uma requisição que já
custou.

**Sem FK para ``user``.** A chave é o ``sub`` do OIDC, que é o que o token
carrega e o que ``portal.current_subject()`` já usa. Sem FK, a linha existe
desde a primeira requisição — inclusive antes de a pessoa ter sido
provisionada, que é exatamente quando um laço automatizado começaria.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0017_chat_rate_window'
down_revision: str | None = '0016_conversation_prompt_stamp'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SYSTEM_GRANTS = """
GRANT SELECT, INSERT, UPDATE ON portal.chat_rate_window TO portal_system;
"""


def _when_role_exists(role: str, *statements: str) -> str:
    """Roda o SQL só onde ``roles.sql`` criou o papel — mesmo formato da 0010/0015."""
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
    op.create_table(
        'chat_rate_window',
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_rate_window')),
    )
    # A unicidade vem do índice, e não de uma `UNIQUE` separada: o modelo declara
    # `unique=True, index=True` na coluna, que o SQLAlchemy reflete como índice
    # único — duas coisas fariam o `alembic check` acusar deriva a cada run.
    op.create_index(
        op.f('ix_chat_rate_window_subject'), 'chat_rate_window', ['subject'], unique=True
    )

    # Ligada sem policy: ver o docstring. `portal_app` fica com SELECT herdado e
    # zero linhas, que é o resultado pretendido.
    op.execute('ALTER TABLE chat_rate_window ENABLE ROW LEVEL SECURITY')
    op.execute(_when_role_exists('portal_system', SYSTEM_GRANTS))


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            'portal_system',
            'REVOKE ALL ON portal.chat_rate_window FROM portal_system;',
        )
    )
    op.drop_index(op.f('ix_chat_rate_window_subject'), table_name='chat_rate_window')
    op.drop_table('chat_rate_window')
