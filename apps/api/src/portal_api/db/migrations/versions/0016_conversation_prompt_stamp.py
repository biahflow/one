"""o turno guardado passa a saber quem o produziu (Fase 5, ADR 0021)

Revision ID: 0016_conversation_prompt_stamp
Revises: 0015_retention_and_erasure
Create Date: 2026-08-05

Três colunas em ``conversation_message``, todas anuláveis, todas no bloco que a
0012 abriu para o que só existe na mensagem do assistente — a pergunta é da
pessoa e nenhum prompt a produziu.

**Por que agora.** O ``prompt-policy.md`` dizia "prompts são versionados" e o
docstring de ``ai/prompt.py`` dizia "versioned prompt"; a única coisa parecida
com uma versão era um ``chat_prompt_version`` nas settings que nenhum código
lia. Uma resposta guardada não sabia qual prompt a produziu, e o
``evaluation-plan.md`` manda rodar o dataset antes de alterar modelo ou prompt —
o que exige saber o que cada resposta guardada usou.

**Por que ``responder`` tem três valores e não dois.** ``offline_fallback`` é um
fato próprio: o portal tentou o provedor, ele falhou, e a resposta saiu do
casador determinístico. Sem esse valor, "por que as respostas pioraram na
terça?" só seria respondível pelo log — que a essa altura já rodou. É a mesma
razão pela qual ``last_sync_error`` mora na linha da conexão do Drive e
``scan_state`` na linha do documento: o que a tela precisa responder não pode
depender de retenção de log.

**Anuláveis, sem ``server_default``.** As linhas que já existem foram escritas
antes de haver versão de prompt; carimbá-las com a versão de hoje seria o banco
afirmar o que ninguém verificou — a mesma escolha que a 0014 fez ao usar
``skipped`` em vez de ``clean``. ``NULL`` aqui quer dizer "anterior ao carimbo",
que é verdade.

**Nenhum GRANT novo, e isso é deliberado.** GRANT é de tabela, e ``portal_app``
já tem ``INSERT`` em ``conversation_message`` desde a 0012 — que é onde estas
colunas são escritas, uma vez, junto da linha. O ``UPDATE`` continua restrito às
quatro colunas de feedback: ninguém reescreve qual prompt produziu a resposta,
pelo mesmo motivo que ninguém reescreve as citações que ela mostrou.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0016_conversation_prompt_stamp'
down_revision: str | None = '0015_retention_and_erasure'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    responder = postgresql.ENUM(
        'offline', 'anthropic', 'offline_fallback', name='message_responder'
    )
    responder.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'conversation_message',
        sa.Column('prompt_version', sa.String(length=40), nullable=True),
    )
    op.add_column(
        'conversation_message',
        sa.Column(
            'responder',
            postgresql.ENUM(
                'offline',
                'anthropic',
                'offline_fallback',
                name='message_responder',
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        'conversation_message', sa.Column('model', sa.String(length=60), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('conversation_message', 'model')
    op.drop_column('conversation_message', 'responder')
    op.drop_column('conversation_message', 'prompt_version')
    op.execute('DROP TYPE IF EXISTS message_responder')
