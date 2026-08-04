"""Agent event domain — idempotent result events from the agents.

This is the persistence slice only: the table is ready to receive events with
an idempotency key so a re-sent event never duplicates. ROI/hours-saved
computation, hourly-rate versioning, per-project API-key auth and rate limiting
are Fase 3 (see ROADMAP). ``hours_saved``/``value_amount`` are stored when the
producer supplies them, but no aggregation happens here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin
from portal_api.models.project import _ProjectChildMixin


class AgentEvent(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "agent_event"
    __table_args__ = (
        # Idempotency: the same producer event id is stored once per project.
        UniqueConstraint(
            "project_id", "external_event_id", name="uq_agent_event_external_event_id"
        ),
    )

    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    hours_saved: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    value_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
