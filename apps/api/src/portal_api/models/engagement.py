"""Engagement — o programa que contém os projetos de uma conta (Language Map v1.1).

O termo canônico da ontologia entre **Account** e **Project**: um Engagement é o
programa de transformação contratado por uma conta, e um Project é um degrau
dentro dele (Discovery Sprint, Feasibility, PROVE, Scale). Até esta fatia o One
navegava direto de organização para projeto, e o nível do meio não existia em
lugar nenhum — nem aqui, nem no Pulse.

**Só ``TenantMixin``, sem ``project_id``.** O Engagement é escopado pela
organização e é *pai* de projeto: herdar a chave de projeto inverteria a
hierarquia. É a mesma forma de ``OrganizationRetentionPolicy`` e de
``OrganizationAiQuota``, e o oposto da de ``Milestone``.

**O portal não origina nada disto.** Como fase e entregável, o Engagement nasce
do snapshot do Biahflow sob ``portal_system``; ``portal_app`` só lê. Por isso a
migração que cria a tabela não concede ``INSERT``/``UPDATE``/``DELETE`` ao papel
de requisição — o desenho da ADR 0006/0008 aplicado a um agregado novo.
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TenantMixin, TimestampMixin


class EngagementStatus(str, enum.Enum):
    """O enum canônico do Language Map v1.1 §4 — três valores, e são os três.

    A sessão do Pulse confirmou o contrato em 28/08/2026: o snapshot manda
    exatamente ``active``/``paused``/``closed``. Um valor que este mapa não
    conheça cai em ``active`` na ingestão, no padrão do ``PROJECT_STATUS_MAP``:
    um vocabulário novo do outro lado não pode derrubar o sync.
    """

    active = "active"
    paused = "paused"
    closed = "closed"


class Engagement(Base, TenantMixin, TimestampMixin):
    """O programa de uma conta. Um Project pertence a zero ou um Engagement.

    ``slug`` é a identidade que sobrevive ao sync — ``biahflow-engagement-{id}``,
    derivado do id do Biahflow, como ``project_slug`` faz para o projeto. Único
    **por organização** e não globalmente, no formato de ``Project``: dois
    tenants podem espelhar ids distintos da mesma origem sem colidir.
    """

    __tablename__ = "engagement"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_engagement_organization_slug"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[EngagementStatus] = mapped_column(
        Enum(EngagementStatus, name="engagement_status"),
        nullable=False,
        default=EngagementStatus.active,
    )
