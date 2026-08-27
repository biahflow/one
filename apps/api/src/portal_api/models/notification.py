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
    #: Alguém escreveu na pendência (ADR 0032). O único aviso que **não** nasce do
    #: diff do snapshot nem de uma decisão da IA: nasce de alguém digitando.
    pending_commented = "pending_commented"
    project_status_changed = "project_status_changed"
    #: Um cliente parou num degrau do funil de onboarding (ADR 0040). O **primeiro** aviso
    #: cuja audiência é só o time interno: o cliente não deve nem saber que está sendo
    #: medido (FDD 020), e é por isso que o ``AUDIENCE`` de ``notifications.py`` ganhou uma
    #: guarda de completude no mesmo commit — o padrão daquele ``.get`` é o cliente.
    onboarding_stuck = "onboarding_stuck"
    #: O cliente respondeu a um aviso pelo WhatsApp (FDD 021, ADR 0043). Também só
    #: para o time, e por um motivo diferente do anterior: o cliente **acabou de
    #: escrever** a mensagem, e devolvê-la a ele seria contar-lhe o que ele digitou.
    #: A resposta vira aviso aqui dentro justamente para não virar conversa lá fora —
    #: "spoke, nunca hub" é o que impede o canal de esvaziar o portal.
    whatsapp_reply = "whatsapp_reply"
    #: O cliente aprovou um entregável ou pediu ajuste (FDD 027, ADR 0077). O
    #: **terceiro** aviso só do time, e por um motivo que é a soma dos dois
    #: anteriores: o cliente acabou de tomar a decisão — devolvê-la a ele seria
    #: contar-lhe o que ele mesmo decidiu — e quem precisa agir é a operação.
    #:
    #: **Uma espécie e não duas**, com a decisão no título e no ``dedupe_key``: a
    #: pergunta que o aviso responde é "o cliente revisou", e quem lê precisa dos
    #: dois desfechos na mesma fila. É a granularidade de ``pending_commented`` e
    #: não a de ``pending_opened``/``pending_resolved``, que são dois momentos da
    #: vida da mesma linha.
    deliverable_reviewed = "deliverable_reviewed"


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
    #: O mesmo carimbo para o canal de WhatsApp (FDD 021), e **coluna separada** de
    #: propósito. São duas entregas do mesmo aviso e uma pode falhar sem a outra:
    #: num carimbo só, o SMTP fora do ar cancelaria o WhatsApp — o oposto do que a
    #: FDD 021 se propõe, que é o aviso sobreviver à queda de qualquer canal porque
    #: ele já está no sino. Cada canal retenta sobre o próprio nulo.
    whatsapp_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
