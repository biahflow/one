"""Domain models.

Importing every model here ensures they are all registered on
``Base.metadata`` for Alembic autogenerate and metadata-create.
"""

from portal_api.models.agent_event import AgentEvent, AgentEventOutcome
from portal_api.models.ai_usage import AiModelPrice, AiUsageEvent, OrganizationAiQuota
from portal_api.models.agent_key import SCOPE_EVENTS_WRITE, AgentApiKey
from portal_api.models.audit import AuditLog
from portal_api.models.chat_rate_window import ChatRateWindow
from portal_api.models.conversation import (
    Conversation,
    ConversationMessage,
    ConversationRole,
    MessageConfidence,
    MessageFeedback,
    MessageResponder,
)
from portal_api.models.decision import Decision
from portal_api.models.document import (
    EMBEDDING_DIMENSIONS,
    Document,
    DocumentChunk,
    DocumentIngestState,
    DocumentOrigin,
    DocumentSource,
)
from portal_api.models.drive import (
    DRIVE_READONLY_SCOPE,
    DriveSyncState,
    ProjectDriveConnection,
)
from portal_api.models.financial import ProjectFinancialAssumption
from portal_api.models.identity import MemberRole, Membership, User
from portal_api.models.meeting import Meeting
from portal_api.models.notification import Notification, NotificationKind
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
    PendingItemComment,
    PendingOrigin,
    PendingPriority,
    PendingState,
    PhaseDeliverable,
    PhaseState,
    Project,
    ProjectPhase,
    ProjectStatus,
)
from portal_api.models.retention import (
    DataErasureRequest,
    ErasureState,
    OrganizationRetentionPolicy,
)

__all__ = [
    "DRIVE_READONLY_SCOPE",
    "EMBEDDING_DIMENSIONS",
    "SCOPE_EVENTS_WRITE",
    "AgentApiKey",
    "AgentEvent",
    "AgentEventOutcome",
    "AiModelPrice",
    "AiUsageEvent",
    "AuditLog",
    "ChatRateWindow",
    "Conversation",
    "ConversationMessage",
    "ConversationRole",
    "DataErasureRequest",
    "Decision",
    "DeliverableState",
    "Delivery",
    "DeliveryStatus",
    "DigitalEmployee",
    "DigitalEmployeeStatus",
    "Document",
    "DocumentChunk",
    "DocumentIngestState",
    "DocumentOrigin",
    "DocumentSource",
    "DriveSyncState",
    "ErasureState",
    "Meeting",
    "MemberRole",
    "Membership",
    "MessageConfidence",
    "MessageFeedback",
    "MessageResponder",
    "Milestone",
    "MilestoneState",
    "Notification",
    "NotificationKind",
    "Organization",
    "OrganizationAiQuota",
    "OrganizationRetentionPolicy",
    "PendingItem",
    "PendingItemComment",
    "PendingOrigin",
    "PendingPriority",
    "PendingState",
    "PhaseDeliverable",
    "PhaseState",
    "Project",
    "ProjectDriveConnection",
    "ProjectFinancialAssumption",
    "ProjectPhase",
    "ProjectStatus",
    "User",
]
