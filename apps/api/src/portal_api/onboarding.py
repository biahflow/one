"""O funil de onboarding: onde o degrau é carimbado, e onde ele é lido.

Fase 7, RFC 001. O carimbo veio na ADR 0039; a leitura, o alerta de cliente travado e a
lista interna vieram na ADR 0040 — que é o passo 3 da RFC, e por isso mora **aqui** e não
num módulo ao lado. Mesma forma de :mod:`portal_api.notifications`,
:mod:`portal_api.conversations` e :mod:`portal_api.retention`, e pelo mesmo motivo: se "o
que conta como degrau" estiver espalhado pelos sete caminhos que o produzem, a pergunta que
a RFC 001 quer responder — *quanto o cliente demora do ganho até o primeiro valor* — deixa
de caber num arquivo, e é justamente essa a pergunta de quem calibra o alerta.

A escrita é uma função só, e nenhuma que edite: o carimbo é **imutável** por desenho
(``UniqueConstraint`` + ``ON CONFLICT DO NOTHING``), e a migração 0024 não dá GRANT de
``UPDATE`` a ninguém. Primeira vez é primeira vez. A leitura é computação **na leitura**, na
forma de :mod:`portal_api.results`: nada é derivado na escrita, e onde falta base ela
declara a lacuna em vez de exibir um zero que ninguém pode conferir.

**A escrita roda sob ``portal_system``, em transação própria**, no precedente do
``chat_limit.consume``. Os degraus nascem em rotas que rodam sob ``portal_app``, e o papel
de requisição não tem policy nesta tabela — porque um caminho de requisição capaz de
escrever o próprio degrau é um caminho capaz de falsear o próprio engajamento.

**Falha em silêncio**, e é decisão declarada: medir engajamento não pode derrubar o que o
cliente veio fazer. Um degrau perdido é um dado a menos numa métrica de tendência; uma exceção
propagada seria um download que não acontece ou um dashboard que não abre.
"""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from portal_api import notifications, retention
from portal_api.ai import quota
from portal_api.config import Settings
from portal_api.db.session import DbRole, get_session
from portal_api.models import (
    Document,
    MemberRole,
    Membership,
    NotificationKind,
    OnboardingStep,
    OnboardingStepName,
    Organization,
    OrganizationRetentionPolicy,
    PendingItem,
    PendingState,
    Project,
    User,
)
from portal_api.scanner import ScanState

logger = logging.getLogger(__name__)


def stamp(
    organization_id: uuid.UUID,
    step: OnboardingStepName,
    *,
    user_id: uuid.UUID | None = None,
    reached_at: datetime | None = None,
) -> bool:
    """Carimba a **primeira** ocorrência de ``step`` nesta organização.

    Devolve ``True`` só quando a linha nasceu agora — é o que distingue "aconteceu pela
    primeira vez" de "acontece toda vez", e é por isso que o log sai apenas no primeiro.
    Sem isso, o evento viraria uma linha por download e por pergunta, que é ruído com nome
    de sinal.

    ``reached_at`` existe para o degrau que **não** nasce agora: o do entregável chega pelo
    sync, e a data que interessa é a do fato afirmado pelo Biahflow, não a da linha.

    Esta é a porta de quem **não** tem transação de sistema em mãos — as cinco rotas que
    rodam sob ``portal_app``. Quem já está numa (o sync) usa :func:`stamp_within`, e o
    porquê está lá.
    """
    try:
        with get_session(role=DbRole.system) as session:
            return stamp_within(
                session, organization_id, step, user_id=user_id, reached_at=reached_at
            )
    except Exception:  # noqa: BLE001 - ver o docstring do módulo: falha em silêncio
        # Sobra o que `stamp_within` não consegue engolir: abrir a conexão, e o `COMMIT` da
        # saída do `with`. O `except` de lá cobre o `INSERT`.
        logger.exception(
            "onboarding.stamp_failed",
            extra={
                "organization_id": str(organization_id),
                "step": getattr(step, "value", str(step)),
            },
        )
        return False


