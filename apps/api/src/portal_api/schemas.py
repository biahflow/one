"""O contrato das rotas de cliente, declarado num lugar só (ADR 0020).

Até esta fatia as dezesseis rotas de ``main.py`` devolviam ``dict`` cru, e o
esquema que `docs/api-contracts.md` prometia publicar "automaticamente pelo
OpenAPI do FastAPI" saía **vazio exatamente na superfície do cliente** — a
única que alguém de fora consome.

Por que um módulo, e não inline como em ``admin.py``: lá a resposta nasce ao
lado da rota, e o modelo ao lado dela é o lugar certo. Aqui os payloads nascem
em **outros módulos** — ``integrations/biahflow.build_dashboard``,
``results.to_payload``, ``main._message_payload`` —, então pôr o contrato junto
de cada produtor reproduziria a divisão que esta fatia existe para fechar. É a
mesma forma de ``notifications.py``, ``conversations.py`` e ``telemetry.py``:
o único lugar onde a coisa vive.

Duas regras governam tudo o que está aqui, e as duas são sobre **não mudar o
payload**:

1. **Onde o produtor já entregou texto, o modelo declara texto.** Um
   ``occurred_at`` que sai de ``.isoformat()`` fica ``str``, não ``datetime``;
   um id que sai de ``str(uuid)`` fica ``str``. Declarar o tipo rico faria o
   Pydantic reserializar, e reserializar é mudar o byte que o navegador recebe
   numa fatia cujo único compromisso é descrever o que já existe. O tipo rico é
   o passo seguinte, junto de fazer os produtores devolverem estes modelos.
2. **Campo não declarado é erro, não descarte.** ``response_model`` filtra em
   silêncio o que o modelo não conhece: um dia alguém acrescenta uma chave em
   ``build_dashboard``, a tela não a recebe, e nada fica vermelho. Com
   ``extra="forbid"`` a mesma situação estoura na resposta e aparece no teste —
   e a diferença entre as duas é a diferença entre um contrato e um enfeite.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Out(BaseModel):
    """Base de toda resposta declarada aqui.

    ``extra="forbid"`` é a decisão, e não a formalidade: ver a regra 2 do
    docstring do módulo.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ErrorOut(Out):
    """O corpo de erro do FastAPI. É o mesmo para 401, 404, 409, 422 e 503.

    Que ele seja **um só** é o contrato: a `auth.py` responde sempre
    ``Not authenticated`` e o motivo vai para o log, e a negação de vínculo
    responde sempre 404 — nunca 403 —, para não contar a quem pergunta que o
    recurso existe.
    """

    detail: str


# --- saúde (ADR 0018) -------------------------------------------------------


class HealthOut(Out):
    status: str
    service: str


class ReadyOut(Out):
    """Prontidão. Sim ou não, e nada além disso — sem versão, hostname, DSN nem
    o nome da dependência que caiu. Um ``down`` é indistinguível de outro."""

    status: str


# --- demonstração -----------------------------------------------------------


class DemoNextDeliveryOut(Out):
    title: str
    date: str


class DemoDashboardOut(Out):
    project: str
    status: str
    completion: int
    next_delivery: DemoNextDeliveryOut
    roi_percent: int
    hours_saved: int


# --- identidade -------------------------------------------------------------


class MeProjectOut(Out):
    id: str
    name: str
    slug: str
    status: str


class MeOut(Out):
    """Quem é o chamador e o que ele alcança.

    ``projects`` vazio com 200 é resposta válida: autenticar não é autorizar, e
    o portal precisa poder dizer "você ainda não tem projeto" sem fingir que
    não conhece a pessoa.
    """

    email: str
    full_name: str
    is_internal: bool
    notify_by_email: bool
    organization: str | None
    projects: list[MeProjectOut]
    #: Papéis vindos da `membership`, nunca do realm — um papel de realm não
    #: sabe dizer *em qual projeto* (ADR 0010).
    roles: list[str]


# --- apuração dos resultados (ADR 0013) -------------------------------------


