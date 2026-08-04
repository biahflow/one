"""Premissas financeiras de um projeto, com vigência (ADR 0013).

O ROI apurado não é um número solto: ele é o resultado de aplicar um valor-hora
e um investimento a um conjunto de eventos. Esses dois números mudam ao longo do
projeto, e é por isso que eles moram numa **linha com vigência** em vez de numa
coluna de ``project``.

Uma premissa nunca é editada no lugar. Trocar o valor-hora fecha a linha vigente
(``effective_to``) e abre outra — assim um indicador de três meses atrás continua
explicável pela premissa que valia naquele dia, que é o que "premissa auditável"
quer dizer. A garantia de que as vigências não se sobrepõem é do banco, não do
código: a migração declara um ``EXCLUDE USING gist`` sobre o intervalo.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin
from portal_api.models.project import _ProjectChildMixin


class ProjectFinancialAssumption(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "project_financial_assumption"

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    #: Aberta enquanto for a vigência corrente. Semântica de intervalo `[from, to)`.
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: Centavos, para o cálculo não carregar erro de ponto flutuante.
    hourly_rate_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Investimento **mensal** no projeto. O cálculo rateia por dia sobre o
    #: período pedido — comparar benefício de 30 dias com investimento de
    #: projeto inteiro produziria um ROI fictício.
    monthly_investment_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="BRL", server_default="BRL"
    )
    #: Por que esta premissa é esta. Aparece para o cliente junto do indicador.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