def stamp_within(
    session: Session,
    organization_id: uuid.UUID,
    step: OnboardingStepName,
    *,
    user_id: uuid.UUID | None = None,
    reached_at: datetime | None = None,
) -> bool:
    """O mesmo carimbo, **dentro** de uma transação de sistema que o chamador já abriu.

    Existe por um defeito medido, e ele era da ADR 0039: o sync chamava :func:`stamp`, que
    abre sessão **própria**, de dentro da transação que **cria a organização**. No primeiro
    snapshot de um cliente novo a linha ``organization`` ainda não estava comitada, então o
    ``INSERT`` batia na chave estrangeira, o ``except`` engolia e saía
    ``onboarding.stamp_failed`` — que o ``alerts.md`` descreve como "ruído de
    indisponibilidade momentânea do banco", diagnóstico falso. O degrau só era carimbado no
    snapshot **seguinte** daquele projeto, e para um cliente com um projeto só isso podia
    demorar semanas. O sétimo degrau (ADR 0041) tornou o caso central em vez de raro: a
    aceitação do artefato é justamente o fato que chega no primeiro snapshot.

    A sessão separada nunca comprou nada aqui: ``sync_snapshot`` **já** roda sob
    ``portal_system``, que é o papel que escreve o funil. O que ela comprava era isolamento
    de falha, e isso o ``SAVEPOINT`` dá sem trocar a ordem — o carimbo passa a ser atômico
    com o fato que o justifica, e uma falha nele desfaz só a si mesma.
    """
    now = reached_at or datetime.now(timezone.utc)
    try:
        # `begin_nested` e não um `try` seco: um `IntegrityError` deixa a transação do
        # Postgres em estado abortado, e sem o SAVEPOINT engolir a exceção derrubaria o
        # snapshot inteiro no `COMMIT` seguinte — trocando um degrau perdido por um sync
        # perdido, que é exatamente o que o docstring do módulo proíbe.
        with session.begin_nested():
            result = session.execute(
                pg_insert(OnboardingStep.__table__)
                .values(
                    id=uuid.uuid4(),
                    organization_id=organization_id,
                    step=step.value,
                    reached_at=now,
                    user_id=user_id,
                )
                .on_conflict_do_nothing(index_elements=["organization_id", "step"])
                # `RETURNING`, e **não** `rowcount`: medido, o driver devolve `-1` para
                # `ON CONFLICT DO NOTHING` nos dois casos, e `bool(-1)` é `True` — de modo
                # que todo carimbo se declararia "primeira vez" e o evento sairia a cada
                # download. Com `DO NOTHING`, `RETURNING` não devolve linha quando pula, que
                # é a única resposta confiável à pergunta "nasceu agora?".
                .returning(OnboardingStep.__table__.c.id)
            )
            created = result.first() is not None
    except Exception:  # noqa: BLE001 - ver o docstring do módulo: falha em silêncio
        # `exception` e não `warning`: o traceback é a única forma de descobrir por que o
        # funil parou de encher, e ninguém vai reparar na falta de uma linha.
        logger.exception(
            "onboarding.stamp_failed",
            # `getattr` e não `step.value`: o caminho de erro não pode ter erro próprio —
            # um `step` inesperado faria a linha de log estourar dentro do `except` e
            # ressuscitaria a exceção que este bloco existe para engolir.
            extra={
                "organization_id": str(organization_id),
                "step": getattr(step, "value", str(step)),
            },
        )
        return False

    if created:
        # Sem conteúdo: só o tenant e o nome do degrau. Comportamento de pessoa
        # identificada é dado sensível, e o log não é o lugar dele — o `user_id` fica na
        # linha, onde a retenção e o apagamento o alcançam.
        logger.info(
            "onboarding.step_reached",
            extra={"organization_id": str(organization_id), "step": step.value},
        )
    return created


# --------------------------------------------------------------------------------------
# A leitura (ADR 0040) — o passo 3 da RFC 001.
# --------------------------------------------------------------------------------------

