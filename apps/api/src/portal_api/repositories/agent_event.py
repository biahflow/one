"""Agent event repository (project-scoped) with idempotent ingest."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from portal_api.models import AgentEvent
from portal_api.repositories.base import TenantScopedRepository


class AgentEventRepository(TenantScopedRepository[AgentEvent]):
    model = AgentEvent

    def ingest(self, event: AgentEvent) -> tuple[AgentEvent, bool]:
        """Persist an event once per ``external_event_id`` within the tenant.

        Returns the stored row and whether this call is the one that created it.
        Re-sending the same producer event id is a no-op — the ROADMAP acceptance
        for Fase 3 — but the producer still gets told which of the two happened,
        because "my retry worked" and "my retry was ignored" are different facts
        for whoever is debugging a pipeline.

        Two barriers, in this order: the lookup below handles the ordinary
        retry, and ``uq_agent_event_external_event_id`` handles the one the
        lookup cannot — two deliveries racing, where both read "absent" before
        either wrote. On that collision we roll back to the savepoint and read
        the winner, so the loser still answers with the stored row instead of a
        500 the producer would retry forever.
        """
        existing = self._by_external_id(event.external_event_id)
        if existing is not None:
            return existing, False
        try:
            with self.session.begin_nested():
                return self.add(event), True
        except IntegrityError:
            stored = self._by_external_id(event.external_event_id)
            if stored is None:
                # A violação foi de outra constraint — não é a corrida que
                # sabemos tratar, e engolir aqui esconderia um defeito real.
                raise
            return stored, False

    def in_period(self, start: datetime, end: datetime) -> list[AgentEvent]:
        """Os eventos do tenant no intervalo ``[start, end)``.

        Meio aberto de propósito: dois períodos adjacentes não podem contar o
        mesmo evento duas vezes.
        """
        stmt = (
            select(self.model)
            .where(
                self.model.occurred_at >= start,
                self.model.occurred_at < end,
                *self._tenant_filters(),
            )
            .order_by(self.model.occurred_at)
        )
        return list(self.session.execute(stmt).scalars())

    def _by_external_id(self, external_event_id: str) -> AgentEvent | None:
        stmt = select(self.model).where(
            self.model.external_event_id == external_event_id,
            *self._tenant_filters(),
        )
        return self.session.execute(stmt).scalar_one_or_none()
