"""access administration: the write path for membership (ADR 0011)

Revision ID: 0008_admin_access_writes
Revises: 0007_rls_tenant_context
Create Date: 2026-08-04

Until now nobody could grant access: ``membership_self_read`` shows a caller only
their own rows and ``portal_app`` holds a bare ``SELECT``, so inviting someone
meant an INSERT by hand. That was the right default — the write path to the
access-control table is the last thing that should live in the request
credential — and it stays the default here. What this migration adds is a
*separate* door: the ``portal_admin`` role, still subject to RLS, whose policies
key on a third-stage GUC.

``portal.admin_organization_id`` is published by ``db.session.bind_admin_org``
**after** the caller's ``internal_admin`` membership has been verified. Before
that it is NULL, the admin predicates are NULL, and the transaction sees exactly
what any other caller would — which is what makes the verification itself
trustworthy rather than circular.

Two properties worth stating, because they are what make this safe:

* every policy below is ``TO portal_admin``. The request credential does not
  merely lack the grant — the policy does not apply to it at all, so a stray
  ``set_config`` in the request path cannot reach anything;
* the membership predicates are pure GUC comparisons, no subquery. ``project``
  and ``organization`` subquery ``membership``, so a membership policy that
  subqueried back would recurse.

Everything is inside a guard on the role existing, matching how 0007 guards its
grants: an environment that never ran ``roles.sql`` has no ``portal_admin``, and
therefore nothing here to attach the policies to.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0008_admin_access_writes'
down_revision: str | None = '0007_rls_tenant_context'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Third-stage accessors, same shape as the ones in 0007: read a GUC, NULL when
# unset. They are role-agnostic — harmless, since a GUC nobody sets stays NULL.
ACCESSORS = """
CREATE OR REPLACE FUNCTION portal.current_admin_org() RETURNS uuid
  LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('portal.admin_organization_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION portal.current_invitee() RETURNS text
  LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('portal.invitee_subject', true), '') $$;
"""

# The administered organization, in full.
MEMBERSHIP_POLICIES = """
CREATE POLICY membership_admin_read ON membership FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());

CREATE POLICY membership_admin_insert ON membership FOR INSERT TO portal_admin
  WITH CHECK (organization_id = portal.current_admin_org());

CREATE POLICY membership_admin_update ON membership FOR UPDATE TO portal_admin
  USING (organization_id = portal.current_admin_org())
  WITH CHECK (organization_id = portal.current_admin_org());

CREATE POLICY membership_admin_delete ON membership FOR DELETE TO portal_admin
  USING (organization_id = portal.current_admin_org());
"""

# Two reaches on `user`, and only two: the people who hold a membership in the
# organization being administered (that is the member list), plus the single row
# of the person currently being invited, addressed by the subject the realm just
# confirmed. The second branch is what lets an invitation find someone who
# already has an account through *another* organization — without it the insert
# would collide on the unique e-mail, and widening the first branch to "any
# e-mail" would turn the endpoint into a directory of every user of the portal.
USER_POLICIES = """
CREATE POLICY user_admin_read ON "user" FOR SELECT TO portal_admin
  USING (portal.current_admin_org() IS NOT NULL
     AND (external_subject = portal.current_invitee()
       OR EXISTS (
            SELECT 1 FROM membership m
             WHERE m.user_id = "user".id
               AND m.organization_id = portal.current_admin_org())));

CREATE POLICY user_admin_provision ON "user" FOR INSERT TO portal_admin
  WITH CHECK (portal.current_admin_org() IS NOT NULL
          AND external_subject = portal.current_invitee());

CREATE POLICY user_admin_update ON "user" FOR UPDATE TO portal_admin
  USING (portal.current_admin_org() IS NOT NULL
     AND external_subject = portal.current_invitee())
  WITH CHECK (external_subject = portal.current_invitee());
"""

# Read-only, so the endpoint can name what it is administering. The identity
# GUCs are published in the admin session too, so the member policies from 0007
# still cover the caller's own organization; these cover the administered one.
TENANT_READ_POLICIES = """
CREATE POLICY organization_admin_read ON organization FOR SELECT TO portal_admin
  USING (id = portal.current_admin_org());

CREATE POLICY project_admin_read ON project FOR SELECT TO portal_admin
  USING (organization_id = portal.current_admin_org());
"""

# Append-only, same shape as the app: writes and cannot read back.
AUDIT_POLICY = """
CREATE POLICY audit_log_admin_insert ON audit_log FOR INSERT TO portal_admin
  WITH CHECK (organization_id = portal.current_admin_org());
"""

# portal_app gains nothing here, and `test_admin_rls.py` fails the build if it
# ever does: the point of the fourth credential is that the request path cannot
# write access control.
GRANTS = """
GRANT SELECT ON portal.organization, portal.project TO portal_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON portal.membership TO portal_admin;
GRANT SELECT, INSERT, UPDATE ON portal."user" TO portal_admin;
GRANT INSERT ON portal.audit_log TO portal_admin;
"""

DROPS = """
DROP POLICY IF EXISTS audit_log_admin_insert ON audit_log;
DROP POLICY IF EXISTS project_admin_read ON project;
DROP POLICY IF EXISTS organization_admin_read ON organization;
DROP POLICY IF EXISTS user_admin_update ON "user";
DROP POLICY IF EXISTS user_admin_provision ON "user";
DROP POLICY IF EXISTS user_admin_read ON "user";
DROP POLICY IF EXISTS membership_admin_delete ON membership;
DROP POLICY IF EXISTS membership_admin_update ON membership;
DROP POLICY IF EXISTS membership_admin_insert ON membership;
DROP POLICY IF EXISTS membership_admin_read ON membership;
"""


def _when_role_exists(*statements: str) -> str:
    """Run the SQL only where ``roles.sql`` created ``portal_admin``.

    ``CREATE POLICY ... TO portal_admin`` errors out on a missing role, so the
    whole block is conditional — the same shape 0007 uses for its grants, and the
    reason a database without the bootstrap simply has no administration path.
    """
    body = "\n".join(statements)
    return f"""
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'portal_admin') THEN
            RAISE NOTICE 'portal_admin is absent; skipping the admin policies (run roles.sql)';
            RETURN;
          END IF;
          EXECUTE $sql${body}$sql$;
        END
        $do$;
    """


def upgrade() -> None:
    op.execute(ACCESSORS)
    op.execute(
        _when_role_exists(
            MEMBERSHIP_POLICIES,
            USER_POLICIES,
            TENANT_READ_POLICIES,
            AUDIT_POLICY,
            GRANTS,
        )
    )


def downgrade() -> None:
    op.execute(DROPS)
    op.execute(
        _when_role_exists(
            """
            REVOKE ALL ON portal.membership, portal."user", portal.audit_log,
                          portal.organization, portal.project
              FROM portal_admin;
            """
        )
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS portal.current_invitee();
        DROP FUNCTION IF EXISTS portal.current_admin_org();
        """
    )