#: Os degraus na ordem de **valor**, que não é a ordem do relógio.
#:
#: O degrau atual é o **primeiro sem carimbo**, e não "o mais alto alcançado + 1". A
#: diferença foi forçada por um caso que existe: ``stamp`` aceita ``reached_at`` justamente
#: para o degrau do Biahflow, que chega pelo sync com a data do fato — de modo que um
#: cliente pode ter ``first_deliverable_delivered`` carimbado com data **anterior** ao
#: ``first_login`` que nunca aconteceu. Qualquer regra de "mais alto alcançado" diria que
#: esse cliente completou o funil; a regra do mais baixo em aberto diz que ele está travado
#: no login, que é a verdade — entregamos algo que ele nunca viu.
#:
#: ``artifact_accepted`` entra **primeiro** (ADR 0041) porque a aprovação precede o projeto:
#: aceitar o contrato é o que faz o projeto existir, e é dele que sai a data do **ganho** de
#: que a régua da RFC 001 — o *time-to-first-value* — precisa para começar do lugar certo.
LADDER: tuple[OnboardingStepName, ...] = (
    OnboardingStepName.artifact_accepted,
    OnboardingStepName.first_login,
    OnboardingStepName.first_document_opened,
    OnboardingStepName.first_pending_answered,
    OnboardingStepName.first_chat_turn,
    OnboardingStepName.first_roi_seen,
    OnboardingStepName.first_deliverable_delivered,
)

#: Onde a medição começou: a migração 0024 (ADR 0039).
#:
#: **Constante de módulo, e não setting.** É um fato sobre este código, não uma configuração
#: — e uma setting convidaria a "consertar" o alerta movendo a data, que é apagar a lacuna
#: em vez de declará-la.
#:
#: **E não derivada.** ``min(reached_at)`` sobre a tabela foi considerado e recusado por
#: duas razões que o próprio repositório impõe: a purga por idade come os carimbos mais
#: antigos (:func:`portal_api.retention.purge_expired`, por ``reached_at``), e o degrau do
#: Biahflow chega com data retroativa. Uma fronteira que se move com o dado não é fronteira.
INSTRUMENTED_SINCE = datetime(2026, 8, 7, tzinfo=timezone.utc)


class Blame(str, enum.Enum):
    """De quem é a vez. Os dois **nunca** se somam na mesma contagem (FDD 020).

    Se o degrau não avança porque a entrega não saiu, o alerta é sobre a equipe — e
    confundir os dois na hora de priorizar é o que faz um radar virar relatório.
    """

    #: O cliente tem tudo o que precisa e não veio.
    client = "client"
    #: Falta alguma coisa nossa. O nome é ``us`` e não ``team`` porque o degrau do
    #: entregável é do Biahflow, que também somos nós do ponto de vista do cliente.
    us = "us"


@dataclass(frozen=True)
class FunnelReading:
    """O estado do funil de uma organização, computado na leitura."""

    organization_id: uuid.UUID
    #: O primeiro degrau sem carimbo, ou ``None`` quando os sete foram alcançados.
    current_step: OnboardingStepName | None
    blame: Blame | None
    #: ``None`` é **lacuna**, jamais zero: ver :data:`INSTRUMENTED_SINCE` e ``gaps``.
    days_stuck: int | None
    threshold_days: int
    stuck: bool
    next_action: str
    #: Desde quando os dias são contados, e de onde essa data saiu. Viajam juntos na
    #: resposta pela disciplina do ``results.py``: um contador que ninguém consegue refazer
    #: não é auditável.
    anchor_at: datetime
    anchor_source: str
    gaps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AlertOutcome:
    """O que o tick fez com uma organização."""

    reading: FunnelReading
    #: Quantas linhas de notificação nasceram agora. Zero significa "o sino já tem".
    notified: int = 0
    #: O projeto que ancorou o aviso, para o digest ser enfileirado depois do commit.
    project_id: uuid.UUID | None = None


