"""Agent event repository (project-scoped) with idempotent ingest."""

from __future__ import annotations

from sqlalchemy import select

from portal_api.models import AgentEvent
from portal_api.repositories.base import TenantScopedRepository


class AgentEventRepository(TenantScopedRepository[AgentEvent]):
    model = AgentEvent

    def ingest(self, event: AgentEvent) -> AgentEvent:
        """Persist an event once per ``external_event_id`` within the tenant.

        Re-sending the same producer event id returns the stored row without
        inserting a duplicate (idempotency; ROADMAP Fase 3 acceptance), relying
        on the ``uq_agent_event_external_event_id`` constraint as the backstop.
        """
        existing = self._by_external_id(event.external_event_id)
        if existing is not None:
            return existing
        return self.add(event)

    def _by_external_id(self, external_event_id: str) -> AgentEvent | None:
        stmt = select(self.model).where(
            self.model.external_event_id == external_event_id,
            *self._tenant_filters(),
        )
        return self.session.execute(stmt).scalar_one_or_none()