class PeriodOut(Out):
    #: ``from`` é palavra reservada em Python e não é negociável no JSON: o
    #: campo existe assim desde a Fase 3 e a tela lê por esse nome.
    from_: str = Field(alias="from")
    to: str
    days: int


class MeasuredAssumptionOut(Out):
    """A premissa ao lado do número que ela produziu.

    Viaja junto do indicador de propósito: o aceite da Fase 3 é o cliente ver a
    origem de todo valor exibido, e uma resposta só com os valores obrigaria a
    tela a inventar a explicação.
    """

    effective_from: str
    effective_to: str | None
    hourly_rate_cents: int
    monthly_investment_cents: int
    currency: str
    note: str | None
    days_in_period: int


class AssumptionBasisOut(Out):
    """A conta em si, para o cliente poder refazê-la na mão."""

    days_per_month: int
    formula: str


class ResultsOut(Out):
    """O que ``results.to_payload`` devolve.

    Um modelo só para dois lugares porque é **uma função só**: esta é a
    resposta de ``GET /projects/{id}/results`` e também o bloco ``measured``
    embutido no dashboard, que evita uma segunda ida à rede no SSR.

    Os ``None`` são a regra 3 do `AGENTS.md` aplicada a número: investimento
    zero não vira ROI infinito, vira ``None`` com a razão em ``gaps``.
    """

    period: PeriodOut
    events_total: int
    hours_saved: float
    labor_savings_cents: int
    avoided_cost_cents: int
    benefit_cents: int
    investment_cents: int
    net_cents: int
    roi_ratio: float | None
    accuracy: float | None
    exceptions_handled: int
    unattended_share: float | None
    failed: int
    events_without_assumption: int
    assumptions: list[MeasuredAssumptionOut]
    assumption_basis: AssumptionBasisOut
    #: Por que falta um número, quando falta. Nunca vazio por preguiça.
    gaps: list[str]


# --- dashboard (ADR 0006/0008, jornada da Fase 6) ---------------------------


class ProjectHealthOut(Out):
    """Saúde amigável derivada do Health Score do Biahflow.

    Rótulo e nível, e nunca o score nem os sinais internos que o produziram.
    """

    label: str | None
    level: str | None


class DeliverableOut(Out):
    name: str
    state: str
    link: str | None


class PhaseOut(Out):
    name: str
    description: str | None
    state: str
    target_date: str | None
    deliverables: list[DeliverableOut]


class JourneyOut(Out):
    current_phase: str | None
    phases: list[PhaseOut]


class DigitalEmployeeOut(Out):
    name: str
    area: str | None
    description: str | None
    status: str
    kpi_label: str | None
    kpi_value: str | None
    hours_saved_month: float | None
    roi_month: float | None


class RoiOut(Out):
    """O ROI projetado que vem do Biahflow — outra coisa que o apurado dos
    eventos, que vive em ``ResultsOut``. Os dois convivem rotulados na tela."""

    net: float | None
    ratio: float | None


class NextMeetingOut(Out):
    title: str | None
    date: str


class MilestoneOut(Out):
    title: str
    state: str
    due_date: str | None
    owner_label: str | None


class DashboardDocumentOut(Out):
    """O documento como o dashboard o mostra.

    Nome distinto do ``DocumentOut`` de ``admin.py`` porque são coisas
    diferentes: lá é a linha da tela de conhecimento, com estado de varredura e
    de indexação; aqui é o que o cliente vê na aba Documentos.
    """

    title: str
    type: str | None
    author: str | None
    link: str | None
    updated_at: str | None


class MeetingOut(Out):
    title: str
    date: str | None
    recording_url: str | None
    has_transcript: bool
    status: str | None


class PendingOut(Out):
    title: str
    description: str | None
    owner_label: str | None
    state: str
    priority: str
    #: Espelhada do Biahflow ou aberta pela IA por lacuna de contexto. É o que
    #: faz a pendência da IA sobreviver ao sync seguinte (ADR 0012).
    origin: str
    created_at: str
    resolved_at: str | None


