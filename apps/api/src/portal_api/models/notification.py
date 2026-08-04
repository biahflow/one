"""Notification domain — the portal telling a person that something moved.

Fan-out por usuário: uma linha por destinatário, e não uma linha por evento com
uma tabela de leitura ao lado. Três razões (ADR 0012): a policy de RLS vira uma
comparação de coluna (``user_id = portal.current_user_id()``), "marcar como
lida" é um UPDATE na própria linha — coberto por um GRANT de coluna em
``read_at``, então o caminho de requisição não pode reescrever o título — e a
audiência fica no dado: um aviso pode ir só ao cliente ou só ao time interno.

O produtor é o sync do Biahflow, nunca uma escrita do portal (ADR 0006/0008): o
portal continua sem originar status, só avisa que o status mudou lá. Como o sync
**substitui** as linhas espelhadas a cada webhook, o ``dedupe_key`` é o que
impede o mesmo fato de virar notificação de novo — mesmo papel que o
``uq_agent_event_external_event_id`` cumpre para os eventos dos agentes.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin
from portal_api.models.project import _ProjectChildMixin


class NotificationKind(str, enum.Enum):
    """O que mudou. Dirige o ícone na UI e a audiência em ``notifications.py``."""

    milestone_done = "milestone_done"
    phase_advanced = "phase_advanced"
    deliverable_delivered = "deliverable_delivered"
    document_added = "document_added"
    meeting_scheduled = "meeting_scheduled"
    transcript_ready = "transcript_ready"
    pending_opened = "pending_opened"
    pending_resolved = "pending_resolved"
    project_status_changed = "project_status_changed"


class Notification(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "notification"
    __table_args__ = (
        # Idempotência: o mesmo fato, para a mesma pessoa, existe uma vez só. É o
        # que deixa o webhook ser reenviado à vontade — e ele é reenviado, porque
        # o sync é a reconciliação completa do projeto, não um delta.
        UniqueConstraint("user_id", "dedupe_key", name="uq_notification_user_dedupe_key"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[NotificationKind] = mapped_column(
        Enum(NotificationKind, name="notification_kind"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Para onde o aviso leva dentro do portal (aba, documento, gravação).
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Quando o fato aconteceu, que não é quando a linha foi criada: um webhook
    # atrasado ainda deve ordenar o aviso pela data do fato.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Carimbo do envio — é o que impede o digest de sair duas vezes se o broker
    # reentregar a task.
    emailed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
