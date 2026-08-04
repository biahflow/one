"""Integration tests for the tenant-scoped repositories.

These prove the ADR 0002 application-layer isolation: a repository bound to one
organization/project never reads or writes another tenant's rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from portal_api.models import (
    AgentEvent,
    Decision,
    Document,
    DocumentSource,
    Meeting,
    MemberRole,
    Membership,
    Milestone,
    PendingItem,
    PendingState,
    Project,
    ProjectStatus,
    User,
)
from portal_api.repositories import (
    AgentEventRepository,
    DecisionRepository,
    DocumentRepository,
    MeetingRepository,
    MembershipRepository,
    MilestoneRepository,
    OrganizationRepository,
    PendingItemRepository,
    TenantContext,
)
from portal_api.repositories.organization import Organization

pytestmark = pytest.mark.integration


def _make_org(session: Session, slug: str) -> Organization:
    org = Organization(name=slug.title(), slug=slug)
    session.add(org)
    session.flush()
    return org


def _make_project(session: Session, org: Organization, slug: str) -> Project:
    project = Project(
        organization_id=org.id,
        name=slug.title(),
        slug=slug,
        status=ProjectStatus.in_implementation,
    )
    session.add(project)
    session.flush()
    return project


@pytest.fixture
def two_tenants(db_session: Session):
    org_a = _make_org(db_session, f"acme-{uuid.uuid4().hex[:8]}")
    org_b = _make_org(db_session, f"globex-{uuid.uuid4().hex[:8]}")
    project_a = _make_project(db_session, org_a, f"finance-{uuid.uuid4().hex[:8]}")
    project_b = _make_project(db_session, org_b, f"ops-{uuid.uuid4().hex[:8]}")
    return org_a, org_b, project_a, project_b


def test_add_stamps_tenant_keys_from_context(db_session: Session, two_tenants) -> None:
    org_a, _, project_a, _ = two_tenants
    ctx = TenantContext(organization_id=org_a.id, project_id=project_a.id)
    repo = MilestoneRepository(db_session, ctx)

    # Instance created with no tenant keys; add() must stamp them.
    milestone = repo.add(Milestone(title="Kickoff"))

    assert milestone.organization_id == org_a.id
    assert milestone.project_id == project_a.id


def test_list_is_isolated_to_the_context_tenant(db_session: Session, two_tenants) -> None:
    org_a, org_b, project_a, project_b = two_tenants

    repo_a = MilestoneRepository(
        db_session, TenantContext(org_a.id, project_a.id)
    )
    repo_b = MilestoneRepository(
        db_session, TenantContext(org_b.id, project_b.id)
    )
    repo_a.add(Milestone(title="A-only milestone"))
    repo_b.add(Milestone(title="B-only milestone"))

    titles_a = {m.title for m in repo_a.list()}
    titles_b = {m.title for m in repo_b.list()}

    assert titles_a == {"A-only milestone"}
    assert titles_b == {"B-only milestone"}


def test_get_across_tenant_returns_none(db_session: Session, two_tenants) -> None:
    """Negative permission case: a row is invisible to another tenant's repo."""
    org_a, org_b, project_a, project_b = two_tenants

    owned = MilestoneRepository(
        db_session, TenantContext(org_a.id, project_a.id)
    ).add(Milestone(title="Secret"))

    other = MilestoneRepository(db_session, TenantContext(org_b.id, project_b.id))
    assert other.get(owned.id) is None


def test_pending_item_resolution_sets_timestamp(db_session: Session, two_tenants) -> None:
    org_a, _, project_a, _ = two_tenants
    repo = PendingItemRepository(db_session, TenantContext(org_a.id, project_a.id))
    item = repo.add(PendingItem(title="Approve exception"))
    assert item.state is PendingState.open
    assert item.resolved_at is None

    repo.resolve(item)

    assert item.state is PendingState.resolved
    assert item.resolved_at is not None


