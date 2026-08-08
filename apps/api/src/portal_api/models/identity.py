"""Identity domain — users and their project memberships."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin


class MemberRole(str, enum.Enum):
    internal_admin = "internal_admin"
    internal_member = "internal_member"
    client_member = "client_member"


class User(Base, TimestampMixin):
    __tablename__ = "user"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    # Keycloak subject; nullable until OIDC lands (Fase 1, bullet 3).
    external_subject: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    is_internal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Preferência de e-mail das notificações (Fase 2). Liga por padrão: quem foi
    # convidado para acompanhar um projeto quer saber quando ele anda; a tela de
    # Configurações é onde se desliga.
    notify_by_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # O canal de WhatsApp (Fase 7, FDD 021, ADR 0043). O telefone é da pessoa e não
    # do projeto, e é campo de **segredo para efeito de log** — `telemetry._redact`
    # o cobre pelo nome.
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Desligado por padrão, ao contrário de `notify_by_email`, e a assimetria é o
    # ponto: quem foi convidado para acompanhar um projeto quer saber quando ele
    # anda, mas um canal que chega no bolso da pessoa exige que ela diga sim. Ligado
    # por padrão, o deploy transformaria toda conta existente em destinatária.
    notify_by_whatsapp: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class Membership(Base, TimestampMixin):
    """Explicit user↔project association carrying the role.

    ``project_id`` is nullable: a null means an organization-wide role (used by
    internal staff), while client members are always bound to a project.
    """

    __tablename__ = "membership"
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_membership_user_project"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole, name="member_role"), nullable=False
    )
