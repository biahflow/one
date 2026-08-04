"""Meeting domain — recordings, transcripts and summaries per project.

Covers FDD 003: internal staff attach a recording link and paste/upload a
transcript; a summary and extracted decisions hang off it. Automatic
transcription of external recordings is out of the MVP (see PRD).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin
from portal_api.models.project import _ProjectChildMixin


class Meeting(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "meeting"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    held_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recording_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Vocabulário espelhado do Biahflow ("scheduled"/"held"), como o health do projeto:
    # string, para que uma nova opção lá não exija migração de enum aqui.
    status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # O snapshot informa só se existe transcrição — o texto não atravessa.
    has_transcript: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