class MilestoneCountsOut(Out):
    """Andamento derivado dos marcos. Recalculado na leitura, nunca
    denormalizado, para não divergir do read model."""

    milestones_total: int
    milestones_done: int
    overdue: int
    on_time_percent: int


class DashboardOut(Out):
    """A projeção do read model alimentado pelo Biahflow (ADR 0006).

    O portal não origina nada disto: a digitação continua no Biahflow e chega
    aqui por snapshot.
    """

    project: str
    status: str
    completion: int
    health: ProjectHealthOut | None
    journey: JourneyOut
    digital_employees: list[DigitalEmployeeOut]
    roi: RoiOut
    next_meeting: NextMeetingOut | None
    milestones: list[MilestoneOut]
    documents: list[DashboardDocumentOut]
    meetings: list[MeetingOut]
    pendings: list[PendingOut]
    results: MilestoneCountsOut
    measured: ResultsOut


class MyDashboardOut(DashboardOut):
    """O mesmo dashboard, mais o nome da organização.

    A assimetria é real e é anterior a esta fatia: ``GET /me/dashboard``
    acrescenta a chave (`main.py`) e ``GET /projects/{id}/dashboard`` não. Está
    declarada em vez de corrigida porque corrigi-la muda um payload, e esta
    fatia descreve o que existe.
    """

    organization: str | None


# --- notificações (ADR 0012) ------------------------------------------------


class NotificationOut(Out):
    id: str
    kind: str
    title: str
    detail: str | None
    link: str | None
    occurred_at: str
    read: bool


class NotificationsOut(Out):
    unread_count: int
    items: list[NotificationOut]


class NotificationsReadOut(Out):
    marked: int


class PreferencesOut(Out):
    notify_by_email: bool


# --- chat e conversa (ADR 0007/0015/0017) -----------------------------------


class CitationOut(Out):
    """A citação como foi exibida, com o ponteiro para o arquivo quando há um.

    ``document_id`` vazio é o caso normal: um marco não é um arquivo e não tem
    o que abrir. Quando há, a citação vira link (ADR 0017).
    """

    label: str
    document_id: str | None


class ChatOut(Out):
    answer: str
    #: Projeção de exibição: quem só quer imprimir o rótulo não precisa saber o
    #: que é clicável. Mesma lista de ``citations``, sem o ponteiro.
    sources: list[str]
    citations: list[CitationOut]
    confidence: str
    #: A resposta declarou lacuna e abriu uma pendência (regra 3 do `AGENTS.md`).
    pending_created: bool
    conversation_id: str
    message_id: str


class ConversationMessageOut(Out):
    id: str
    role: str
    text: str
    confidence: str | None
    sources: list[str]
    citations: list[CitationOut]
    pending_created: bool
    feedback: str | None


class ConversationOut(Out):
    """A thread corrente, para o chat reabrir onde parou.

    Sem conversa nenhuma devolve ``conversation_id: null`` e lista vazia — e
    **sem** a chave ``title``, que é por que a rota serializa com
    ``response_model_exclude_unset``. "Ainda não perguntei nada" não é ausência
    de recurso, então também não é 404.
    """

    conversation_id: str | None
    title: str | None = None
    messages: list[ConversationMessageOut]


class FeedbackOut(Out):
    id: str
    #: O polegar. Nunca a resposta nem as citações: o GRANT é de coluna
    #: (ADR 0015), e avaliar não é reescrever.
    feedback: str


# --- integrações ------------------------------------------------------------


class AgentEventAcceptedOut(Out):
    """202 em ambos os casos: ``accepted`` na primeira vez, ``duplicate`` no
    reenvio. O produtor precisa distinguir reenvio de recusa, e nenhum dos dois
    é erro (ADR 0013)."""

    event_id: str
    status: str


class WebhookSyncedOut(Out):
    status: str
    project_id: str


class DocumentDownloadOut(Out):
    """Endereço, não bytes: URL assinada de vida curta (ADR 0017)."""

    url: str
    expires_at: str
