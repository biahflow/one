"""Metadata-level checks that need no database."""

from __future__ import annotations

from portal_api.db.base import Base
from portal_api.models import (
    Delivery,
    MemberRole,
    Milestone,
    PendingItem,
    Project,
)

EXPECTED_TABLES = {
    "organization",
    "user",
    "project",
    "membership",
    "milestone",
    "delivery",
    "pending_item",
    "audit_log",
}

PROJECT_SCOPED = [Milestone, Delivery, PendingItem]


def test_all_domain_tables_are_registered() -> None:
    assert EXPECTED_TABLES <= set(Base.metadata.tables)


def test_project_scoped_tables_carry_both_tenant_keys() -> None:
    for model in PROJECT_SCOPED:
        columns = model.__table__.columns
        assert "organization_id" in columns, model.__name__
        assert "project_id" in columns, model.__name__


def test_project_has_org_key_but_no_project_key() -> None:
    assert "organization_id" in Project.__table__.columns
    assert "project_id" not in Project.__table__.columns


def test_audit_log_is_append_only() -> None:
    columns = Base.metadata.tables["audit_log"].columns
    assert "created_at" in columns
    assert "updated_at" not in columns


def test_member_roles_match_the_authorization_model() -> None:
    assert {role.value for role in MemberRole} == {
        "internal_admin",
        "internal_member",
        "client_member",
    }
