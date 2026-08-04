"""Document domain — project knowledge sources (metadata only).

Text extraction, chunking and ``pgvector`` embeddings are Fase 4 (ADR 0004);
this table carries only the source metadata so ingestion can attach to it later.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin
from portal_api.models.project import _ProjectChildMixin


class DocumentSource(str, enum.Enum):
    upload = "upload"
    drive = "drive"
    transcript = "transcript"


class Document(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "document"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource, name="document_source"), nullable=False
    )
    # MinIO/S3 object key; null until the file is stored (Fase 4).
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Google Drive file id for synced sources.
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Link externo (Drive) vindo do snapshot do Biahflow; null quando o arquivo só existe
    # no storage do portal (Fase 4).
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Quem subiu o documento, como rótulo exibível — não é um usuário do portal.
    author_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
