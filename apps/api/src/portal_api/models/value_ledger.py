"""Value Ledger — o valor gerado, entrada por entrada (Language Map v1.1 §2).

O termo canônico é **Value**, o modelo é ``ValueLedgerEntry`` e o rótulo que o
cliente lê é **Value Ledger**. A mesma linha da §2 diz o que ele **nunca** é:
"ROI projetado" nem "Case". Isso não é preciosismo de nome — é a diferença entre
uma promessa da origem (``RoiOut``, o ``roi`` do snapshot) e um valor com
período, método de atribuição e um Outcome por trás.

**Escopo de mandato, não de projeto.** O ``value_ledger`` é lido por Engagement
no Pulse: a mesma entrada sai no snapshot de **todos** os projetos do mandato
(fan-out). Guardá-la por projeto duplicaria a mesma linha uma vez por irmão e
faria a soma do programa contar cada real tantas vezes quantos projetos houvesse.
Daí ``engagement_id`` e **nenhum** ``project_id``: é a forma de ``Engagement``,
de ``OrganizationRetentionPolicy`` e de ``OrganizationAiQuota`` — tenant sem
projeto —, com a chave do programa por cima.

**Sem FK para ``kpi``, e é decisão.** ``kpi_external_id`` guarda o ``KPI.id`` do
Pulse, solto. Uma FK exigiria que o KPI de origem existisse *deste* lado no
momento da escrita, e ele pode viver num projeto irmão do mesmo mandato que ainda
não sincronizou — ou que nunca sincronizará, porque ninguém foi convidado para
ele. O vínculo é resolvido na leitura, contra os KPIs do projeto sendo servido, e
**não casar é caso normal**: a entrada aparece com o método de atribuição escrito
e sem o KPI ao lado. Fabricar a FK trocaria uma exibição incompleta por uma
ingestão que falha.

**Sem moeda.** Tudo é BRL, e o produtor decidiu não emitir a coluna. Um
``currency`` aqui seria um campo que ninguém escreve e que a tela leria como se
significasse algo — o defeito da ADR 0033 na direção de entrada.

**O portal não origina nada disto**, como todo o resto do read model: nasce do
snapshot sob ``portal_system`` e ``portal_app`` só lê.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TenantMixin, TimestampMixin


class ValueLedgerEntry(Base, TenantMixin, TimestampMixin):
    """Uma entrada do Value Ledger de um Engagement."""

    __tablename__ = "value_ledger_entry"
    __table_args__ = (
        UniqueConstraint(
            "engagement_id", "external_id", name="uq_value_ledger_entry_engagement_id"
        ),
    )

    #: O programa a que a entrada pertence. ``CASCADE`` e não ``SET NULL`` — ao
    #: contrário de ``Project.engagement_id`` —, porque aqui o vínculo é a
    #: identidade: uma entrada de Value Ledger sem mandato não é escopável por
    #: nada, e a policy do papel de requisição a alcança justamente por ele.
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("engagement.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: O ``ValueLedgerEntry.id`` do Pulse — a identidade que sobrevive à
    #: substituição do sync, como o ``external_id`` do KPI.
    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    #: A espécie de valor (``cost_saving``, ``revenue``…), como a origem a nomeia.
    value_type: Mapped[str] = mapped_column(String(60), nullable=False)
    #: O valor em BRL. ``NOT NULL``: uma entrada sem quantia não é entrada de
    #: razão — o produtor só publica o que foi aprovado.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    #: A quantidade física por trás da quantia (horas, chamados…), quando houver.
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    #: **Como** aquele número foi atribuído a este mandato, em prosa da origem. É
    #: o invariante 12 do Language Map, e é o que separa um Value Ledger de um
    #: número solto na tela: sem o método, a entrada é uma afirmação sem conta.
    attribution_method: Mapped[str] = mapped_column(Text, nullable=False)
    #: O KPI de origem, pelo id do Pulse. Ver o docstring do módulo: sem FK, e
    #: não casar com nenhum KPI deste projeto é caso normal.
    kpi_external_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Quando o Outcome que sustenta a entrada foi medido. ``None`` quando a
    #: origem não o carimba — ausência de afirmação, não "hoje".
    outcome_measured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
