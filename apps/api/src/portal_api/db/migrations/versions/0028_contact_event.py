"""o teto de frequência de contato, por pessoa (Fase 7, FDD 021 e FDD 022, ADR 0042)

Revision ID: 0028_contact_event
Revises: 0027_artifact_accepted_step
Create Date: 2026-08-07

Uma tabela que é **razão e não contador**, e a escolha contraria o precedente mais
próximo de propósito. O ``chat_rate_window`` (0017) é um contador de três colunas
porque lá subcontar sob concorrência deixa passar uma pergunta a mais num limite de
abuso; aqui subcontar deixa passar **uma mensagem a mais para uma pessoa**, que é o
dano exato que o teto existe para impedir. O argumento é o mesmo que a 0018 usou
para o razão de IA, e o docstring do próprio ``chat_limit.py`` já o tinha escrito:
"seria inaceitável para um contador de faturamento".

**Escopada por organização, e é isso que a distingue do ``chat_rate_window``.** Lá
não havia tenant e o meta-teste de ``test_rls_isolation.py`` não cobrava policy —
registro deixado naquela migração para ninguém o ler como esquecimento. Aqui há
``organization_id``, então há policy, poda por idade e exclusão à mão no apagamento
por decisão. É o preço declarado por guardar histórico em vez de um contador, e ele
se paga: a linha é comportamento de pessoa identificada, a mesma classe de dado que
a FDD 020 tratou como a mais sensível do portal.

**A policy nega, e nega por escrito.** Não há leitor: não existe tela de contatos, e
o que a FDD 021 mostra em ``/admin`` é o estado da *integração*, não o histórico da
pessoa. As tabelas anteriores sem leitor de requisição — ``agent_api_key`` (0010),
``project_drive_connection`` (0013), ``onboarding_step`` (0024) — resolveram isso
**omitindo** a policy ``TO portal_app``, o que funciona porque nenhuma regra se
aplica ao papel e a leitura devolve zero linhas. Aqui a omissão não estava
disponível: o meta-teste exige que toda tabela com ``organization_id`` tenha ao
menos uma policy, e a alternativa seria conceder ao ``portal_admin`` um ``SELECT``
que nenhuma tela consome — que é precisamente o defeito que a ADR 0033 achou (campo
publicado sem consumidor) escrito ao contrário. Então a regra existe e diz não. No
dia em que a FDD 022 ou uma tela precisar ler, ela é substituída por uma escopada,
e a substituição fica visível no diff em vez de acontecer por uma linha nova
aparecendo do nada.

Quem escreve é ``portal_system``, na transação do próprio envio.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0028_contact_event'
down_revision: str | None = '0027_artifact_accepted_step'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: A regra que diz não, em vez da omissão que dizia não por ausência. Ver o
#: docstring: aqui a omissão custaria reprovar o meta-teste, e a saída fácil —
#: conceder leitura a uma tela que não existe — é o defeito da ADR 0033 invertido.
DENY_REQUEST_PATH = """
CREATE POLICY contact_event_no_request_path ON contact_event
  FOR ALL TO portal_app, portal_admin
  USING (false) WITH CHECK (false);
"""

SYSTEM_GRANTS = """
GRANT SELECT, INSERT, DELETE ON portal.contact_event TO portal_system;
"""


def _when_role_exists(role: str, *statements: str) -> str:
    """Roda o SQL só onde ``roles.sql`` criou o papel — mesmo formato da 0010/0015/0017/0024."""
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


def _when_roles_exist(roles: Sequence[str], *statements: str) -> str:
    """A policy nomeia **dois** papéis, e o Postgres recusa a que cite um ausente.

    Os ``_when_role_exists`` anteriores guardavam blocos de um papel só. Este
    existe porque ``FOR ALL TO portal_app, portal_admin`` é uma instrução única
    que depende dos dois — e numa instalação sem ``roles.sql`` (o SQLite local,
    um banco de ensaio) ela derrubaria a migração inteira.
    """
    body = "\n".join(statements)
    checks = " OR ".join(
        f"NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}')" for role in roles
    )
    # Sem aspas no aviso: um `{roles}` cru interpola a repr da tupla Python, com
    # aspas simples dentro de um literal SQL já delimitado por aspas simples — o que
    # fecha a string no meio e produz um "syntax error at or near portal_app" que
    # não tem nada a ver com papel nenhum.
    named = ", ".join(roles)
    return f"""
        DO $do$
        BEGIN
          IF {checks} THEN
            RAISE NOTICE 'one of {named} is absent; skipping (run roles.sql)';
            RETURN;
          END IF;
          EXECUTE $sql${body}$sql$;
        END
        $do$;
    """


def upgrade() -> None:
    op.create_table(
        'contact_event',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column(
            'kind',
            sa.Enum('whatsapp_notice', name='contact_kind'),
            nullable=False,
        ),
        sa.Column('dedupe_key', sa.String(length=255), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['organization.id'],
            name=op.f('fk_contact_event_organization_id_organization'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['user.id'],
            name=op.f('fk_contact_event_user_id_user'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_contact_event')),
        sa.UniqueConstraint(
            'user_id', 'dedupe_key', name='uq_contact_event_user_dedupe_key'
        ),
    )
    op.create_index(
        op.f('ix_contact_event_organization_id'), 'contact_event', ['organization_id']
    )
    op.create_index(
        'ix_contact_event_user_created', 'contact_event', ['user_id', 'created_at']
    )

    op.execute('ALTER TABLE contact_event ENABLE ROW LEVEL SECURITY')
    op.execute(_when_roles_exist(('portal_app', 'portal_admin'), DENY_REQUEST_PATH))
    op.execute(_when_role_exists('portal_system', SYSTEM_GRANTS))


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            'portal_system', 'REVOKE ALL ON portal.contact_event FROM portal_system;'
        )
    )
    op.drop_index('ix_contact_event_user_created', table_name='contact_event')
    op.drop_index(op.f('ix_contact_event_organization_id'), table_name='contact_event')
    op.drop_table('contact_event')
    op.execute('DROP TYPE IF EXISTS contact_kind')
