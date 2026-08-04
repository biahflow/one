"""row-level security scoped by the per-transaction tenant context

Revision ID: 0007_rls_tenant_context
Revises: 0006_portal_sync_fields
Create Date: 2026-08-04

Adds the second isolation barrier promised by ADR 0002: until now org/project
scoping lived only in ``TenantScopedRepository``, so any raw ``select()`` — and
``biahflow.build_dashboard`` is exactly that — was unscoped.

The policies read their scope from GUCs published by ``db.session`` inside the
transaction (``portal.subject``, ``portal.user_id``, ``portal.organization_id``,
``portal.project_id``). ``current_setting(..., true)`` yields NULL when a GUC was
never set, the predicate is then NULL rather than TRUE, and the row is filtered
out — missing context returns zero rows instead of everything.

``ENABLE``, deliberately not ``FORCE``: FORCE only extends RLS to the table
*owner*, and would stop ``portal_migrator`` from running data backfills in later
migrations — an ``UPDATE`` would silently touch zero rows. The role separation in
``infra/postgres/bootstrap/roles.sql`` is what actually makes the policies bite,
since ``portal_app`` is neither superuser nor owner.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0007_rls_tenant_context'
down_revision: str | None = '0006_portal_sync_fields'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Denormalized organization_id + project_id (TenantMixin exists for this): the
# predicate is a plain column comparison, no subquery.
PROJECT_SCOPED_TABLES = (
    'milestone',
    'delivery',
    'pending_item',
    'project_phase',
    'phase_deliverable',
    'digital_employee',
    'document',
    'meeting',
    'decision',
    'agent_event',
)

# The portal never originates status (ADR 0006/0008): it mirrors Biahflow. The
# one exception is the pendência the chat opens on a context gap (ADR 0007).
APP_WRITABLE_TABLES = ('pending_item',)


def upgrade() -> None:
    # 1. Context accessors. STABLE (not IMMUTABLE — the value varies per
    # transaction) and never SECURITY DEFINER: they read only GUCs.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION portal.current_subject() RETURNS text
          LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('portal.subject', true), '') $$;

        CREATE OR REPLACE FUNCTION portal.current_email() RETURNS text
          LANGUAGE sql STABLE AS
        $$ SELECT lower(nullif(current_setting('portal.email', true), '')) $$;

        CREATE OR REPLACE FUNCTION portal.current_user_id() RETURNS uuid
          LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('portal.user_id', true), '')::uuid $$;

        CREATE OR REPLACE FUNCTION portal.current_org() RETURNS uuid
          LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('portal.organization_id', true), '')::uuid $$;

        CREATE OR REPLACE FUNCTION portal.current_project() RETURNS uuid
          LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('portal.project_id', true), '')::uuid $$;
        """
    )

    # 2. Project-scoped read model.
    for table in PROJECT_SCOPED_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_read ON "{table}" FOR SELECT
              USING (organization_id = portal.current_org()
                 AND project_id = portal.current_project())
            """
        )
    for table in APP_WRITABLE_TABLES:
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_insert ON "{table}" FOR INSERT
              WITH CHECK (organization_id = portal.current_org()
                      AND project_id = portal.current_project())
            """
        )

    # 3. project — read *before* the organization is known (access.py resolves
    # the project first), so this cannot use the org GUC. Mirrors
    # MembershipRepository.roles_for_project: direct membership or org-wide.
    # Consequence: session.get(Project, ...) returns None for a non-member, and
    # access.py already turns None into 404 — "404, never 403" preserved by RLS.
    op.execute('ALTER TABLE project ENABLE ROW LEVEL SECURITY')
    op.execute(
        """
        CREATE POLICY project_member_read ON project FOR SELECT
          USING (EXISTS (
            SELECT 1 FROM membership m
             WHERE m.user_id = portal.current_user_id()
               AND m.organization_id = project.organization_id
               AND (m.project_id = project.id OR m.project_id IS NULL)))
        """
    )

    # 4. organization — covers session.get(Organization, ...) in /me/dashboard.
    op.execute('ALTER TABLE organization ENABLE ROW LEVEL SECURITY')
    op.execute(
        """
        CREATE POLICY organization_member_read ON organization FOR SELECT
          USING (EXISTS (
            SELECT 1 FROM membership m
             WHERE m.user_id = portal.current_user_id()
               AND m.organization_id = organization.id))
        """
    )

    # 5. membership — GUC only, no subquery. This is what keeps the policies on
    # project and organization (which do subquery membership) from recursing.
    op.execute('ALTER TABLE membership ENABLE ROW LEVEL SECURITY')
    op.execute(
        """
        CREATE POLICY membership_self_read ON membership FOR SELECT
          USING (user_id = portal.current_user_id())
        """
    )

    # 6. user — the three branches that let first-login provisioning happen
    # under the unprivileged role. INSERT is limited to the row matching the
    # verified subject; UPDATE only claims a seeded row that has no subject yet.
    op.execute('ALTER TABLE "user" ENABLE ROW LEVEL SECURITY')
    op.execute(
        """
        CREATE POLICY user_self_read ON "user" FOR SELECT
          USING (external_subject = portal.current_subject()
              OR id = portal.current_user_id()
              OR (external_subject IS NULL AND lower(email) = portal.current_email()));

        CREATE POLICY user_self_provision ON "user" FOR INSERT
          WITH CHECK (external_subject = portal.current_subject()
                  AND lower(email) = portal.current_email());

        CREATE POLICY user_self_link ON "user" FOR UPDATE
          USING (external_subject IS NULL AND lower(email) = portal.current_email())
          WITH CHECK (external_subject = portal.current_subject()
                  AND lower(email) = portal.current_email());
        """
    )

    # 7. audit_log — append-only for the app: it writes and cannot read back.
    op.execute('ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY')
    op.execute(
        """
        CREATE POLICY audit_log_tenant_insert ON audit_log FOR INSERT
          WITH CHECK (organization_id = portal.current_org())
        """
    )

    # 8. Grants. RLS does not replace GRANT — they are independent gates, and
    # keeping both narrow means a mistake in one is still caught by the other.
    # Guarded so `alembic upgrade` still works where roles.sql never ran.
    op.execute(
        """
        DO $$
        DECLARE
          t text;
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'portal_app') THEN
            RAISE NOTICE 'portal_app is absent; skipping grants (run roles.sql)';
            RETURN;
          END IF;

          FOREACH t IN ARRAY ARRAY[
            'organization', 'project', 'membership', 'milestone', 'delivery',
            'pending_item', 'project_phase', 'phase_deliverable',
            'digital_employee', 'document', 'meeting', 'decision', 'agent_event'
          ] LOOP
            EXECUTE format('GRANT SELECT ON portal.%I TO portal_app', t);
          END LOOP;

          GRANT SELECT, INSERT ON portal.pending_item TO portal_app;
          GRANT SELECT, INSERT, UPDATE ON portal."user" TO portal_app;
          GRANT INSERT ON portal.audit_log TO portal_app;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
          p record;
        BEGIN
          FOR p IN SELECT schemaname, tablename, policyname FROM pg_policies
                    WHERE schemaname = 'portal' LOOP
            EXECUTE format('DROP POLICY %I ON %I.%I', p.policyname, p.schemaname, p.tablename);
          END LOOP;
        END
        $$;
        """
    )
    for table in (
        *PROJECT_SCOPED_TABLES,
        'project',
        'organization',
        'membership',
        'user',
        'audit_log',
    ):
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')

    op.execute(
        """
        DROP FUNCTION IF EXISTS portal.current_subject();
        DROP FUNCTION IF EXISTS portal.current_email();
        DROP FUNCTION IF EXISTS portal.current_user_id();
        DROP FUNCTION IF EXISTS portal.current_org();
        DROP FUNCTION IF EXISTS portal.current_project();
        """
    )
