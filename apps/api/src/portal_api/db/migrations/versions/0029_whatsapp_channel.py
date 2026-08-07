"""o canal de WhatsApp: telefone, consentimento e carimbo de envio (FDD 021, ADR 0043)

Revision ID: 0029_whatsapp_channel
Revises: 0028_contact_event
Create Date: 2026-08-07

Três colunas e **nenhuma tabela nova**, que é o custo que a ADR 0012 estabeleceu
para um canal: acrescentar um canal é acrescentar um ramo de entrega, não um
domínio. O registro do que foi enviado pendura na notificação que já existe.

**O consentimento nasce desligado, ao contrário do e-mail.** `notify_by_email`
entrou na 0009 com `server_default 'true'` e o argumento estava escrito lá: quem
foi convidado para acompanhar um projeto quer saber quando ele anda. Aqui o
argumento se inverte — o número de telefone é da pessoa, não do projeto, e um
canal que chega no bolso dela exige que ela diga sim. Um `server_default 'true'`
faria toda conta existente virar destinatária no deploy, que é o modo de falha
mais caro disponível nesta fatia.

**O GRANT de coluna cresce em duas, e é o ponto inteiro.** A 0009 apertou o que a
0007 tinha deixado largo — `GRANT UPDATE` na tabela inteira permitia a alguém se
promover a `is_internal` — e deixou três colunas nomeadas. As duas novas entram na
mesma lista pela mesma razão: uma policy decide quais **linhas**, nunca quais
**colunas**, então sem esta linha "mudar minha preferência" voltaria a ser "escrever
qualquer coisa em mim". A policy `user_self_preferences` da 0009 já cobre a linha.

**`whatsapp_sent_at` é irmão de `emailed_at`, e separado dele de propósito.** São
duas entregas do mesmo aviso, e uma pode falhar sem a outra: colapsá-las num
`sent_at` faria o SMTP fora do ar cancelar o WhatsApp, e é justamente sobre isso
que a FDD 021 se apoia — "a falha do provedor não perde o aviso". Cada canal
retenta sobre o próprio nulo.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0029_whatsapp_channel'
down_revision: str | None = '0028_contact_event'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: A lista da 0009 mais as duas colunas do canal. Reescrita inteira, e não um
#: `GRANT` incremental, porque é assim que ela se lê como a resposta completa à
#: pergunta "o que o caminho de requisição escreve em `user`?".
WIDEN_USER_UPDATE = """
REVOKE UPDATE ON portal."user" FROM portal_app;
GRANT UPDATE (external_subject, notify_by_email, phone, notify_by_whatsapp, updated_at)
  ON portal."user" TO portal_app;
"""

NARROW_USER_UPDATE = """
REVOKE UPDATE ON portal."user" FROM portal_app;
GRANT UPDATE (external_subject, notify_by_email, updated_at)
  ON portal."user" TO portal_app;
"""

# `whatsapp_sent_at` **não** recebe GRANT nenhum, e as duas ausências são decisões
# diferentes. Para o `portal_system` não há o que conceder: o `roles.sql` já lhe dá
# `UPDATE` de tabela inteira por default privilege, e um `GRANT UPDATE (coluna)` por
# cima não restringe nada — só faria esta migração *parecer* dizer que ele está
# limitado a essa coluna, que é falso. Para o `portal_app` a ausência é o ponto:
# o carimbo é a afirmação de que a mensagem saiu, e quem recebe a mensagem não
# escreve o registro de tê-la recebido — a mesma regra que o `emailed_at` da 0009
# já seguia sem precisar dizer.


def _when_role_exists(role: str, *statements: str) -> str:
    """Mesma guarda das anteriores: sem ``roles.sql``, não há a quem conceder."""
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
    # Sem `server_default`: o telefone não tem valor neutro, e uma string vazia
    # seria um número que o adaptador teria de saber distinguir de um de verdade.
    op.add_column('user', sa.Column('phone', sa.String(length=32), nullable=True))
    op.add_column(
        'user',
        sa.Column(
            'notify_by_whatsapp',
            sa.Boolean(),
            server_default='false',
            nullable=False,
        ),
    )
    op.add_column(
        'notification',
        sa.Column('whatsapp_sent_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(_when_role_exists('portal_app', WIDEN_USER_UPDATE))


def downgrade() -> None:
    op.execute(_when_role_exists('portal_app', NARROW_USER_UPDATE))
    op.drop_column('notification', 'whatsapp_sent_at')
    op.drop_column('user', 'notify_by_whatsapp')
    op.drop_column('user', 'phone')
