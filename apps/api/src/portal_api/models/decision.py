"""Decision domain — decisions recorded per project.

A decision may be extracted from a meeting (``meeting_id``); the link is
optional so decisions can also be logged directly. Uses ``SET NULL`` so
removing a meeting keeps the decision but drops the provenance link.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin
from portal_api.models.project import _ProjectChildMixin


class Decision(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "decision"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("meeting.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
