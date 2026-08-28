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


class CanonicalStage(str, enum.Enum):
    """O degrau da metodologia FDE a que uma fase corresponde (Language Map v1.1 §4).

    Seis valores, e são **os do documento normativo** — nunca derivados do nome da
    fase. Um projeto do Biahflow pode ter uma fase ``Activation``, operacional da casa
    e sem equivalente na FDE; adivinhar o degrau pelo rótulo produziria exatamente a
    falsa precisão que ``results.py`` recusa ao declarar a lacuna em vez de dividir por
    zero. Quando a origem não afirma o degrau, a coluna fica ``NULL`` — e ``NULL`` aqui
    quer dizer "esta fase não tem equivalente FDE", não "ainda não sabemos".
    """

    discover = "discover"
    prioritize = "prioritize"
    feasibility = "feasibility"
    prove = "prove"
    scale = "scale"
    optimize = "optimize"


class GateDecision(str, enum.Enum):
    """A decisão que fecha uma fase com gate (Language Map v1.1 §4, decisão D7).

    Chama-se ``GateDecision`` e **não** ``GateOutcome``: a D7 renomeou o termo porque
    ``Outcome`` é resultado de negócio medido (``Measurement(kind=outcome)``), e os
    dois disputando a mesma palavra fariam a tela chamar de "resultado" uma decisão de
    metodologia. O modelo do Biahflow ainda se chama ``gate_outcome`` lá; o nome
    canônico é este, e é o que atravessa a fronteira.
    """

    go = "go"
    conditional_go = "conditional_go"
    redesign = "redesign"
    no_go = "no_go"


class DeliverableState(str, enum.Enum):
    pending = "pending"
    delivered = "delivered"


class DeliverableAcceptanceAction(str, enum.Enum):
    """A decisão que o cliente tomou sobre um entregável (ADR 0077).

    Dois valores, e a ausência dos outros é decisão e não recorte: a escada de
    aceite desenhada na F-025 §10 tem cinco rótulos, e ``superseded``/
    ``cancelled`` **não** entram sem revisão de design própria — supersessão é
    consequência de uma segunda linha, não uma terceira espécie de decisão.
    ``done`` nunca entra: quem conclui a entrega é o lifecycle de Delivery, e o
    One registra o evento sem concluir nada (ADR 0067).
    """

    accepted = "accepted"
    changes_requested = "changes_requested"


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
    # O Engagement a que este projeto pertence (Language Map v1.1 §2), e **nullable**.
    #
    # A ontologia diz que todo Project pertence a exatamente um Engagement (invariante 7),
    # e este é o lado que **projeta**, não o que origina: um projeto sincronizado antes de o
    # Biahflow passar a mandar a chave não tem engagement, e inventar um seria fabricar
    # dado — o que este repositório recusa em `results.py`, em `freshness()` e na tela do
    # funil. `NOT NULL` aqui exigiria um valor de aterro para toda linha existente, que é
    # exatamente a falsa precisão que a ausência declara não ter.
    #
    # `SET NULL` e não `CASCADE`: apagar o programa não apaga o projeto do cliente — ele
    # continua existindo e passa a não ter agrupamento, que é o estado anterior a esta fatia.
    engagement_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("engagement.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
    # --- contrato de projeção versionado (Fase 7, ADR 0076) ------------------------------
    #
    # As três colunas respondem a **duas** perguntas, e é por isso que são três.
    #
    # ``observed_at`` é quando o **Biahflow observou** aquele estado, carimbado na origem: é
    # a idade do dado. ``synced_at`` é quando o portal **copiou**: é a idade da cópia, e só
    # isso. Uma coluna só faria a segunda passar pela primeira — a falsa precisão que
    # ``results.py`` recusa e que a ADR 0026 apagou da tela ao remover um "Atualizado há 2
    # dias" que ninguém tinha como sustentar. Separadas, a projeção diz "observado há X"
    # quando é verdade e "sincronizado há X" quando é só o que se sabe.
    #
    # ``projection_version`` é o inteiro monotônico por projeto que a origem incrementa a
    # cada mudança de estado projetável. É o que torna a reconciliação determinística quando
    # dois ``observed_at`` empatam ou o relógio da origem regride: ordenar por hora sozinho
    # não sobrevive a um relógio que anda para trás.
    #
    # As três são nullable, e a nulidade é significativa: as linhas que já existem não têm
    # nenhuma delas, e um Biahflow anterior a esta fatia não manda os campos — ausência é
    # ausência de afirmação, nunca "versão zero". ``NOT NULL`` quebraria o upgrade sobre os
    # dados existentes e faria a reconciliação ler o desconhecido como o mais velho possível.
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    projection_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
    # O degrau da FDE a que esta fase corresponde (Language Map v1.1 §4, ADR 0081).
    #
    # **Nullable, e a nulidade é significativa**: a origem manda `""` quando a fase não
    # tem equivalente FDE — uma `Activation`, operacional da Biahflow —, e isso é
    # legítimo por desenho, não falta de dado. `NULL` é a tradução honesta daquele
    # vazio, no precedente de `observed_at` (ADR 0076) e de `engagement_id` (ADR 0079):
    # ausência é ausência de afirmação. Um valor de aterro exigiria escolher um degrau
    # para uma fase que a metodologia não tem, que é fabricar dado.
    canonical_stage: Mapped[CanonicalStage | None] = mapped_column(
        Enum(CanonicalStage, name="canonical_stage"),
        nullable=True,
    )
    # A decisão que fechou o gate desta fase, quando alguém a tomou (decisão D7).
    #
    # Nullable pelo motivo **oposto** ao de cima, e é por isso que são duas colunas e
    # não uma: aqui `NULL` quer dizer "ninguém decidiu ainda". Quem separa os dois
    # sentidos é `requires_gate` — sem ele, "fase sem gate" e "gate por decidir"
    # ficariam indistinguíveis, e a tela teria de escolher entre calar sobre as duas ou
    # afirmar espera sobre uma fase que nunca terá decisão.
    gate_decision: Mapped[GateDecision | None] = mapped_column(
        Enum(GateDecision, name="gate_decision"),
        nullable=True,
    )
    # Se esta fase termina em gate. É propriedade do **template** da fase na origem:
    # quem decide que Feasibility e PROVE terminam em decisão é a metodologia, não o
    # projeto. `False` por default porque um Biahflow anterior a esta fatia não manda a
    # chave, e "não afirmou que exige gate" é a leitura conservadora — ela faz a tela
    # calar, nunca afirmar uma espera que ninguém declarou.
    requires_gate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


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
    #: Id do entregável no Biahflow, quando o snapshot o traz (ADR 0077).
    #:
    #: **É a identidade que o uuid desta linha não é.** O sync apaga e recria as
    #: linhas de ``phase_deliverable`` a cada snapshot, então o ``id`` de hoje não
    #: é o de amanhã — a mesma armadilha que ``notifications.ITEM_ANCHOR``
    #: documenta ao recusar apontar um link por uuid. Um fato que precise nomear
    #: *este entregável* meses depois — o aceite do cliente, ADR 0077 — aponta
    #: para cá, no precedente de ``PendingItem.external_ref`` e de
    #: ``Document.external_id``.
    #:
    #: ``nullable`` pelo argumento de ``Project.archived_at``: um Biahflow que não
    #: mande a chave manda um corpo sem ela, e ausência é ausência de afirmação —
    #: não um id inventado deste lado.
    external_ref: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)


