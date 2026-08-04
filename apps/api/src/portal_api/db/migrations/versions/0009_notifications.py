"""notifications: fan-out por usuário, com leitura própria (ADR 0012)

Revision ID: 0009_notifications
Revises: 0008_admin_access_writes
Create Date: 2026-08-04

A primeira tabela do portal cuja linha pertence a *uma pessoa*, e não ao projeto
inteiro. Isso muda duas coisas em relação ao resto do read model:

* a policy de leitura soma o dono ao tenant (``user_id = portal.current_user_id()``),
  senão um membro veria o aviso destinado a outro dentro do mesmo projeto;
* ``portal_app`` ganha ``UPDATE``, o que até aqui só valia para ``user``. Para
  que "marcar como lida" não vire poder de reescrever título, destinatário ou
  link, o grant é **de coluna**: ``GRANT UPDATE (read_at)``. A policy sozinha não
  daria isso — ela decide *quais linhas*, nunca *quais colunas*.

Quem escreve continua sendo ``portal_system`` (BYPASSRLS), no caminho do sync:
o portal não origina status (ADR 0006/0008), só avisa que o Biahflow mudou.

Aditiva. ``user.notify_by_email`` entra com ``server_default 'true'`` — o
convidado quer saber quando o projeto anda, e a tela de Configurações é onde se
desliga.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0009_notifications'
down_revision: str | None = '0008_admin_access_writes'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NOTIFICATION_KINDS = (
    'milestone_done',
    'phase_advanced',
    'deliverable_delivered',
    'document_added',
    'meeting_scheduled',
    'transcript_ready',
    'pending_opened',
    'pending_resolved',
    'project_status_changed',
)

# Tenant *e* dono. O meta-teste em `test_rls_isolation.py` cobra a policy de toda
# tabela com organization_id; o `user_id` no predicado é o que esta tabela
# acrescenta, e `test_notifications_rls.py` é quem cobra isso.
POLICIES = """
CREATE POLICY notification_own_read ON notification FOR SELECT TO portal_app
  USING (organization_id = portal.current_org()
     AND user_id = portal.current_user_id());

CREATE POLICY notification_own_update ON notification FOR UPDATE TO portal_app
  USING (organization_id = portal.current_org()
     AND user_id = portal.current_user_id())
  WITH CHECK (organization_id = portal.current_org()
          AND user_id = portal.current_user_id());
"""

# A preferência de e-mail mora no `user`, e até aqui o caminho de requisição só
# podia tocar naquela tabela para *reivindicar* uma linha semeada
# (``user_self_link``, que exige ``external_subject IS NULL``). Uma conta já
# ligada não conseguia mudar nada de si mesma — correto enquanto não havia o que
# mudar, e insuficiente a partir de agora.
PREFERENCES_POLICY = """
CREATE POLICY user_self_preferences ON "user" FOR UPDATE TO portal_app
  USING (external_subject = portal.current_subject())
  WITH CHECK (external_subject = portal.current_subject());
"""

# Aperta o que 0007 tinha deixado largo: ``GRANT ... UPDATE ON "user"`` valia a
# tabela inteira, e a policy nova abriria junto ``email``, ``full_name`` e
# ``is_internal`` — o usuário se promovendo a interno é exatamente o tipo de
# escrita que o caminho de requisição não deve alcançar. As três colunas que
# sobram são as que ele legitimamente escreve: o `sub` na reivindicação, a
# preferência, e o carimbo que o `onupdate` do ORM leva junto.
NARROW_USER_UPDATE = """
REVOKE UPDATE ON portal."user" FROM portal_app;
GRANT UPDATE (external_subject, notify_by_email, updated_at)
  ON portal."user" TO portal_app;
"""

# Sem INSERT e sem DELETE: quem cria é o sync, sob portal_system. `updated_at`
# entra junto de `read_at` porque o `onupdate` do TimestampMixin o inclui em todo
# UPDATE — é o carimbo de que a linha mudou, não autoridade sobre o conteúdo.
GRANTS = """
GRANT SELECT ON portal.notification TO portal_app;
GRANT UPDATE (read_at, updated_at) ON portal.notification TO portal_app;
"""


def _when_role_exists(*statements: str) -> str:
    """Mesma guarda de 0007/0008: sem ``roles.sql``, não há a quem conceder."""
    body = "\n".join(statements)
    return f"""
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'portal_app') THEN
            RAISE NOTICE 'portal_app is absent; skipping the notification grants (run roles.sql)';
            RETURN;
          END IF;
          EXECUTE $sql${body}$sql$;
        END
        $do$;
    """


def upgrade() -> None:
    op.create_table(
        'notification',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.Enum(*NOTIFICATION_KINDS, name='notification_kind'), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('detail', sa.String(length=300), nullable=True),
        sa.Column('link', sa.Text(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dedupe_key', sa.String(length=255), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('emailed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name=op.f('fk_notification_organization_id_organization'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_notification_project_id_project'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_notification_user_id_user'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_notification')),
        sa.UniqueConstraint('user_id', 'dedupe_key', name='uq_notification_user_dedupe_key'),
    )
    op.create_index(op.f('ix_notification_organization_id'), 'notification', ['organization_id'], unique=False)
    op.create_index(op.f('ix_notification_project_id'), 'notification', ['project_id'], unique=False)
    op.create_index(op.f('ix_notification_user_id'), 'notification', ['user_id'], unique=False)

    op.add_column(
        'user',
        sa.Column('notify_by_email', sa.Boolean(), server_default='true', nullable=False),
    )

    op.execute('ALTER TABLE notification ENABLE ROW LEVEL SECURITY')
    op.execute(
        _when_role_exists(POLICIES, GRANTS, PREFERENCES_POLICY, NARROW_USER_UPDATE)
    )


def downgrade() -> None:
    op.execute(
        _when_role_exists(
            """
            DROP POLICY IF EXISTS user_self_preferences ON "user";
            REVOKE UPDATE ON portal."user" FROM portal_app;
            GRANT UPDATE ON portal."user" TO portal_app;
            """
        )
    )
    op.execute('DROP POLICY IF EXISTS notification_own_update ON notification')
    op.execute('DROP POLICY IF EXISTS notification_own_read ON notification')
    op.drop_column('user', 'notify_by_email')
    op.drop_index(op.f('ix_notification_user_id'), table_name='notification')
    op.drop_index(op.f('ix_notification_project_id'), table_name='notification')
    op.drop_index(op.f('ix_notification_organization_id'), table_name='notification')
    op.drop_table('notification')
    op.execute('DROP TYPE IF EXISTS notification_kind')
