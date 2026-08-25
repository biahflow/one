"""Project domain — project spine plus milestones, deliveries and pendings."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TenantMixin, TimestampMixin


class ProjectStatus(str, enum.Enum):
    discovery = "discovery"
    in_implementation = "in_implementation"
    live = "live"
    paused = "paused"


class MilestoneState(str, enum.Enum):
    planned = "planned"
    in_progress = "in_progress"
    next = "next"
    done = "done"


class DeliveryStatus(str, enum.Enum):
    planned = "planned"
    in_progress = "in_progress"
    delivered = "delivered"


class PendingPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class PendingState(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"


class PendingOrigin(str, enum.Enum):
    """Quem criou a pendência — decide o que o sync do Biahflow pode substituir.

    ``biahflow`` são espelhadas do snapshot (replace a cada webhook); ``portal`` nascem no
    próprio portal (o chat abre uma quando falta evidência, ADR 0007) e nunca são apagadas
    pelo sync.
    """

    biahflow = "biahflow"
    portal = "portal"


class PhaseState(str, enum.Enum):
    """Estado de uma fase da jornada — dirige o "Você está aqui" e o desbloqueio."""

    locked = "locked"
    active = "active"
    done = "done"


class DeliverableState(str, enum.Enum):
    pending = "pending"
    delivered = "delivered"


class DigitalEmployeeStatus(str, enum.Enum):
    building = "building"
    active = "active"
    paused = "paused"


class _ProjectChildMixin(TenantMixin):
    """TenantMixin plus the mandatory project foreign key."""

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class Project(Base, TenantMixin, TimestampMixin):
    __tablename__ = "project"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_project_organization_slug"),
        CheckConstraint(
            "completion_percent >= 0 AND completion_percent <= 100",
            name="completion_range",
        ),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"),
        nullable=False,
        default=ProjectStatus.discovery,
    )
    completion_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # ROI projetado do Biahflow (read model). `net` é o valor em R$; `ratio` é o múltiplo
    # (receita - custo) / custo. É o ROI do próprio projeto do cliente — client-safe.
    roi_net: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    roi_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Próxima reunião agendada, denormalizada do snapshot para o dashboard.
    next_meeting_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    next_meeting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Saúde amigável vinda do Biahflow (rótulo + cor), sem score/sinais internos.
    health_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    health_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Quando o Biahflow arquivou o projeto — coluna própria, e não um valor de `ProjectStatus`,
    # porque as duas coisas são ortogonais: um projeto encerrado tinha um andamento quando
    # acabou, e `status` é justamente esse andamento. Pausado e encerrado disputando a mesma
    # coluna faria perder um dos dois. É reversível: a interface do Biahflow restaura por item,
    # e o sync devolve isto a `None` quando ela o faz (ADR 0036).
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Quando o Biahflow apagou o projeto de vez. Separada de `archived_at` porque as duas chegam
    # por portas diferentes e uma delas não tem volta: arquivamento vem **no snapshot** e o sync o
    # reescreve a cada sincronização (é assim que restaurar funciona); exclusão chega **só pelo
    # webhook**, porque depois dela não existe snapshot para consultar. Uma coluna só faria o sync
    # apagar este fato (ADR 0037).
    source_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Milestone(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "milestone"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    state: Mapped[MilestoneState] = mapped_column(
        Enum(MilestoneState, name="milestone_state"),
        nullable=False,
        default=MilestoneState.planned,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class Delivery(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "delivery"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status"),
        nullable=False,
        default=DeliveryStatus.planned,
    )


class PendingItem(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "pending_item"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    priority: Mapped[PendingPriority] = mapped_column(
        Enum(PendingPriority, name="pending_priority"),
        nullable=False,
        default=PendingPriority.medium,
    )
    state: Mapped[PendingState] = mapped_column(
        Enum(PendingState, name="pending_state"),
        nullable=False,
        default=PendingState.open,
    )
    origin: Mapped[PendingOrigin] = mapped_column(
        Enum(PendingOrigin, name="pending_origin"),
        nullable=False,
        default=PendingOrigin.portal,
        server_default=PendingOrigin.portal.value,
    )
    # Id da pendência no Biahflow, quando espelhada de lá.
    external_ref: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PendingItemComment(Base, _ProjectChildMixin, TimestampMixin):
    """O que alguém escreveu numa pendência (Fase 2, ADR 0032).

    A **terceira** tabela que o caminho de requisição origina, depois de
    ``conversation`` e ``conversation_message`` — e a primeira cujo escopo é o
    **projeto** e não a pessoa.

    A inversão é a decisão: as policies daquelas duas exigem
    ``user_id = portal.current_user_id()`` porque a conversa é de quem
    perguntou. Um comentário existe **para ser lido pelo outro lado**, então o
    predicado é o de tenant simples, como ``pending_item``, e "quem escreveu"
    fica na coluna em vez de no `WHERE`.

    Não há coluna de edição nem de remoção, e não é omissão: ``portal_app``
    recebe só ``INSERT`` (o ``SELECT`` vem do default privilege do
    ``roles.sql``), pelo argumento da ADR 0015 — quem escreve não reescreve.
    """

    __tablename__ = "pending_item_comment"

    pending_item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pending_item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Quem escreveu. ``SET NULL`` e não ``CASCADE``: revogar o acesso de alguém
    #: — ou apagar a conta — não pode reescrever a história da pendência
    #: apagando o que foi dito. A tela mostra "Participante removido" e o texto
    #: continua lá, que é o mesmo argumento do registro do expurgo (ADR 0017).
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Denormalizado no momento da escrita, pela razão acima: sem ele, um autor
    #: removido deixaria o comentário sem procedência nenhuma.
    author_label: Mapped[str] = mapped_column(String(160), nullable=False)
    #: ``True`` quando quem escreveu era da Biahflow. Guardado e não derivado
    #: do papel atual: alguém que deixa de ser interno não muda o lado de quem
    #: falou naquele dia.
    author_is_internal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    body: Mapped[str] = mapped_column(String(2000), nullable=False)


class ProjectPhase(Base, _ProjectChildMixin, TimestampMixin):
    """Fase da jornada de transformação, espelhada do Biahflow (ADR do snapshot).

    Só o vocabulário e o estado da metodologia atravessam — nada técnico. A UI do cliente
    usa `state` para o "Você está aqui" e para revelar os entregáveis fase a fase.
    """

    __tablename__ = "project_phase"

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    state: Mapped[PhaseState] = mapped_column(
        Enum(PhaseState, name="phase_state"),
        nullable=False,
        default=PhaseState.locked,
    )
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class PhaseDeliverable(Base, _ProjectChildMixin, TimestampMixin):
    """Entregável que uma fase "desbloqueia" ao concluir (read model)."""

    __tablename__ = "phase_deliverable"

    phase_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project_phase.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    state: Mapped[DeliverableState] = mapped_column(
        Enum(DeliverableState, name="deliverable_state"),
        nullable=False,
        default=DeliverableState.pending,
    )
    link: Mapped[str | None] = mapped_column(Text, nullable=True)


class DigitalEmployee(Base, _ProjectChildMixin, TimestampMixin):
    """Funcionário Digital espelhado do Biahflow — o agente de IA entregue ao cliente."""

    __tablename__ = "digital_employee"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    area: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[DigitalEmployeeStatus] = mapped_column(
        Enum(DigitalEmployeeStatus, name="digital_employee_status"),
        nullable=False,
        default=DigitalEmployeeStatus.building,
    )
    kpi_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kpi_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    hours_saved_month: Mapped[Decimal | None] = mapped_column(Numeric(10, 1), nullable=True)
    roi_month: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