#: A frase sobre a qual a pessoa age, por degrau e por lado.
#:
#: Mapa estático porque a IA é o **passo 4** da RFC 001, e é isto que ela substitui quando
#: vier. Enquanto não vem, esta é a fatia inteira do valor: um alerta sem o que fazer é um
#: relatório com um sino em cima.
NEXT_ACTION: dict[tuple[OnboardingStepName, Blame], str] = {
    (OnboardingStepName.artifact_accepted, Blame.us): (
        "Nenhuma aprovação deste cliente está registrada no Biahflow. Registre o "
        "artefato aceito lá — sem ele o funil conta os dias do convite, e não do ganho."
    ),
    (OnboardingStepName.first_login, Blame.us): (
        "Ninguém do cliente foi convidado. Convide em /admin."
    ),
    (OnboardingStepName.first_login, Blame.client): (
        "Convite enviado e nunca usado — ligue. Aos nove dias ainda se resolve com um "
        "telefonema; aos trinta virou churn."
    ),
    (OnboardingStepName.first_document_opened, Blame.us): (
        "Não há documento que o cliente possa abrir. Publique o contrato ou o "
        "diagnóstico em /admin/knowledge."
    ),
    (OnboardingStepName.first_document_opened, Blame.client): (
        "Há documento disponível e ele não foi aberto. Aponte-o no próximo contato."
    ),
    (OnboardingStepName.first_pending_answered, Blame.us): (
        "Não há pendência aberta para o cliente responder. Abra a próxima pergunta no "
        "Biahflow."
    ),
    (OnboardingStepName.first_pending_answered, Blame.client): (
        "Há pendência aberta e sem resposta. Cobre por telefone — o comentário na "
        "pendência avisa os dois lados."
    ),
    (OnboardingStepName.first_chat_turn, Blame.us): (
        "O teto de gasto de IA desta organização está em zero e o assistente recusa "
        "responder. Reveja em /admin/organization."
    ),
    (OnboardingStepName.first_chat_turn, Blame.client): (
        "O cliente nunca perguntou nada ao assistente. Mostre-o na próxima reunião."
    ),
    (OnboardingStepName.first_roi_seen, Blame.us): (
        "O Biahflow não afirma ROI para nenhum projeto vivo desta organização, e o "
        "dashboard mostra a lacuna. Preencha lá."
    ),
    (OnboardingStepName.first_roi_seen, Blame.client): (
        "Há ROI no dashboard e o cliente não voltou para vê-lo. Leve o número a ele."
    ),
    (OnboardingStepName.first_deliverable_delivered, Blame.us): (
        "Nenhum entregável saiu de `pending` no Biahflow. A entrega é nossa."
    ),
}

#: O degrau completo, que não tem ação nem lado.
_ALL_DONE = "Os sete degraus foram alcançados. Nada a fazer."

#: O rótulo humano do degrau, para o título do aviso. Fica aqui e não na tela porque o sino
#: também o mostra, e duas traduções do mesmo enum divergem na primeira que for editada.
_STEP_LABEL: dict[OnboardingStepName, str] = {
    OnboardingStepName.artifact_accepted: "nenhuma aprovação registrada",
    OnboardingStepName.first_login: "nunca entrou no portal",
    OnboardingStepName.first_document_opened: "nunca abriu um documento",
    OnboardingStepName.first_pending_answered: "nunca respondeu uma pendência",
    OnboardingStepName.first_chat_turn: "nunca perguntou ao assistente",
    OnboardingStepName.first_roi_seen: "nunca viu o ROI",
    OnboardingStepName.first_deliverable_delivered: "nenhum entregável liberado",
}


def _threshold_days(step: OnboardingStepName, settings: Settings) -> int:
    if step is OnboardingStepName.first_login:
        return settings.onboarding_alert_login_days
    if step in (
        OnboardingStepName.first_deliverable_delivered,
        # `artifact_accepted` acompanha o do entregável pelo argumento escrito no
        # `config.py`: os dois são sempre nossos, e cobrá-los cedo transformaria o radar de
        # engajamento num relatório de execução — que é o que a saúde do projeto já faz.
        OnboardingStepName.artifact_accepted,
    ):
        return settings.onboarding_alert_deliverable_days
    return settings.onboarding_alert_step_days