def test_membership_roles_include_org_wide(db_session: Session, two_tenants) -> None:
    org_a, _, project_a, _ = two_tenants
    user = User(email="marina@acme.test", full_name="Marina", is_internal=False)
    admin = User(email="admin@portal.test", full_name="Admin", is_internal=True)
    db_session.add_all([user, admin])
    db_session.flush()

    db_session.add_all(
        [
            Membership(
                organization_id=org_a.id,
                project_id=project_a.id,
                user_id=user.id,
                role=MemberRole.client_member,
            ),
            # org-wide membership (null project) for internal admin
            Membership(
                organization_id=org_a.id,
                project_id=None,
                user_id=admin.id,
                role=MemberRole.internal_admin,
            ),
        ]
    )
    db_session.flush()

    repo = MembershipRepository(db_session, TenantContext(org_a.id))
    assert repo.roles_for_project(user.id, project_a.id) == {MemberRole.client_member}
    # Admin's org-wide role applies to any project in the org.
    assert repo.roles_for_project(admin.id, project_a.id) == {MemberRole.internal_admin}


def test_organization_lookup_by_slug(db_session: Session, two_tenants) -> None:
    org_a, _, _, _ = two_tenants
    repo = OrganizationRepository(db_session)
    assert repo.get_by_slug(org_a.slug) is not None
    assert repo.get_by_slug("does-not-exist") is None


# --- Knowledge & agent-event slice (Fase 1 data slice) ---------------------
#
# Every new project-scoped repository must prove the ADR 0002 isolation, so
# each carries its own cross-tenant negative-permission case.


def test_document_repo_stamps_and_isolates(db_session: Session, two_tenants) -> None:
    org_a, org_b, project_a, project_b = two_tenants
    repo_a = DocumentRepository(db_session, TenantContext(org_a.id, project_a.id))
    doc = repo_a.add(Document(title="Contract", source=DocumentSource.upload))

    assert doc.organization_id == org_a.id
    assert doc.project_id == project_a.id

    other = DocumentRepository(db_session, TenantContext(org_b.id, project_b.id))
    assert other.get(doc.id) is None  # negative permission: invisible cross-tenant
    assert {d.title for d in repo_a.list()} == {"Contract"}
    assert other.list() == []


def test_meeting_repo_stamps_and_isolates(db_session: Session, two_tenants) -> None:
    org_a, org_b, project_a, project_b = two_tenants
    repo_a = MeetingRepository(db_session, TenantContext(org_a.id, project_a.id))
    meeting = repo_a.add(Meeting(title="Kickoff call"))

    assert meeting.organization_id == org_a.id
    assert meeting.project_id == project_a.id

    other = MeetingRepository(db_session, TenantContext(org_b.id, project_b.id))
    assert other.get(meeting.id) is None
    assert {m.title for m in repo_a.list()} == {"Kickoff call"}


def test_decision_repo_links_meeting_and_isolates(
    db_session: Session, two_tenants
) -> None:
    org_a, org_b, project_a, project_b = two_tenants
    ctx_a = TenantContext(org_a.id, project_a.id)
    meeting = MeetingRepository(db_session, ctx_a).add(Meeting(title="Planning"))

    repo_a = DecisionRepository(db_session, ctx_a)
    decision = repo_a.add(
        Decision(title="Adopt vendor X", meeting_id=meeting.id)
    )

    assert decision.organization_id == org_a.id
    assert decision.project_id == project_a.id
    assert decision.meeting_id == meeting.id

    other = DecisionRepository(db_session, TenantContext(org_b.id, project_b.id))
    assert other.get(decision.id) is None


def _make_event(external_id: str) -> AgentEvent:
    return AgentEvent(
        event_type="ticket_resolved",
        occurred_at=datetime.now(timezone.utc),
        external_event_id=external_id,
        hours_saved=2,
    )


def test_agent_event_ingest_is_idempotent(db_session: Session, two_tenants) -> None:
    org_a, _, project_a, _ = two_tenants
    repo = AgentEventRepository(db_session, TenantContext(org_a.id, project_a.id))

    first = repo.ingest(_make_event("evt-1"))
    again = repo.ingest(_make_event("evt-1"))  # same producer id → no duplicate

    assert again.id == first.id
    assert len(repo.list()) == 1


def test_agent_event_is_isolated_across_tenants(
    db_session: Session, two_tenants
) -> None:
    org_a, org_b, project_a, project_b = two_tenants
    owned = AgentEventRepository(
        db_session, TenantContext(org_a.id, project_a.id)
    ).ingest(_make_event("evt-shared"))

    other = AgentEventRepository(db_session, TenantContext(org_b.id, project_b.id))
    assert other.get(owned.id) is None
    # Same external id in another tenant is a distinct row (uniqueness is per project).
    other_event = other.ingest(_make_event("evt-shared"))
    assert other_event.id != owned.id
