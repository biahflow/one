"""KPI e suas medições — o indicador que o Pulse define e mede (Language Map v1.1).

O termo canônico da §2: **KPI** é o indicador extraído de ``DigitalEmployee``, e
**Measurement** é a leitura dele. A §4 fixa três espécies de leitura —
``baseline`` · ``outcome`` · ``monitoring`` — e o invariante 11 diz que todo
Outcome mostrado ao cliente tem um Baseline comparável ao lado.

**Uma tabela, não duas.** A forma óbvia seria ``kpi`` mais ``measurement`` com um
``kind``, espelhando o modelo do Pulse. Este lado **projeta** em vez de originar
(ADR 0006/0008), e o que atravessa a fronteira não é o modelo de lá: é um
snapshot em que ``baseline`` e ``outcome`` são **no máximo um cada** e
``monitoring`` é uma série sem identidade própria. Uma tabela filha reproduziria
a hierarquia sem ganhar nada — o sync substitui o KPI inteiro a cada passagem, de
modo que nenhuma linha de medição sobrevive para ser referenciada — e custaria
uma segunda policy, um segundo ``DELETE`` escopado e uma junção no dashboard.
O ``monitoring`` fica em JSONB pelo argumento de ``ProjectDriveConnection.
last_sync_stats``: é uma lista opaca que a tela mostra e ninguém consulta por
dentro.

**As duas nulidades do Baseline, sem coluna extra.** O produtor distingue
``"baseline": null`` (nunca foi definida) de ``{"value": null, …}`` (a janela
existe, ninguém mediu ainda), e **nenhuma das duas é zero** — a AC da issue #89
está escrita nesses termos. A regra aqui é: **o objeto existe se e somente se
``baseline_period_start`` não é nulo**. A janela é o que a definição da medição
carrega mesmo quando o número falta; o número é ``baseline_value``, que pode ser
nulo dentro de uma janela que existe. Uma coluna booleana a mais seria um segundo
lugar dizendo a mesma coisa, e os dois podendo divergir.

**O portal não origina nada disto.** Como fase, entregável e Engagement, o KPI
nasce do snapshot sob ``portal_system``; ``portal_app`` só lê. A migração que
cria a tabela não concede ``INSERT``/``UPDATE``/``DELETE`` ao papel de
requisição, e a ausência é o controle.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.models.project import _ProjectChildMixin
from portal_api.db.base import Base, TimestampMixin


class Kpi(Base, _ProjectChildMixin, TimestampMixin):
    """O indicador de um projeto, com a Baseline e o Outcome dele.

    Escopo de **projeto**, ao contrário de ``ValueLedgerEntry``: o snapshot manda
    ``kpis[]`` por projeto e não há sinal de fan-out entre irmãos do mesmo
    mandato. É a forma de ``Milestone`` e de ``DigitalEmployee``, inclusive na
    ingestão — substituição integral a cada passagem do sync.
    """

    __tablename__ = "kpi"
    __table_args__ = (
        UniqueConstraint("project_id", "external_id", name="uq_kpi_project_external_id"),
    )

    #: O ``KPI.id`` do Pulse. É a identidade que sobrevive ao ``DELETE`` do sync —
    #: o uuid local é recriado a cada webhook —, e é ela que
    #: ``DigitalEmployee.kpi_external_ids`` e ``ValueLedgerEntry.kpi_external_id``
    #: guardam. ``int`` e não ``str``: o produtor manda inteiro, ao contrário do
    #: ``external_ref`` do entregável, que é chave primária de Django projetada
    #: como texto.
    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: O que o indicador significa, em prosa da origem.
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Como ele é calculado, em prosa da origem. Texto e não expressão: quem
    #: calcula é o Pulse, e este lado só mostra a conta que já foi feita.
    formula: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: A unidade (``hours``, ``percent``, ``brl``…). É o que faz Baseline e
    #: Outcome serem comparáveis lado a lado, que é o invariante 11.
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: ``up`` ou ``down`` — para que lado o indicador melhora. Sem ele a tela não
    #: sabe se cair de 72 para 21 é ganho ou perda.
    direction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: De onde o número sai, em prosa da origem.
    data_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Com que frequência é medido (``monthly``, ``weekly``…).
    cadence: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: A meta. ``None`` é "ninguém definiu meta", **nunca** zero.
    target: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    #: A Baseline. O objeto existe sse ``baseline_period_start`` não é nulo — ver
    #: o docstring do módulo. ``baseline_value`` nulo dentro de uma janela que
    #: existe é "a janela existe e ninguém mediu ainda".
    baseline_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    baseline_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    baseline_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    baseline_measured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    baseline_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: O Outcome, com a mesma regra de nulidade. O invariante 12 do Language Map
    #: — Outcome nunca sem Baseline comparável — é afirmado na ingestão e na
    #: projeção, não por constraint: o produtor já o garante, e uma constraint
    #: aqui trocaria um Outcome perdido por um **snapshot** perdido.
    outcome_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    outcome_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    outcome_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    outcome_measured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outcome_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: A série de acompanhamento, na forma ``[{value, period_start, period_end,
    #: measured_at, confidence}]``. Sempre lista, **nunca** ``None``: o produtor
    #: manda ``[]`` quando não há, e uma lista vazia é o que a tela sabe ler.
    monitoring: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
