"""Agent event domain — idempotent result events from the agents.

An event is what an agent run *reported*, stored exactly as it was reported:
integers, in the unit the producer sent. The derived figures (hours saved in
money, ROI) are computed at read time by :mod:`portal_api.results` against the
financial assumption in force on the day of the event — never baked into the
row, because a later change to the hourly rate must not rewrite the past.

``external_event_id`` is the idempotency key: the same producer event id lands
once per project, enforced by ``uq_agent_event_external_event_id`` and checked
first by :class:`~portal_api.repositories.agent_event.AgentEventRepository`.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin
from portal_api.models.project import _ProjectChildMixin


class AgentEventOutcome(str, enum.Enum):
    """How the run ended — the ground under the accuracy and exception figures.

    ``exception_handled`` is a success with a caveat: the flow met something it
    was not designed for and dealt with it. Counting it as a failure would
    understate accuracy; counting it as a plain success would hide the
    exceptions the client is paying attention to.
    """

    success = "success"
    exception_handled = "exception_handled"
    failed = "failed"


class AgentEvent(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "agent_event"
    __table_args__ = (
        # Idempotency: the same producer event id is stored once per project.
        UniqueConstraint(
            "project_id", "external_event_id", name="uq_agent_event_external_event_id"
        ),
        # Every aggregation is "this project, this period".
        Index("ix_agent_event_project_occurred", "project_id", "occurred_at"),
    )

    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    #: Which agent produced this — free-form, agreed between producer and project.
    agent_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    outcome: Mapped[AgentEventOutcome] = mapped_column(
        Enum(AgentEventOutcome, name="agent_event_outcome"),
        nullable=False,
        default=AgentEventOutcome.success,
        server_default=AgentEventOutcome.success.value,
    )
    #: A human had to step in. Only meaningful alongside ``exception_handled``.
    human_intervention: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    #: Seconds and cents, as integers: the stored event has to equal what the
    #: agent reported, or the audit trail behind the number does not close.
    time_saved_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avoided_cost_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: Producer-side pointer to the run (log id, trace, execution url).
    run_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)

    # Legado da fatia de persistência da Fase 1, quando nada gravava aqui: foram
    # substituídas por `time_saved_seconds`/`avoided_cost_cents`, que guardam o
    # inteiro do produtor em vez de um decimal já convertido. Ficam porque
    # migração é aditiva (AGENTS.md, regra 4); a remoção é item da Fase 5.
    hours_saved: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    value_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
