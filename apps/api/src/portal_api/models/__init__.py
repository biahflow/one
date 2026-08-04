"""Domain models.

Importing every model here ensures they are all registered on
``Base.metadata`` for Alembic autogenerate and metadata-create.
"""

from portal_api.models.agent_event import AgentEvent
from portal_api.models.audit import AuditLog
from portal_api.models.decision import Decision
from portal_api.models.document import Document, DocumentSource
from portal_api.models.identity import MemberRole, Membership, User
from portal_api.models.meeting import Meeting
from portal_api.models.organization import Organization
from portal_api.models.project import (
    Delivery,
    DeliveryStatus,
    DeliverableState,
    DigitalEmployee,
    DigitalEmployeeStatus,
    Milestone,
    MilestoneState,
    PendingItem,
    PendingOrigin,
    PendingPriority,
    PendingState,
    PhaseDeliverable,
    PhaseState,
    Project,
    ProjectPhase,
    ProjectStatus,
)

__all__ = [
    "AgentEvent",
    "AuditLog",
    "Decision",
    "DeliverableState",
    "Delivery",
    "DeliveryStatus",
    "DigitalEmployee",
    "DigitalEmployeeStatus",
    "Document",
    "DocumentSource",
    "Meeting",
    "MemberRole",
    "Membership",
    "Milestone",
    "MilestoneState",
    "Organization",
    "PendingItem",
    "PendingOrigin",
    "PendingPriority",
    "PendingState",
    "PhaseDeliverable",
    "PhaseState",
    "Project",
    "ProjectPhase",
    "ProjectStatus",
    "User",
]