def _blame_for(
    session: Session,
    organization_id: uuid.UUID,
    step: OnboardingStepName,
    settings: Settings,
) -> Blame:
    """De quem é a vez neste degrau — e cada ramo espelha o **produtor** do carimbo.

    A regra é a mesma em todos: se falta alguma coisa que só nós podemos pôr no lugar, o
    cliente não tem como avançar e o alerta é sobre a equipe.
    """
    if step is OnboardingStepName.first_login:
        # `is_internal` (coluna de `user`) e `role == client_member` (coluna de
        # `membership`) são flags diferentes, e o produtor do carimbo usa a **primeira**
        # (`if not internal`, em `main.py`). Sem o join, a regra e o produtor discordariam
        # sobre uma conta interna que tenha papel de cliente.
        has_client = session.execute(
            select(
                exists().where(
                    Membership.organization_id == organization_id,
                    Membership.role == MemberRole.client_member,
                    Membership.user_id == User.id,
                    User.is_internal.is_(False),
                )
            )
        ).scalar()
        return Blame.client if has_client else Blame.us

    if step is OnboardingStepName.first_document_opened:
        # A condição é a da rota que carimba (o **download**), e não `ingest_state`: um
        # documento indexado sem `storage_key` é a linha espelhada do Biahflow — metadado e
        # link — e não é baixável. Cobrar do cliente que abrisse o que não abre seria um
        # "travou no cliente" falso.
        has_downloadable = session.execute(
            select(
                exists().where(
                    Document.organization_id == organization_id,
                    Document.storage_key.is_not(None),
                    Document.scan_state.in_((ScanState.clean, ScanState.skipped)),
                )
            )
        ).scalar()
        return Blame.client if has_downloadable else Blame.us

    if step is OnboardingStepName.first_pending_answered:
        has_open = session.execute(
            select(
                exists().where(
                    PendingItem.organization_id == organization_id,
                    PendingItem.state != PendingState.resolved,
                )
            )
        ).scalar()
        return Blame.client if has_open else Blame.us

    if step is OnboardingStepName.first_chat_turn:
        # A única inferência "em nós" que não é sobre conteúdo faltando: com o teto em
        # zero o assistente recusa toda pergunta (ADR 0022), e culpar o cliente por não
        # perguntar quando **nós** desligamos o assistente é a confusão que a RFC proíbe.
        ceiling = quota.limit_cents(session, organization_id, settings)
        return Blame.us if ceiling == 0 else Blame.client

    if step is OnboardingStepName.first_roi_seen:
        # `project.roi_net`, e **não** premissa financeira nem evento de agente: o carimbo
        # é condicionado ao `roi` que `build_dashboard` projeta dessa coluna. A apuração
        # dos eventos alimenta outro número, que não porteia degrau nenhum.
        has_roi = session.execute(
            select(
                exists().where(
                    Project.organization_id == organization_id,
                    Project.roi_net.is_not(None),
                    Project.archived_at.is_(None),
                    Project.source_deleted_at.is_(None),
                )
            )
        ).scalar()
        return Blame.client if has_roi else Blame.us

    # `first_deliverable_delivered` e `artifact_accepted` são afirmação do Biahflow, e o
    # portal não origina status (ADR 0006/0008). Nos dois não há o que o cliente possa fazer
    # **aqui**: a entrega é nossa, e a aprovação do artefato acontece do outro lado — o portal
    # não a hospeda nem tem como coletá-la, então nada que ele faça nesta tela move o degrau.
    return Blame.us


def _client_has_authenticated(session: Session, organization_id: uuid.UUID) -> bool:
    """Alguém do cliente já entrou alguma vez, segundo o dado que não é do funil.

    ``user.external_subject`` deixa de ser nulo no primeiro login e sobrevive a qualquer
    coisa que a instrumentação tenha perdido — é o sinal que a RFC 001 apontava, e é o único
    degrau que tem corroboração fora do próprio funil.
    """
    return bool(
        session.execute(
            select(
                exists().where(
                    Membership.organization_id == organization_id,
                    Membership.role == MemberRole.client_member,
                    Membership.user_id == User.id,
                    User.is_internal.is_(False),
                    User.external_subject.is_not(None),
                )
            )
        ).scalar()
    )


def _has_live_project(session: Session, organization_id: uuid.UUID) -> bool:
    """Esta organização tem projeto vivo — e é a corroboração do degrau da aprovação.

    **Projeto vivo no Biahflow significa negócio fechado.** Um projeto não nasce lá sem que
    alguém tenha aceitado um artefato ou fechado o contrato por fora, então a existência da
    linha é evidência de que o degrau foi cumprido, mesmo quando o Biahflow não reportou a
    data. É o mesmo papel que :func:`_client_has_authenticated` faz para o login, e existe
    pelo mesmo susto: sem ela **toda** organização anterior à FDD 031 apareceria travada em
    "nenhuma aprovação registrada", e a tela mandaria cobrar um contrato assinado meses atrás.

    O predicado é o mesmo de :func:`organizations_to_watch` e :func:`_anchor_project` —
    arquivado e apagado na origem não contam.
    """
    return bool(
        session.execute(
            select(
                exists().where(
                    Project.organization_id == organization_id,
                    Project.archived_at.is_(None),
                    Project.source_deleted_at.is_(None),
                )
            )
        ).scalar()
    )


