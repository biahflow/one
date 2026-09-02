"""A superfície de Discovery que o cliente lê (Language Map v1.1, ADR 0086).

Cinco agregados da §2 do mapa que até aqui existiam só no Pulse: **Process** e
**ProcessStep** (o AS-IS validado), **Finding** (com ``epistemic_status``),
**PainPoint**, e **ImprovementOpportunity** com o Opportunity Score e as
**SolutionHypothesis** aninhadas. Nenhum deles é originado aqui: como fase,
entregável, Engagement e KPI, todos nascem do snapshot sob ``portal_system``, e
``portal_app`` só lê.

**Escopo de conta, não de projeto.** O Discovery é lido por Account no Pulse: a
mesma lista completa sai no snapshot de **todos** os projetos da conta (fan-out),
e não incrementalmente. Guardá-la por projeto duplicaria cada achado uma vez por
irmão e faria o backlog de melhoria contar a mesma oportunidade tantas vezes
quantos projetos houvesse. Daí só ``TenantMixin``, sem ``project_id`` — a forma
de ``Engagement``, de ``OrganizationRetentionPolicy`` e de ``ValueLedgerEntry``,
com a diferença de a chave ser a própria organização.

**A marca de publicação não atravessa, e é decisão do produtor.** O Pulse tem
``published_at``/``published_by`` em ``Process``, ``Evidence``, ``Finding``,
``PainPoint`` e ``ImprovementOpportunity``, e **filtra antes de emitir**: o que
chega no payload já é o publicado, e a presença no array é a prova. Não há coluna
de revisão aqui porque não há campo de revisão lá para copiar — copiá-lo seria o
One afirmando por conta própria que algo foi revisado, que é a regra 3 da §3 ("o
One nunca é fonte primária") ao contrário. Ver a ADR 0086 e o
``reviewed_resources`` de ``docs/contracts/one-visibility.json``.

**As duas listas de ligação são tabelas, e não JSONB.** ``DigitalEmployee.
kpi_external_ids`` (ADR 0085) guarda ids crus porque o KPI de origem pode viver
num projeto irmão que **nunca sincronizou** deste lado — ali um id que não casa é
estado normal e permanente. Aqui não: achado, dor e oportunidade chegam no
**mesmo payload**, escopados pela mesma conta e recriados na mesma transação, de
modo que um id pendurado significa que a ingestão errou. A chave estrangeira é o
que faz o banco cobrar o que a ingestão promete — um id que não resolve é
descartado ali, com a decisão visível, em vez de sobreviver num JSONB que ninguém
confere.

**O que fica em JSONB, fica com lista branca.** ``Finding.evidences`` e
``ImprovementOpportunity.priority_dimensions`` são blobs, e blob é o ponto cego
do guard de visibilidade da ADR 0082: ele classifica **campo de esquema**, e não
enxerga dentro de um objeto sem propriedades declaradas. A proteção equivalente é
a lista branca na ingestão (``_EVIDENCE_KEYS``, ``_PRIORITY_DIMENSIONS`` em
:mod:`portal_api.integrations.biahflow`): um campo novo do outro lado — um
``raw_excerpt``, um ``content_hash``, um ``rationale`` dentro de ``dimensions`` —
não atravessa por omissão, que é a mesma regra de negação da ADR 0082 aplicada
onde o esquema não alcança.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TenantMixin, TimestampMixin


class EpistemicStatus(str, enum.Enum):
    """O enum canônico da §4 do Language Map — três valores, e são os três (D6).

    ``fact`` é afirmação com evidência revisada; ``hypothesis`` é o que a extração
    por IA produz e ainda não foi promovido por uma pessoa; ``unknown`` é a
    **lacuna declarada** — pergunta que o Discovery abriu e não fechou.

    ``unknown`` atravessa e não é omitido, e isso não é detalhe: um Discovery que
    só mostrasse o que ficou sabido esconderia do cliente o que ainda não se sabe,
    que é a regra 3 do `AGENTS.md` aplicada a levantamento em vez de a resposta de
    IA.

    Um valor que este mapa não conheça cai em ``unknown`` na ingestão — e **não**
    em ``fact``, que é o padrão do ``PROJECT_STATUS_MAP`` invertido de propósito:
    vocabulário novo do outro lado não pode derrubar o sync, e também não pode
    virar afirmação. O degrau seguro é a lacuna.
    """

    fact = "fact"
    hypothesis = "hypothesis"
    unknown = "unknown"


class Process(Base, TenantMixin, TimestampMixin):
    """Um processo mapeado da conta — o AS-IS que o Discovery validou.

    ``external_id`` é a identidade que sobrevive à substituição do sync, como em
    ``Kpi``: o uuid local é recriado a cada passagem, e é o id da origem que
    ``Finding.process_id`` reencontra na ingestão seguinte.
    """

    __tablename__ = "process"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "external_id", name="uq_process_organization_id"
        ),
    )

    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: A ordem em que a origem os lista. Vem da origem e não é derivada aqui: a
    #: sequência dos processos é afirmação de quem os mapeou.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Quando a origem atualizou o processo. ``None`` é ausência de afirmação —
    #: nunca a hora da cópia, que seria a falsa precisão que ``results.py`` recusa.
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ProcessStep(Base, TenantMixin, TimestampMixin):
    """Uma etapa do processo, com as seis chaves do formulário P-S-D-T-E-R.

    **Os seis nomes ficam em português, e é decisão do contrato** (fechamento de
    `biahflow/pulse#106`): eles não são termos da ontologia — são as perguntas do
    formulário que o time faz na sessão de Discovery ("quem são as *pessoas*, que
    *sistema*, que *dados*, quanto *tempo*, que *erro*, quanto *retrabalho*"). A
    §5 do Language Map bane nome de **modelo** em português (`Processo`,
    `ProcessoEtapa`), e o modelo aqui é ``ProcessStep``; traduzir as seis chaves
    quebraria o casamento com o formulário do outro lado sem ganhar vocabulário
    canônico nenhum, porque não há termo canônico para elas.
    """

    __tablename__ = "process_step"
    __table_args__ = (
        UniqueConstraint("process_id", "external_id", name="uq_process_step_process_id"),
    )

    process_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("process.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    pessoas: Mapped[str | None] = mapped_column(Text, nullable=True)
    sistema: Mapped[str | None] = mapped_column(Text, nullable=True)
    dados: Mapped[str | None] = mapped_column(Text, nullable=True)
    tempo: Mapped[str | None] = mapped_column(Text, nullable=True)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrabalho: Mapped[str | None] = mapped_column(Text, nullable=True)


class Finding(Base, TenantMixin, TimestampMixin):
    """Um achado do Discovery, com o estado epistêmico dele.

    ``process_id`` e ``step_id`` são ``SET NULL`` e não ``CASCADE``, pelo
    argumento que ``Decision.meeting_id`` já escreveu: **perder a proveniência é
    melhor que perder o achado**. E são nulos por caso normal, não só por acidente
    — o produtor publica achado e processo separadamente, então um achado pode
    apontar para um processo que ninguém publicou ainda.

    ``evidences`` é JSONB e não tabela: a evidência nunca é consultada por si só —
    ela existe para aparecer **debaixo** do achado que sustenta —, e uma tabela
    filha custaria policy, ``DELETE`` escopado e junção sem responder pergunta
    nenhuma que este lado faça. É o argumento de ``Kpi.monitoring``. A lista branca
    que decide o que entra nela está no docstring do módulo.
    """

    __tablename__ = "finding"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "external_id", name="uq_finding_organization_id"
        ),
    )

    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    #: A afirmação, em prosa da origem. É o achado — não o resumo dele.
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    epistemic_status: Mapped[EpistemicStatus] = mapped_column(
        Enum(EpistemicStatus, name="epistemic_status"),
        nullable=False,
        default=EpistemicStatus.unknown,
    )
    #: A confiança que a origem declara. ``None`` é "não declarada", nunca zero —
    #: zero seria a origem desconfiando do próprio achado (a regra do
    #: ``KpiMeasurementOut.confidence``).
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    process_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("process.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("process_step.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: ``[{id, kind, reference, captured_at}]`` — e só essas quatro chaves. Sempre
    #: lista, nunca ``None``: a lista vazia é o estado de um ``hypothesis``, e um
    #: terceiro caso não teria o que dizer à tela.
    evidences: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )


class PainPoint(Base, TenantMixin, TimestampMixin):
    """Uma dor confirmada da conta, sustentada pelos achados que a originaram."""

    __tablename__ = "pain_point"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "external_id", name="uq_pain_point_organization_id"
        ),
    )

    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Que espécie de impacto a dor causa (``cost``, ``time``, ``quality``…), como
    #: a origem a nomeia.
    impact_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: O tamanho do impacto, quando alguém o quantificou. ``None`` é **não
    #: quantificado** e nunca zero — a mesma regra do ``target`` do KPI, e a razão
    #: de a tela dizer "Impacto não quantificado" em vez de "R$ 0".
    impact_estimate: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    status: Mapped[str] = mapped_column(String(60), nullable=False)


#: Quais achados sustentam qual dor. Tabela de ligação pura — sem ``id`` próprio,
#: sem carimbo de tempo e sem ``organization_id``: ela não é uma coisa, é o fato
#: de duas coisas se ligarem, e as duas já são escopadas pela conta. A policy
#: alcança a linha **pela dor**, que é o que mantém "contexto ausente devolve zero
#: linhas" sem uma terceira cópia da chave de tenant.
pain_point_finding = Table(
    "pain_point_finding",
    Base.metadata,
    Column(
        "pain_point_id",
        PGUUID(as_uuid=True),
        ForeignKey("pain_point.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "finding_id",
        PGUUID(as_uuid=True),
        ForeignKey("finding.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class ImprovementOpportunity(Base, TenantMixin, TimestampMixin):
    """Uma oportunidade de melhoria da conta — o item do backlog vivo.

    **``Improvement`` não é enfeite no nome** (§5 do Language Map, invariante 1):
    ``Opportunity`` sozinho colide entre venda e melhoria operacional, e a venda —
    ``CommercialOpportunity`` — é proibida no One por escrito
    (``forbidden_resources`` de ``docs/contracts/one-visibility.json``).

    O Opportunity Score vive em três colunas rasas em vez de um agregado próprio:
    o produtor manda **só a avaliação vigente** (``PriorityAssessment`` tem
    histórico lá e ele não atravessa), então uma tabela filha guardaria sempre uma
    linha só. É o argumento de ``Kpi`` não ter ``measurement`` como filha.

    ``priority_dimensions`` é JSONB com lista branca de cinco chaves — ver o
    docstring do módulo. O ``rationale`` do ``PriorityAssessment`` **não existe
    aqui e não pode passar a existir**: é o par proibido da §3, e a proibição já
    tem guarda em ``tests/api-contract.test.mjs``.
    """

    __tablename__ = "improvement_opportunity"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "external_id",
            name="uq_improvement_opportunity_organization_id",
        ),
    )

    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: O que muda se a oportunidade for perseguida, em prosa da origem.
    desired_change: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: O impacto que se **espera** — hipótese, e a tela a rotula como tal.
    impact_hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(60), nullable=False)
    #: A versão da avaliação vigente. Existe para o cliente e o time falarem da
    #: mesma nota: o score muda quando a avaliação é refeita, e sem a versão as
    #: duas conversas seriam sobre números diferentes com o mesmo nome.
    priority_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: O Opportunity Score (D5). ``None`` é "ninguém avaliou ainda", nunca zero —
    #: zero é uma nota, e a ausência de nota não é a pior nota.
    priority_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: ``{impact, evidence_strength, feasibility, time_to_value, economics}``, as
    #: cinco da D5 e nada além delas.
    priority_dimensions: Mapped[dict[str, int] | None] = mapped_column(
        JSONB, nullable=True
    )


#: Quais dores a oportunidade endereça. Mesma forma e mesma razão de
#: ``pain_point_finding``.
improvement_opportunity_pain_point = Table(
    "improvement_opportunity_pain_point",
    Base.metadata,
    # Os dois nomes são explícitos porque a convenção de nomes produziria 88 e 62
    # caracteres aqui, e o Postgres trunca identificador em 63: o nome gravado
    # deixaria de ser o nome declarado, e o `alembic check` acusaria deriva de uma
    # migração que aplicou corretamente.
    Column(
        "improvement_opportunity_id",
        PGUUID(as_uuid=True),
        ForeignKey(
            "improvement_opportunity.id",
            ondelete="CASCADE",
            name="fk_improvement_opportunity_pain_point_opportunity",
        ),
        primary_key=True,
    ),
    Column(
        "pain_point_id",
        PGUUID(as_uuid=True),
        ForeignKey(
            "pain_point.id",
            ondelete="CASCADE",
            name="fk_improvement_opportunity_pain_point_pain_point",
        ),
        primary_key=True,
    ),
)


class SolutionHypothesis(Base, TenantMixin, TimestampMixin):
    """Uma hipótese de solução para uma oportunidade de melhoria.

    **Hipótese, e a palavra é o contrato** (§2): o que a Biahflow acha que
    resolveria, antes de a Feasibility dizer se dá e de o PROVE dizer se funciona.
    Nunca "a solução" nem "o escopo" — a §2 nomeia os dois como o que ela não é.

    FK direta para a oportunidade, sem tabela de ligação e sem mapa de resolução:
    ela vem **aninhada** no payload do pai, e não solta.
    """

    __tablename__ = "solution_hypothesis"
    __table_args__ = (
        UniqueConstraint(
            "improvement_opportunity_id",
            "external_id",
            name="uq_solution_hypothesis_improvement_opportunity_id",
        ),
    )

    #: Nome explícito pelo mesmo motivo de ``improvement_opportunity_pain_point``:
    #: a convenção passaria dos 63 caracteres que o Postgres guarda.
    improvement_opportunity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "improvement_opportunity.id",
            ondelete="CASCADE",
            name="fk_solution_hypothesis_improvement_opportunity",
        ),
        nullable=False,
        index=True,
    )
    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    #: O que se faria — a intervenção, em prosa da origem.
    intervention: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: O efeito esperado dela. Esperado, não medido: quem mede é o KPI (ADR 0085).
    expected_effect: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(60), nullable=False)