class DeliverableAcceptance(Base, _ProjectChildMixin, TimestampMixin):
    """O que o cliente decidiu sobre um entregável (Fase 7, ADR 0077).

    A **quarta** tabela que o caminho de requisição origina, depois de
    ``conversation``, ``conversation_message`` e ``pending_item_comment`` — e a
    forma é a da terceira, pela mesma razão declarada lá: o registro existe
    **para o outro lado ler**, então o predicado da policy é o de tenant simples
    e "quem decidiu" fica na coluna, não no ``WHERE``.

    **Append-only, e a imutabilidade é privilégio e não convenção.** ``portal_app``
    recebe ``SELECT`` e ``INSERT`` na migração 0035 e nada mais: uma segunda
    decisão **acrescenta** uma linha, e a anterior aparece superada na leitura —
    nunca reescrita. Não existe rota de "editar aceite" porque o banco a
    recusaria; seria funcionalidade errada, não funcionalidade faltando.

    **O vínculo é o ``external_ref`` e não uma chave estrangeira.** ``sync_snapshot``
    apaga e recria ``phase_deliverable`` a cada webhook, então um FK ao uuid do
    read model seria destruído no sync seguinte, levando junto a decisão do
    cliente. Pelo mesmo motivo ``phase_name`` e ``deliverable_name`` são
    denormalizados: eles sobrevivem ao entregável sumir da origem, como
    ``author_label`` sobrevive à remoção do autor.

    O One registra o evento; **não** conclui a fase. ``accepted`` autoriza o outro
    lado a transicionar para ``ACCEPTED``, e só o lifecycle de Delivery conclui
    ``DONE`` (ADR 0067).
    """

    __tablename__ = "deliverable_acceptance"

    #: A identidade estável do entregável, vinda do Biahflow (migração 0034).
    deliverable_external_ref: Mapped[str] = mapped_column(
        String(80), nullable=False, index=True
    )
    #: Nome da fase e do entregável **como estavam no momento da decisão**. Sem
    #: eles, um entregável que saiu do snapshot deixaria o registro sem dizer
    #: sobre o quê alguém decidiu — e é justamente o registro que precisa
    #: sobreviver ao read model.
    phase_name: Mapped[str] = mapped_column(String(80), nullable=False)
    deliverable_name: Mapped[str] = mapped_column(String(160), nullable=False)
    action: Mapped[DeliverableAcceptanceAction] = mapped_column(
        Enum(DeliverableAcceptanceAction, name="deliverable_acceptance_action"),
        nullable=False,
    )
    #: Quem decidiu. ``SET NULL`` e não ``CASCADE``, pelo argumento de
    #: ``PendingItemComment.author_user_id``: revogar o acesso de alguém não pode
    #: apagar o aceite que ele deu — e aqui isso vale mais, porque é o registro
    #: que o outro lado projeta.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_label: Mapped[str] = mapped_column(String(160), nullable=False)
    #: ``True`` quando quem decidiu era da Biahflow. Guardado e não derivado do
    #: papel atual: alguém que deixa de ser interno não muda o lado de quem
    #: decidiu naquele dia.
    actor_is_internal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: Opcional em "aprovar", esperado em "pedir ajuste". Texto do cliente — não
    #: vai para o log nem para o ``audit_log``.
    comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)


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
