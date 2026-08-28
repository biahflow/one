"""o link do aviso segue a rota que foi renomeada (ADR 0080)

Revision ID: 0038_notification_link_rename
Revises: 0037_engagement
Create Date: 2026-08-28

``notification.link`` é **dado gravado**, não uma rota resolvida na leitura: `fan_out`
congela a URL na linha, e o sino a renderiza como `<a href>` (ADR 0043). A ADR 0079
renomeou `/admin/funil` para `/admin/funnel` **sem redirect**, o que deixa todo aviso de
`onboarding_stuck` já gravado apontando para uma rota que responde 404.

**Por que uma migração e não um redirect.** Um redirect seria uma rota permanente para
sustentar um dado antigo — a rota morta que a decisão de renomear existe para não
deixar. A migração conserta o **dado**, que é onde o problema está, e some depois de
aplicada.

**Por que ela é segura.** O casamento é por igualdade com o literal exato que
`onboarding.alert_if_stuck` escreve (não `LIKE`, não prefixo): nenhum outro produtor
grava esse valor, e os links de cliente são `/?project=…&tab=…`, que esta fatia não
tocou — o rótulo de aba continua em português por decisão.

``UPDATE`` e não ``DROP``: nada é apagado, e a linha continua sendo a mesma linha, com o
mesmo `dedupe_key`. Roda sob ``portal_migrator``, que é isento da RLS por ser dono (a
0007 usa ``ENABLE`` e não ``FORCE`` justamente para backfill de migração funcionar).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0038_notification_link_rename'
down_revision: str | None = '0037_engagement'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_LINK = '/admin/funil'
NEW_LINK = '/admin/funnel'


def upgrade() -> None:
    op.execute(f"UPDATE notification SET link = '{NEW_LINK}' WHERE link = '{OLD_LINK}'")


def downgrade() -> None:
    op.execute(f"UPDATE notification SET link = '{OLD_LINK}' WHERE link = '{NEW_LINK}'")