def _anchor(
    session: Session, organization_id: uuid.UUID, organization: Organization
) -> tuple[datetime, str]:
    """Desde quando contar os dias, em três camadas.

    O carimbo mais recente é a resposta boa: "há quantos dias este cliente não recebe
    nada", que é o número de que o telefonema precisa. Sem carimbo nenhum, a data em que a
    primeira pessoa do cliente ganhou porta — e **não** a da organização, que o sync cria
    quando o projeto chega do Biahflow, possivelmente dias antes de alguém ser convidado:
    contar esses dias é cobrar do cliente um tempo em que ele não tinha como entrar.
    """
    last = session.execute(
        select(func.max(OnboardingStep.reached_at)).where(
            OnboardingStep.organization_id == organization_id
        )
    ).scalar()
    if last is not None:
        return _aware(last), "step"

    invited = session.execute(
        select(func.min(Membership.created_at)).where(
            Membership.organization_id == organization_id,
            Membership.role == MemberRole.client_member,
        )
    ).scalar()
    if invited is not None:
        # `MIN` e não `MAX`: revogar e reconvidar alguém não pode zerar o relógio do
        # cliente inteiro.
        return _aware(invited), "membership"

    return _aware(organization.created_at), "organization"


def _aware(value: datetime) -> datetime:
    """O Postgres devolve `timestamptz` com fuso; um `datetime` ingênuo aqui seria erro."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def read_funnel(
    session: Session, organization_id: uuid.UUID, settings: Settings
) -> FunnelReading | None:
    """O estado do funil desta organização. ``None`` quando ela não existe.

    Computação **na leitura**, na forma de :mod:`portal_api.results`: nada aqui foi
    derivado na escrita, e onde falta base a resposta é uma lacuna declarada em ``gaps``, e
    não um zero. Um cliente sem carimbo de "primeiro ROI visto" pode não ter chegado lá
    **ou** ser anterior à instrumentação, e as duas coisas não podem sair iguais.
    """
    organization = session.get(Organization, organization_id)
    if organization is None:
        return None

    stamped = set(
        session.execute(
            select(OnboardingStep.step).where(
                OnboardingStep.organization_id == organization_id
            )
        ).scalars()
    )
    # `reached` pode ganhar um degrau que `stamped` não tem (ver o bloco do login abaixo), e
    # os dois conjuntos respondem perguntas diferentes: "onde o cliente está" e "o que a
    # tabela registrou". A purga é sobre a tabela.
    reached = set(stamped)
    anchor_at, anchor_source = _anchor(session, organization_id, organization)
    gaps: list[str] = []

    if anchor_source == "organization":
        gaps.append("no_client_member")

    # **A evidência independente do primeiro login**, e ela é o que impede a medição de
    # nascer cega. `user.external_subject` deixa de ser nulo no primeiro login e não depende
    # do funil — é o sinal que a própria RFC 001 apontava antes de a ADR 0039 escolher
    # carimbar no dashboard. Sem consultá-lo, no primeiro dia da instrumentação **toda**
    # organização existente apareceria travada em "nunca entrou no portal", que é o alerta
    # mais caro que esta fatia poderia produzir: manda ligar justamente para quem está
    # usando o produto.
    if OnboardingStepName.first_login not in reached and _client_has_authenticated(
        session, organization_id
    ):
        reached.add(OnboardingStepName.first_login)
        gaps.append("login_before_instrumentation")

    # **A evidência independente da aprovação** (ADR 0041), e ela é a mesma história um degrau
    # abaixo. `artifact_accepted` só passou a ser reportado pela FDD 031 do Biahflow, então
    # toda organização anterior a ela chega sem o carimbo — e, sendo o primeiro da escada,
    # seria o degrau atual de **todas**. A tela nasceria mandando registrar o contrato de
    # clientes que estão em produção há meses.
    #
    # A corroboração é estrutural: um projeto vivo só existe porque um negócio foi fechado.
    # Ela declara a lacuna em vez de fabricar a data — o degrau conta como alcançado, mas
    # `reached_at` continua sem existir, e é por isso que a âncora daquela organização segue
    # saindo do convite. Quem não tem projeto vivo não recebe a corroboração e fica com o
    # degrau em aberto, o que também é a verdade: não há nem projeto nem aprovação.
    if OnboardingStepName.artifact_accepted not in reached and _has_live_project(
        session, organization_id
    ):
        reached.add(OnboardingStepName.artifact_accepted)
        gaps.append("artifact_not_reported")

    current_step = next((step for step in LADDER if step not in reached), None)

    # A lacuna que a FDD 020 exige: degrau ausente **não** é degrau zerado. Um cliente de
    # junho pode ter aberto um documento em junho, sem carimbo, e o degrau atual apontaria
    # para trás — a incerteza é sobre **o degrau**, e ela vale enquanto a organização for
    # mais velha que a medição. O primeiro degrau escapa dela pelo bloco acima, que tem
    # prova própria; os de cima não têm, e é por isso que uma linha assim **não** conta como
    # travada: ninguém deve ser chamado por um degrau que talvez já tenha sido cumprido.
    uncertain = (
        current_step is not None
        and current_step is not OnboardingStepName.first_login
        and _aware(organization.created_at) < INSTRUMENTED_SINCE
    )
    if uncertain:
        gaps.append("before_instrumentation")

    if not stamped:
        policy = session.execute(
            select(OrganizationRetentionPolicy).where(
                OrganizationRetentionPolicy.organization_id == organization_id
            )
        ).scalar_one_or_none()
        window = retention.windows_for(policy, settings).onboarding_days
        if anchor_at < retention.now() - timedelta(days=window):
            # Zero carimbos numa organização mais velha que a janela de retenção pode ser
            # a purga, não o cliente. Mesma honestidade da linha acima.
            gaps.append("steps_may_have_been_purged")

    if current_step is None:
        return FunnelReading(
            organization_id=organization_id,
            current_step=None,
            blame=None,
            days_stuck=None,
            threshold_days=0,
            stuck=False,
            next_action=_ALL_DONE,
            anchor_at=anchor_at,
            anchor_source=anchor_source,
            gaps=gaps,
        )

    blame = _blame_for(session, organization_id, current_step, settings)
    threshold = _threshold_days(current_step, settings)
    # Sempre a partir de uma data **real** — o último carimbo, o convite ou a criação da
    # organização. O que a FDD 020 proíbe é exibir "0 dias" para quem talvez já tenha
    # passado do degrau, e o zero fabricado só apareceria se a âncora fosse a data da
    # instrumentação. Ela nunca é.
    days = (retention.now() - anchor_at).days

    return FunnelReading(
        organization_id=organization_id,
        current_step=current_step,
        blame=blame,
        days_stuck=days,
        threshold_days=threshold,
        # `stuck` é decidido **aqui** e viaja na resposta: a tela não pode rederivá-lo de
        # `days_stuck > threshold_days` sem pôr a mesma regra em dois lugares — o argumento
        # que o docstring de `_erasure_is_claimable` já escreveu.
        # `uncertain` desqualifica: um degrau que talvez já tenha sido cumprido antes de
        # haver medição não pode virar telefonema.
        stuck=days >= threshold and not uncertain,
        next_action=NEXT_ACTION.get(
            (current_step, blame), "Sem ação sugerida para este degrau."
        ),
        anchor_at=anchor_at,
        anchor_source=anchor_source,
        gaps=gaps,
    )


def organizations_to_watch(session: Session) -> list[uuid.UUID]:
    """As organizações que o alerta vigia: as que têm projeto **vivo**.

    Espelha :func:`portal_api.retention.organizations_with_data` na forma e difere no
    conteúdo, de propósito. ``run_erasure`` apaga os projetos e a ``membership`` e
    **mantém** a linha ``organization`` — é assim que "o que aconteceu com aquele tenant"
    continua tendo resposta (ADR 0017). Sem este filtro, todo tenant apagado viraria uma
    linha perpétua "ninguém foi convidado" com um alerta diário atrás.
    """
    return list(
        session.execute(
            select(Organization.id)
            .join(Project, Project.organization_id == Organization.id)
            .where(Project.archived_at.is_(None), Project.source_deleted_at.is_(None))
            .distinct()
        ).scalars()
    )


def _anchor_project(session: Session, organization_id: uuid.UUID) -> Project | None:
    """O projeto que ancora o aviso: o vivo mais antigo.

    ``Notification`` é escopada por projeto e o funil é escopado por organização, então
    alguma linha tem de ser escolhida. O ``id`` no desempate não é enfeite:
    ``project.created_at`` é ``server_default now()``, e no Postgres ``now()`` é o instante
    de **início da transação** — dois projetos criados pelo mesmo sync recebem o mesmo
    carimbo, e a ordenação por data sozinha não é total. E mesmo que a âncora mude entre
    passagens, o aviso não duplica: o ``dedupe_key`` não carrega projeto.
    """
    return session.execute(
        select(Project)
        .where(
            Project.organization_id == organization_id,
            Project.archived_at.is_(None),
            Project.source_deleted_at.is_(None),
        )
        .order_by(Project.created_at.asc(), Project.id.asc())
        .limit(1)
    ).scalar_one_or_none()


def raise_alert(
    session: Session, organization_id: uuid.UUID, settings: Settings
) -> AlertOutcome | None:
    """Avisa o time interno **uma vez** por organização e degrau travado.

    A memória de "já avisei" não é uma tabela nova: é o ``dedupe_key`` da notificação, com
    ``uq_notification_user_dedupe_key`` e ``ON CONFLICT DO NOTHING``. ``fan_out`` devolve só
    os ids que nasceram, então lista vazia significa "o sino já tem" e o evento não sai.

    A alternativa — persistir o estado do alerta — foi recusada com preço: a tabela do funil
    não aceita ``UPDATE`` de papel nenhum, nem do sistema, então seria tabela própria, com
    policy (o meta-teste de RLS cobra), predicado de purga e uma **terceira** exclusão à mão
    em ``run_erasure``. Tudo para lembrar um booleano que a notificação já lembra.
    """
    reading = read_funnel(session, organization_id, settings)
    if reading is None or not reading.stuck or reading.current_step is None:
        return None

    project = _anchor_project(session, organization_id)
    if project is None:
        return None

    step, blame = reading.current_step, reading.blame or Blame.us
    change = notifications.Change(
        kind=NotificationKind.onboarding_stuck,
        title=f"Conta travada no onboarding: {_STEP_LABEL[step]}",
        detail=reading.next_action,
        # Sem data na chave, ao contrário do `project_status_changed`: lá um projeto
        # **volta** a um status anterior e a segunda transição seria engolida em silêncio.
        # Aqui o fato não recorre — uma vez alcançado, o degrau deixa de ser o degrau
        # travado, e o carimbo é imutável.
        #
        # E **com** o `organization_id`, que não é redundante com a coluna: a unicidade é
        # `(user_id, dedupe_key)`, e um `internal_admin` que administra duas organizações
        # teria o aviso da segunda deduplicado contra o da primeira.
        #
        # Montada aqui e não pelo `_key` de `notifications`: aquele helper existe para o
        # caso em que a chave pode estourar os 255 da coluna, o que acontece quando ela
        # carrega título digitado. Esta tem tamanho fixo — dois literais, um UUID e um
        # rótulo de enum.
        dedupe_key=f"onboarding:stuck:{organization_id}:{step.value}",
        link="/admin/funnel",
    )
    created = notifications.fan_out(session, project, [change])

    if not created:
        # Ou o sino já tem, ou não há ninguém interno a quem avisar — e as duas coisas
        # precisam ser distinguíveis, senão um tenant sem administrador ficaria travado em
        # silêncio absoluto, que é o único desfecho pior que o alerta não existir.
        audience = notifications.recipients(
            session, project, NotificationKind.onboarding_stuck
        )
        if not audience:
            logger.warning(
                "onboarding.alert_undeliverable",
                extra={"organization_id": str(organization_id), "step": step.value},
            )
        return AlertOutcome(reading=reading, notified=0, project_id=project.id)

    logger.warning(
        "onboarding.client_stuck",
        extra={
            "organization_id": str(organization_id),
            "step": step.value,
            "days_stuck": reading.days_stuck,
            "blocked_by": blame.value,
            "threshold_days": reading.threshold_days,
        },
    )
    return AlertOutcome(reading=reading, notified=len(created), project_id=project.id)
