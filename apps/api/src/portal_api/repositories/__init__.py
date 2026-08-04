"""Data-access repositories.

Tenant roots (organization, user) use the plain ``Repository``; everything else
is a ``TenantScopedRepository`` bound to a :class:`TenantContext`.
"""

from portal_api.repositories.agent_event import AgentEventRepository
from portal_api.repositories.audit import AuditLogRepository
from portal_api.repositories.base import Repository, TenantScopedRepository
from portal_api.repositories.context import TenantContext
from portal_api.repositories.decision import DecisionRepository
from portal_api.repositories.delivery import DeliveryRepository
from portal_api.repositories.document import DocumentRepository
from portal_api.repositories.meeting import MeetingRepository
from portal_api.repositories.membership import MembershipRepository
from portal_api.repositories.milestone import MilestoneRepository
from portal_api.repositories.organization import OrganizationRepository, UserRepository
from portal_api.repositories.pending_item import PendingItemRepository
from portal_api.repositories.project import ProjectRepository

__all__ = [
    "AgentEventRepository",
    "AuditLogRepository",
    "DecisionRepository",
    "DeliveryRepository",
    "DocumentRepository",
    "MeetingRepository",
    "MembershipRepository",
    "MilestoneRepository",
    "OrganizationRepository",
    "PendingItemRepository",
    "ProjectRepository",
    "Repository",
    "TenantContext",
    "TenantScopedRepository",
    "UserRepository",
]
