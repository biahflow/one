"""Biahflow integration — the portal's read model mirrors Biahflow (ADR 0006).

Biahflow is the internal source of truth for project status. It notifies the portal via a
signed (HMAC) webhook, and the portal pulls the full project snapshot server-to-server for
backfill/reconciliation. This module verifies signatures, fetches snapshots, and upserts
them into the portal's own models (the read model). Only project data crosses over — never
Biahflow's commercial data.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from portal_api import clock, notifications, pending_comments, results
from portal_api.models import (
    ConversationMessage,
    Decision,
    DeliverableState,
    DigitalEmployee,
    DigitalEmployeeStatus,
    Document,
    DocumentOrigin,
    DocumentSource,
    Engagement,
    EngagementStatus,
    Meeting,
    MemberRole,
    Membership,
    Milestone,
    OnboardingStepName,
    MilestoneState,
    Organization,
    PendingItem,
    PendingOrigin,
    PendingPriority,
    PendingState,
    PhaseDeliverable,
    PhaseState,
    Project,
    ProjectPhase,
    ProjectStatus,
    User,
)
from portal_api.repositories import TenantContext

logger = logging.getLogger(__name__)

# Biahflow status/state → portal enums.
PROJECT_STATUS_MAP: dict[str, ProjectStatus] = {
    "planning": ProjectStatus.discovery,
    "active": ProjectStatus.in_implementation,
    "on_hold": ProjectStatus.paused,
    "completed": ProjectStatus.live,
}
MILESTONE_STATE_MAP: dict[str, MilestoneState] = {
    "todo": MilestoneState.planned,
    "in_progress": MilestoneState.in_progress,
    "done": MilestoneState.done,
}
PHASE_STATE_MAP: dict[str, PhaseState] = {
    "locked": PhaseState.locked,
    "active": PhaseState.active,
    "done": PhaseState.done,
}
DELIVERABLE_STATE_MAP: dict[str, DeliverableState] = {
    "pending": DeliverableState.pending,
    "delivered": DeliverableState.delivered,
}
DIGITAL_EMPLOYEE_STATUS_MAP: dict[str, DigitalEmployeeStatus] = {
    "building": DigitalEmployeeStatus.building,
    "active": DigitalEmployeeStatus.active,
    "paused": DigitalEmployeeStatus.paused,
}
#: O enum canônico do Language Map v1.1 §4, confirmado pela sessão do Pulse em
#: 28/08/2026: o snapshot manda exatamente estes três valores. Um vocabulário novo do
#: outro lado cai em ``active``, no padrão do ``PROJECT_STATUS_MAP`` — a alternativa
#: seria o sync inteiro morrer por causa de uma palavra que ninguém combinou.
ENGAGEMENT_STATUS_MAP: dict[str, EngagementStatus] = {
    "active": EngagementStatus.active,
    "paused": EngagementStatus.paused,
    "closed": EngagementStatus.closed,
}
PENDING_STATE_MAP: dict[str, PendingState] = {
    "open": PendingState.open,
    "resolved": PendingState.resolved,
}
#: A prioridade da pendência, no vocabulário do Biahflow (ADR 0029).
#:
#: **Opcional, e o default é `medium`** — o campo é novo no snapshot e o portal
#: não pode exigir que a outra ponta já o envie. Até esta fatia o sync não o lia
#: de jeito nenhum: a coluna existia com enum desde a Fase 1, o `PendingOut` a
#: declarava e o payload a entregava, e **nada nunca escrevia outro valor**.
#: Uma coluna com contrato e sem produtor é uma constante disfarçada de dado.
PENDING_PRIORITY_MAP: dict[str, PendingPriority] = {
    "low": PendingPriority.low,
    "medium": PendingPriority.medium,
    "high": PendingPriority.high,
}

# Quem responde pelo item, no vocabulário do Biahflow (``party``). "provider" é sempre a
# Biahflow — é o time que responde, não o produto; "client" é a própria organização do
# cliente, resolvida no sync.
PROVIDER_LABEL = "Biahflow"

_SIGNATURE_PREFIX = "sha256="


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Constant-time check of the ``X-Biahflow-Signature`` HMAC header."""
    if not secret or not header:
        return False
    provided = header[len(_SIGNATURE_PREFIX) :] if header.startswith(_SIGNATURE_PREFIX) else header
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def fetch_snapshot(
    base_url: str, token: str, biahflow_project_id: int, *, client: httpx.Client | None = None
) -> dict[str, Any]:
    """Pull the read-only project snapshot from Biahflow (backfill/reconciliation)."""
    url = f"{base_url.rstrip('/')}/portal/projects/{biahflow_project_id}/snapshot/"
    headers = {"Authorization": f"Bearer {token}"}
    if client is not None:
        response = client.get(url, headers=headers)
    else:
        response = httpx.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return dict(response.json())


def org_slug(biahflow_account_id: int) -> str:
    """A identidade da organização espelhada, e o nome dela é **histórico**.

    O termo canônico é Account desde o Language Map v1.1, e este literal continua
    ``biahflow-client-`` de propósito: o slug é **chave de persistência**, não
    vocabulário. Toda organização já sincronizada está gravada com este prefixo, e
    trocá-lo faria o ``select`` por slug não achar nenhuma delas — o sync criaria
    uma organização nova ao lado, órfã de membership, de projeto e de índice. O
    vocabulário muda na leitura (``account or client``, em :func:`sync_snapshot`);
    a chave, não.
    """
    return f"biahflow-client-{biahflow_account_id}"


def project_slug(biahflow_project_id: int) -> str:
    return f"biahflow-{biahflow_project_id}"


def engagement_slug(biahflow_engagement_id: int) -> str:
    """A identidade do programa espelhado, na forma de :func:`project_slug`.

    Nasce já com o termo canônico porque não há linha gravada para órfãoar: o
    Engagement chega com esta fatia.
    """
    return f"biahflow-engagement-{biahflow_engagement_id}"


def _party_label(party: str | None, organization_name: str) -> str | None:
    """``party`` do Biahflow → rótulo exibível de responsável."""
    if party == "provider":
        return PROVIDER_LABEL
    if party == "client":
        return organization_name
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    """Datetime ISO do snapshot; tolera ``Z`` no lugar do offset."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_date(value: str | None) -> date | None:
    """Data ISO do snapshot (sem hora). O `decided_on` de uma decisão é um dia, não um instante."""
    if not value:
        return None
    return date.fromisoformat(value)


#: A hora que a projeção carimba veio da **origem**: o Biahflow observou aquele estado
#: naquele instante. É a idade do dado.
FRESHNESS_OBSERVED = "observed"

#: A hora que a projeção carimba é a da **cópia**: o portal sincronizou naquele instante e
#: não sabe quando a origem observou. É o fallback declarado da ADR 0076 — uma resposta pior
#: à mesma pergunta, dita honestamente, no precedente do embedder offline e do
#: ``scan_state=skipped``.
FRESHNESS_SYNCED = "synced"


def _projection_version(value: Any) -> int | None:
    """A versão de projeção do envelope, quando a origem a carimba.

    Tolera o inteiro vindo como texto (é o que um JSON gerado à mão costuma trazer) e
    devolve ``None`` para qualquer coisa que não seja um inteiro — inclusive ``bool``, que
    em Python é ``int`` e viraria "versão 1" sem esta linha. Ausência e lixo caem no mesmo
    lugar de propósito: **ausência de afirmação**, nunca "versão zero", que faria a
    reconciliação da ADR 0076 ler o desconhecido como o mais velho possível.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def freshness(project: Project) -> tuple[str, datetime] | None:
    """Como o portal soube a hora que projeta, e qual hora é essa (ADR 0076).

    ``(FRESHNESS_OBSERVED, …)`` quando a origem carimbou ``observed_at``;
    ``(FRESHNESS_SYNCED, …)`` quando não carimbou e tudo o que existe é a hora da cópia;
    ``None`` quando não há carimbo nenhum — um projeto anterior a esta fatia que ainda não
    passou por um sync. **Sem hora de verdade não se inventa uma**: a ADR 0026 já removeu da
    tela um "Atualizado há 2 dias" que ninguém tinha como sustentar, e a ADR 0076 repete a
    regra ao dizer que sem ``observed_at`` real não há carimbo.

    A escolha não é uma preferência avaliada aqui e sim uma consequência: ``sync_snapshot``
    mantém as duas colunas **mutuamente exclusivas**, então no máximo uma está preenchida e
    não há como o rótulo discordar do instante. Um terceiro campo com o rótulo escrito seria
    a mesma regra em dois lugares — o argumento do ``textfold.py`` — e poderia divergir.
    """
    if project.observed_at is not None:
        return (FRESHNESS_OBSERVED, project.observed_at)
    if project.synced_at is not None:
        return (FRESHNESS_SYNCED, project.synced_at)
    return None


def _regression(
    project: Project, version: int | None, observed_at: datetime | None
) -> str | None:
    """Por que este snapshot é mais **velho** que o já aplicado — ou ``None`` se não é.

    Generaliza o que ``mark_project_deleted`` já fazia para uma coluna ("a primeira
    observação é a verdadeira") para o snapshot inteiro (ADR 0076 §3). O sync é idempotente
    por **substituição** — apaga e reinsere fases, marcos, decisões e pendências —, então
    um webhook atrasado ou reentregue dispara um fetch, e até esta fatia o fetch de um
    estado mais velho era aplicado por cima do mais novo sem que nada percebesse.

    A ordem dos critérios é a da ADR, e cada um existe porque o outro não basta:

    1. **``projection_version``**, quando os dois lados a têm. É o inteiro monotônico por
       projeto, e é o único critério que sobrevive a um relógio de origem que regride.
    2. **``observed_at``**, no **empate** de versão — e também quando a versão não está nos
       dois lados, porque uma observação estritamente anterior da origem é uma regressão
       ainda que ninguém tenha numerado.

    E há duas ausências deliberadas:

    - **Versão só de um lado não recusa nada.** Tratar ausência como "menor" barraria um
      snapshot legítimo de uma origem que ainda não numera — e ausência é ausência de
      afirmação, não versão zero. É o comportamento atual, declarado (ADR 0076).
    - **``synced_at`` não entra na comparação.** Ele é ``now()`` por construção, então
      ordena as *cópias* e não os *estados*: comparar por ele nunca recusaria nada, e
      pareceria proteção. O limite é declarado, não fingido.
    """
    current = project.projection_version
    if version is not None and current is not None:
        if version < current:
            return "version"
        if version > current:
            return None
    if (
        observed_at is not None
        and project.observed_at is not None
        and observed_at < project.observed_at
    ):
        return "observed_at"
    return None


def _upsert_engagement(
    session: Session, organization: Organization, data: dict[str, Any]
) -> Engagement:
    """O programa do snapshot, espelhado. Idempotente, chaveado por ``(org, slug)``.

    Numa função própria pela razão de ``_party_label`` estar numa: ``sync_snapshot``
    já é o arquivo inteiro do espelho, e um upsert a mais no meio dele deixa de ser
    legível. **Nunca cria organização** — recebe a que ``sync_snapshot`` já resolveu,
    porque um engagement sem conta é um tenant sem dono.
    """
    slug = engagement_slug(data["id"])
    engagement = session.execute(
        select(Engagement).where(
            Engagement.organization_id == organization.id, Engagement.slug == slug
        )
    ).scalar_one_or_none()
    if engagement is None:
        engagement = Engagement(organization_id=organization.id, slug=slug)
        session.add(engagement)
    engagement.name = data["name"]
    engagement.status = ENGAGEMENT_STATUS_MAP.get(
        data.get("status") or "", EngagementStatus.active
    )
    session.flush()  # precisamos do `engagement.id` para apontar o projeto
    return engagement


def sync_snapshot(session: Session, snapshot: dict[str, Any]) -> Project:
    """Upsert a Biahflow snapshot into the portal read model. Idempotent.

    Também é o produtor das notificações (ADR 0012): o portal não origina status,
    então a única forma de saber que algo *mudou* é comparar o read model antes e
    depois do upsert. O estado é fotografado antes de qualquer escrita e o diff
    sai no fim — ver :mod:`portal_api.notifications`.

    E é onde a projeção **recusa regressão** (ADR 0076): um snapshot mais velho que o já
    aplicado — por ``projection_version`` ou, no empate, por ``observed_at`` — é ignorado
    por inteiro, com ``projection.stale_rejected`` no log e o projeto devolvido como está.
    Ver :func:`_regression` para os critérios e para o que **não** entra neles.
    """
    project_data = snapshot["project"]
    # **``account`` primeiro, ``client`` depois** (Language Map v1.1 §5, ADR 0079). O
    # Biahflow passa a mandar a chave canônica e mantém a antiga em paralelo até a
    # `/api/v2/` dele, então ler nesta ordem cobre os dois lados sem sincronizar
    # deploys. O `[...]` no fallback é deliberado: um snapshot sem nenhuma das duas
    # chaves não tem organização, e falhar alto é a resposta certa — inventar tenant
    # é o que a regra 1 do `AGENTS.md` proíbe.
    account_data = project_data.get("account") or project_data["client"]

    organization = session.execute(
        select(Organization).where(Organization.slug == org_slug(account_data["id"]))
    ).scalar_one_or_none()
    if organization is None:
        organization = Organization(name=account_data["name"], slug=org_slug(account_data["id"]))
        session.add(organization)
        session.flush()

    slug = project_slug(project_data["id"])
    project = session.execute(
        select(Project).where(
            Project.organization_id == organization.id, Project.slug == slug
        )
    ).scalar_one_or_none()

    # Reconciliação anti-regressão (ADR 0076 §3), **antes de qualquer escrita**: um snapshot
    # mais velho do que o já aplicado é ignorado por inteiro. Não é o portal decidindo a fase
    # — ele continua sem originar status (ADR 0006/0008) — é o portal não desaprendendo o que
    # já observou.
    #
    # A recusa vem antes do retrato de `snapshot_state` e antes do rename da organização de
    # propósito: recusar "quase tudo" deixaria o cliente com o nome velho vindo de um webhook
    # atrasado, e uma recusa que aplica metade do snapshot não é uma recusa.
    observed_at = _parse_datetime(snapshot.get("observed_at"))
    incoming_version = _projection_version(snapshot.get("projection_version"))
    if project is not None:
        regression = _regression(project, incoming_version, observed_at)
        if regression is not None:
            logger.warning(
                "projection.stale_rejected",
                extra={
                    "project_id": str(project.id),
                    "biahflow_project_id": project_data["id"],
                    "reason": regression,
                    "applied_version": project.projection_version,
                    "rejected_version": incoming_version,
                },
            )
            return project

    organization.name = account_data["name"]
    # Antes de qualquer escrita: é este retrato que vira notificação lá embaixo.
    # `None` para um projeto que ainda não existe, e é o que faz o primeiro sync
    # chegar em silêncio em vez de com uma caixa de entrada cheia.
    before = notifications.snapshot_state(session, project)

    # O programa a que este projeto pertence (Language Map v1.1 §2, ADR 0079).
    #
    # **Depois do retrato**, e não antes: `_upsert_engagement` grava, e a linha acima
    # afirma que nada foi gravado até ali. O engagement não entra no `diff` hoje — mas
    # a frase é o invariante que faz o `diff` significar alguma coisa, e um dia em que
    # `snapshot_state` passe a ler o programa, a ordem errada faria a mudança dele
    # nascer invisível para o aviso.
    #
    # **Ausente não é negação**, o mesmo argumento já escrito para
    # `artifact_accepted_at` mais abaixo: um Biahflow anterior a esta fatia manda o
    # corpo sem a chave, e zerar `engagement_id` ali apagaria um vínculo verdadeiro.
    # Presente, o upsert é por `(organization_id, slug)` como o do projeto.
    engagement_data = project_data.get("engagement")
    if engagement_data is not None:
        engagement = _upsert_engagement(session, organization, engagement_data)
    else:
        engagement = None

    if project is None:
        project = Project(organization_id=organization.id, slug=slug)
        session.add(project)
    project.name = project_data["name"]
    # Só aponta quando o snapshot afirmou. Ver o `_upsert_engagement` acima: a
    # atribuição condicional é o oposto da do `archived_at`, e de propósito — lá
    # `None` é um valor que a origem sabe desfazer, aqui `None` é silêncio.
    if engagement is not None:
        project.engagement_id = engagement.id
    project.status = PROJECT_STATUS_MAP.get(project_data["status"], ProjectStatus.discovery)
    project.completion_percent = int(snapshot.get("completion", 0))

    # ROI e próxima reunião (denormalizados do snapshot para o dashboard do cliente).
    roi = snapshot.get("roi") or {}
    project.roi_net = roi.get("net")
    project.roi_ratio = roi.get("roi")
    next_meeting = snapshot.get("next_meeting")
    project.next_meeting_title = next_meeting["title"] if next_meeting else None
    project.next_meeting_date = (
        date.fromisoformat(next_meeting["date"]) if next_meeting else None
    )
    snapshot_health = snapshot.get("health") or {}
    project.health_label = snapshot_health.get("label")
    project.health_level = snapshot_health.get("level")
    # Arquivamento (ADR 0036). Lido com `.get`, como todo o resto: um Biahflow anterior à fatia
    # simplesmente não manda a chave, e ausência aqui significa ativo. A atribuição é
    # incondicional de propósito — `None` é um valor, não "não mexa" —, porque a interface de lá
    # restaura por item e um campo que só soubesse ir deixaria o projeto marcado como encerrado
    # depois de o arquivamento ser desfeito.
    archived_at = project_data.get("archived_at")
    project.archived_at = datetime.fromisoformat(archived_at) if archived_at else None
    # Frescor e versão do **envelope** (ADR 0076), e não por entidade: o snapshot descreve
    # um estado do projeto inteiro, e uma hora por linha diria coisas diferentes sobre a
    # mesma observação. Lidos com `.get`, como todo o resto — um Biahflow anterior a esta
    # fatia não manda as chaves, e ausência é ausência de afirmação.
    #
    # As duas colunas de hora são **mutuamente exclusivas**, e é o que torna o rótulo
    # impossível de errar (ver `freshness()`): carimbar as duas deixaria a projeção com dois
    # instantes e nenhuma regra escrita sobre qual deles a tela mostra. Com a origem
    # carimbando, vale a hora dela; sem ela, o fallback declarado é a hora da cópia —
    # rotulada como cópia, nunca disfarçada de observação da origem, que é a falsa precisão
    # que `results.py` recusa e que a ADR 0026 apagou da tela.
    #
    # A atribuição é incondicional pelo argumento do `archived_at` logo acima: `None` é um
    # valor, não "não mexa". Se a origem parar de carimbar, a projeção precisa **degradar**
    # para "sincronizado há X" em vez de seguir exibindo um `observed_at` velho como se
    # fosse a última observação.
    project.observed_at = observed_at
    project.synced_at = None if observed_at is not None else datetime.now(timezone.utc)
    project.projection_version = incoming_version
    # `source_deleted_at` **não** entra aqui, e a ausência é a decisão (ADR 0037): um projeto
    # apagado no Biahflow não tem snapshot, então chegar até esta função já significaria que o id
    # voltou a existir — outro projeto reusando o número, que é problema diferente e não uma
    # restauração. Reescrever a coluna aqui apagaria o fato que só o webhook consegue contar.
    session.flush()

    # Read model: milestones are fully replaced from the snapshot so removals propagate.
    session.execute(delete(Milestone).where(Milestone.project_id == project.id))
    for position, milestone in enumerate(snapshot.get("milestones", [])):
        due = milestone.get("due_date")
        session.add(
            Milestone(
                organization_id=organization.id,
                project_id=project.id,
                title=milestone["title"],
                due_date=date.fromisoformat(due) if due else None,
                owner_label=_party_label(milestone.get("party"), organization.name),
                state=MILESTONE_STATE_MAP.get(milestone["status"], MilestoneState.planned),
                position=position,
            )
        )

    # Os degraus do funil que **nascem no Biahflow** (RFC 001). Só saem de afirmação do
    # snapshot — ausência não é negação, e um sync truncado não pode virar degrau falso.
    #
    # O primeiro entregável fora de `pending`, e a primeira aprovação do cliente. O segundo
    # chegou depois (ADR 0041): até a FDD 031 de lá o snapshot não carregava artefato nenhum,
    # e `.get` sem default continua sendo o certo — um Biahflow anterior àquela fatia manda
    # um corpo sem a chave, e isso é ausência de afirmação, não negação.
    delivered_seen = False
    accepted_at = _parse_datetime(snapshot.get("artifact_accepted_at"))
    # Journey phases + deliverables are also fully replaced (deliverables first, FK order).
    journey = snapshot.get("journey") or {}
    session.execute(delete(PhaseDeliverable).where(PhaseDeliverable.project_id == project.id))
    session.execute(delete(ProjectPhase).where(ProjectPhase.project_id == project.id))
    session.flush()
    for position, phase_data in enumerate(journey.get("phases", [])):
        target = phase_data.get("target_date")
        phase = ProjectPhase(
            organization_id=organization.id,
            project_id=project.id,
            name=phase_data["name"],
            description=phase_data.get("description") or None,
            position=phase_data.get("position", position),
            state=PHASE_STATE_MAP.get(phase_data["status"], PhaseState.locked),
            target_date=date.fromisoformat(target) if target else None,
        )
        session.add(phase)
        session.flush()  # precisamos do phase.id para os entregáveis
        for deliverable_position, deliverable in enumerate(phase_data.get("deliverables", [])):
            session.add(
                PhaseDeliverable(
                    organization_id=organization.id,
                    project_id=project.id,
                    phase_id=phase.id,
                    name=deliverable["name"],
                    position=deliverable_position,
                    state=DELIVERABLE_STATE_MAP.get(
                        deliverable["status"], DeliverableState.pending
                    ),
                    link=deliverable.get("link"),
                    # O id de lá, que é a única identidade do entregável que
                    # sobrevive ao `delete` acima (ADR 0077). `.get` sem default
                    # pelo argumento do `artifact_accepted_at`: um Biahflow que
                    # não mande a chave está calado, não negando — e `str()`
                    # porque lá é a chave primária inteira do Django, como no
                    # `external_ref` da pendência.
                    external_ref=(
                        str(deliverable["id"])
                        if deliverable.get("id") is not None
                        else None
                    ),
                )
            )
            if (
                DELIVERABLE_STATE_MAP.get(deliverable["status"], DeliverableState.pending)
                is DeliverableState.delivered
            ):
                delivered_seen = True

    # Funcionários Digitais também são totalmente substituídos pelo snapshot.
    session.execute(delete(DigitalEmployee).where(DigitalEmployee.project_id == project.id))
    for employee in snapshot.get("digital_employees", []):
        session.add(
            DigitalEmployee(
                organization_id=organization.id,
                project_id=project.id,
                name=employee["name"],
                area=employee.get("area") or None,
                description=employee.get("description") or None,
                status=DIGITAL_EMPLOYEE_STATUS_MAP.get(
                    employee["status"], DigitalEmployeeStatus.building
                ),
                kpi_label=employee.get("kpi_label") or None,
                kpi_value=employee.get("kpi_value") or None,
                hours_saved_month=employee.get("hours_saved_month"),
                roi_month=employee.get("roi_month"),
            )
        )

    # Documentos: metadados apenas — o arquivo do Biahflow continua no Drive. Só
    # os espelhados de lá são substituídos; os de origem `portal` (enviados na
    # tela de administração e indexados, ADR 0014) sobrevivem ao sync, pelo mesmo
    # motivo das pendências abaixo. Sem esta distinção, todo arquivo enviado
    # morreria — junto do índice dele — no próximo webhook.
    session.execute(
        delete(Document).where(
            Document.project_id == project.id,
            Document.origin == DocumentOrigin.biahflow,
        )
    )
    for document in snapshot.get("documents", []):
        link = document.get("link") or None
        session.add(
            Document(
                organization_id=organization.id,
                project_id=project.id,
                title=document["name"],
                source=DocumentSource.drive if link else DocumentSource.upload,
                origin=DocumentOrigin.biahflow,
                external_id=str(document["id"]),
                link=link,
                author_label=document.get("author") or None,
                source_updated_at=_parse_datetime(document.get("created_at")),
            )
        )

    # **Decisões antes de reuniões, e a ordem é dependência.** `Decision.meeting_id` é
    # FK com `ON DELETE SET NULL`: apagar as reuniões primeiro anularia a proveniência
    # de qualquer decisão que sobrevivesse ao `DELETE` abaixo — sem erro, sem log e sem
    # teste que percebesse. Hoje nenhuma sobrevive, porque a substituição é integral; a
    # ordem existe para o dia em que alguém copiar o padrão da pendência.
    #
    # **E a substituição é integral de propósito**, ao contrário de documento e pendência
    # logo acima: `Meeting` não guarda id externo e é recriada por inteiro a cada sync,
    # então o uuid dela muda a cada webhook. O vínculo só se sustenta se for refeito na
    # mesma transação — filtrar este `DELETE` por origem quebraria a proveniência de
    # todas as decisões antigas na passagem seguinte.
    session.execute(delete(Decision).where(Decision.project_id == project.id))

    # Reuniões: o texto da transcrição não atravessa — só o fato de existir.
    session.execute(delete(Meeting).where(Meeting.project_id == project.id))
    reuniao_por_id: dict[str, Meeting] = {}
    for meeting in snapshot.get("meetings", []):
        held = meeting.get("date")
        linha = Meeting(
            organization_id=organization.id,
            project_id=project.id,
            title=meeting["title"],
            held_at=_parse_datetime(f"{held}T00:00:00+00:00") if held else None,
            recording_url=meeting.get("recording_url") or None,
            status=meeting.get("status") or None,
            has_transcript=bool(meeting.get("has_transcript")),
        )
        session.add(linha)
        if meeting.get("id") is not None:
            reuniao_por_id[str(meeting["id"])] = linha

    # O `flush` é o que dá `id` às reuniões recém-inseridas, e sem ele o laço de decisões
    # abaixo gravaria `meeting_id=None` em todas. Mesmo motivo do `flush` das fases mais
    # acima, que existe "porque precisamos do phase.id para os entregáveis".
    if reuniao_por_id:
        session.flush()

    # Decisões (FDD 032 do Biahflow). Só as publicadas chegam aqui — o rascunho, que é
    # onde a extração por IA grava, não entra no snapshot de lá.
    for decision in snapshot.get("decisions", []):
        reuniao = reuniao_por_id.get(str(decision.get("meeting_id")))
        session.add(
            Decision(
                organization_id=organization.id,
                project_id=project.id,
                title=decision["title"],
                rationale=decision.get("rationale") or None,
                decided_on=_parse_date(decision.get("decided_on")),
                owner_label=decision.get("decided_by") or None,
                # `None` quando a reunião não veio no snapshot (arquivada, por exemplo):
                # perder a proveniência é melhor que perder a decisão, que é o mesmo
                # argumento do `SET NULL` do outro lado.
                meeting_id=reuniao.id if reuniao is not None else None,
            )
        )

    # Pendências: só as espelhadas do Biahflow são substituídas. As de origem `portal` (o
    # chat abre uma quando falta evidência, ADR 0007) sobrevivem ao sync.
    session.execute(
        delete(PendingItem).where(
            PendingItem.project_id == project.id,
            PendingItem.origin == PendingOrigin.biahflow,
        )
    )
    for pendencia in snapshot.get("pendencias", []):
        # `created_at` vem do Biahflow: como o sync recria a linha, deixar o default do banco
        # zeraria a idade da pendência ("há 2 dias") a cada webhook.
        opened_at = _parse_datetime(pendencia.get("created_at"))
        item = PendingItem(
            organization_id=organization.id,
            project_id=project.id,
            title=pendencia["title"],
            owner_label=_party_label(pendencia.get("party"), organization.name),
            state=PENDING_STATE_MAP.get(pendencia["status"], PendingState.open),
            priority=PENDING_PRIORITY_MAP.get(
                str(pendencia.get("priority") or ""), PendingPriority.medium
            ),
            origin=PendingOrigin.biahflow,
            external_ref=str(pendencia["id"]),
            resolved_at=_parse_datetime(pendencia.get("resolved_at")),
        )
        if opened_at is not None:
            item.created_at = opened_at
        session.add(item)
    session.flush()

    notifications.emit_changes(session, project, before)
    # Os dois degraus do funil que **nascem no Biahflow** (RFC 001). Sem `user_id`: o fato é
    # de lá, e não há pessoa deste lado a nomear. Importado aqui, e não no topo, para o
    # `onboarding` não entrar no grafo de importação do worker e do seed por este caminho.
    #
    # `stamp_within` e **não** `stamp`: esta função já roda sob `portal_system`, e abrir
    # sessão separada aqui dentro fazia o `INSERT` não enxergar a organização que esta mesma
    # transação acabou de criar — o carimbo do primeiro snapshot de um cliente novo falhava
    # na chave estrangeira, em silêncio. O defeito é da ADR 0039 e foi medido na 0041.
    if delivered_seen or accepted_at is not None:
        from portal_api import onboarding

        if delivered_seen:
            onboarding.stamp_within(
                session, organization.id, OnboardingStepName.first_deliverable_delivered
            )
        if accepted_at is not None:
            # `reached_at` é a data da **decisão**, não a da passagem do sync: é para isso
            # que a coluna existe separada do `created_at` (ADR 0039), e é o que faz a
            # âncora do funil começar no ganho em vez de na primeira vez que o portal olhou.
            onboarding.stamp_within(
                session,
                organization.id,
                OnboardingStepName.artifact_accepted,
                reached_at=accepted_at,
            )
    return project


def mark_project_deleted(session: Session, biahflow_project_id: int) -> list[Project]:
    """Carimba o fato de o Biahflow ter apagado o projeto de vez (ADR 0037).

    Mora aqui, ao lado de `sync_snapshot`, porque é a mesma porta: o Biahflow contando um fato
    sobre o projeto. O que muda é que este fato **não cabe num snapshot** — depois da exclusão a
    rota de leitura de lá responde 404, e um 404 não distingue "foi apagado" de "id de outra
    base" (ADR 0036). Por isso o aviso vem no corpo do webhook e é a única coisa que temos.

    Nada é apagado deste lado, e é decisão: documento é a evidência de uma citação já dada, e
    apagar tenant é decisão de pessoa registrada numa linha, executada pelo worker (ADR 0017).
    O projeto fica visível, marcado e sem escrita.

    A busca é **só pelo slug**, sem organização, porque o webhook de exclusão não carrega o
    cliente — e devolve lista porque mover um projeto de cliente no Biahflow deixa duas linhas
    com este slug (o `sync_snapshot` casa por organização + slug e cria a segunda). Ambas
    afirmam ser o projeto que morreu, então ambas são carimbadas.

    Idempotente: um webhook reentregue não move a data. A primeira observação é a verdadeira, e
    ela é do portal — o Biahflow não manda quando apagou, porque quem apaga não deixa linha.
    """
    projects = list(
        session.execute(
            select(Project).where(Project.slug == project_slug(biahflow_project_id))
        ).scalars()
    )
    for project in projects:
        if project.source_deleted_at is None:
            project.source_deleted_at = datetime.now(timezone.utc)
    session.flush()
    return projects


def ensure_demo_client(session: Session, project: Project, email: str, name: str) -> User:
    """Provision a demo client user + client_member membership for a project (demo only).

    Idempotent. Lets the Biahflow→portal flow be exercised end-to-end without manual seeding.
    """
    normalized = email.lower()
    user = session.execute(select(User).where(User.email == normalized)).scalar_one_or_none()
    if user is None:
        user = User(email=normalized, full_name=name, is_internal=False)
        session.add(user)
        session.flush()
    membership = session.execute(
        select(Membership).where(
            Membership.user_id == user.id, Membership.project_id == project.id
        )
    ).scalar_one_or_none()
    if membership is None:
        session.add(
            Membership(
                organization_id=project.organization_id,
                project_id=project.id,
                user_id=user.id,
                role=MemberRole.client_member,
            )
        )
        session.flush()
    return user


def _document_type(title: str) -> str | None:
    """Rótulo de tipo derivado da extensão do nome — evita uma coluna só para isso."""
    _, _, extension = title.rpartition(".")
    return extension.upper() if extension and extension != title else None


def _results_projection(
    milestones: list[Milestone], *, today: date | None = None
) -> dict[str, Any]:
    """KPIs de andamento derivados dos marcos (o Biahflow envia os mesmos em ``resultados``).

    São recalculados aqui, e não denormalizados em colunas, para não divergirem do read model.

    ``today`` entra por parâmetro, na forma de ``Period.last_days`` — o padrão é o dia
    do produto (São Paulo) e não ``date.today()``: a data da máquina é UTC no contêiner,
    o que adianta em até três horas o corte de "marco atrasado" em relação ao dia que o
    cliente vê na tela.
    """
    total = len(milestones)
    done = sum(1 for milestone in milestones if milestone.state == MilestoneState.done)
    today = today or clock.product_date(datetime.now(timezone.utc))
    overdue = sum(
        1
        for milestone in milestones
        if milestone.state != MilestoneState.done
        and milestone.due_date is not None
        and milestone.due_date < today
    )
    return {
        "milestones_total": total,
        "milestones_done": done,
        "overdue": overdue,
        "on_time_percent": round((total - overdue) / total * 100) if total else 100,
    }


def _journey_projection(session: Session, project: Project) -> dict[str, Any]:
    """Jornada + entregáveis para a UI do cliente ("Você está aqui" e desbloqueio)."""
    phases = list(
        session.execute(
            select(ProjectPhase)
            .where(ProjectPhase.project_id == project.id)
            .order_by(ProjectPhase.position, ProjectPhase.created_at)
        ).scalars()
    )
    deliverables_by_phase: dict[uuid.UUID, list[PhaseDeliverable]] = {}
    for deliverable in session.execute(
        select(PhaseDeliverable)
        .where(PhaseDeliverable.project_id == project.id)
        .order_by(PhaseDeliverable.position, PhaseDeliverable.created_at)
    ).scalars():
        deliverables_by_phase.setdefault(deliverable.phase_id, []).append(deliverable)

    current_phase = next((p.name for p in phases if p.state == PhaseState.active), None)
    return {
        "current_phase": current_phase,
        "phases": [
            {
                "name": phase.name,
                "description": phase.description,
                "state": phase.state.value,
                "target_date": phase.target_date.isoformat() if phase.target_date else None,
                "deliverables": [
                    {
                        "name": deliverable.name,
                        "state": deliverable.state.value,
                        "link": deliverable.link,
                        # A identidade que o uuid desta linha não é (ADR 0077): é
                        # o caminho da rota de aceite, e é o que faz o card de
                        # revisão ter para onde mandar a decisão.
                        "external_ref": deliverable.external_ref,
                    }
                    for deliverable in deliverables_by_phase.get(phase.id, [])
                ],
            }
            for phase in phases
        ],
    }


def _turn_that_opened(session: Session, project: Project) -> dict[uuid.UUID, uuid.UUID]:
    """Pendência da IA → (id do turno, id da conversa) que a abriu (ADR 0031).

    O FK existe e é gravado desde a ADR 0015 (``conversations.append_turn``), e
    até esta fatia era lido **só como booleano** (``pending_created`` em
    ``main.py``): o cliente via "aberta pela IA" e não tinha como voltar à
    pergunta que a gerou.

    Roda sob o mesmo papel do resto do dashboard, e é o que torna a leitura
    correta sem policy nova: a linha é da pessoa que perguntou, então quem
    enxerga o turno é exatamente quem deveria — as policies de
    ``conversation_message`` já dizem isso, e uma pendência aberta pela conversa
    de outra pessoa simplesmente não casa aqui.
    """
    rows = session.execute(
        select(
            ConversationMessage.pending_item_id,
            ConversationMessage.id,
            ConversationMessage.conversation_id,
        ).where(
            ConversationMessage.project_id == project.id,
            ConversationMessage.pending_item_id.is_not(None),
        )
    ).all()
    return {
        pending_id: (message_id, conversation_id)
        for pending_id, message_id, conversation_id in rows
    }


def build_dashboard(session: Session, project: Project) -> dict[str, Any]:
    """Dashboard projection from the portal read model (fed by Biahflow)."""
    milestones = list(
        session.execute(
            select(Milestone)
            .where(Milestone.project_id == project.id)
            .order_by(Milestone.position)
        ).scalars()
    )
    opened_by = _turn_that_opened(session, project)
    comment_counts = pending_comments.counts_for_project(session, project.id)
    documents = session.execute(
        select(Document)
        .where(Document.project_id == project.id)
        .order_by(Document.source_updated_at.desc().nullslast(), Document.title)
    ).scalars()
    meetings = session.execute(
        select(Meeting)
        .where(Meeting.project_id == project.id)
        .order_by(Meeting.held_at.desc().nullslast(), Meeting.title)
    ).scalars()
    pendings = session.execute(
        select(PendingItem)
        .where(PendingItem.project_id == project.id)
        .order_by(PendingItem.created_at.desc())
    ).scalars()
    # A decisão mais recente primeiro, e `decided_on` antes de `created_at`: a data que
    # importa é a do dia em que se decidiu, não a da linha — o sync recria as linhas.
    # `outerjoin` e não um relationship com carga preguiçosa: a aba mostra de qual reunião
    # cada decisão saiu, e uma consulta por linha seria N+1 num laço que já é do dashboard.
    decisions = session.execute(
        select(Decision, Meeting.title)
        .outerjoin(Meeting, Decision.meeting_id == Meeting.id)
        .where(Decision.project_id == project.id)
        .order_by(Decision.decided_on.desc().nullslast(), Decision.title)
    ).all()
    # O programa a que este projeto pertence (ADR 0079). `None` é resposta legítima e
    # frequente: só chega preenchido depois de o Biahflow mandar a chave, e a tela sabe
    # dizer "sem programa" em vez de inventar um rótulo.
    engagement = (
        session.get(Engagement, project.engagement_id) if project.engagement_id else None
    )
    return {
        "project": project.name,
        "status": project.status.value,
        "completion": project.completion_percent,
        "engagement": (
            {
                "id": str(engagement.id),
                "name": engagement.name,
                "status": engagement.status.value,
            }
            if engagement is not None
            else None
        ),
        # Ao lado de `status`, não dentro dele (ADR 0036): o andamento continua sendo o que era
        # quando o projeto foi encerrado, e é a tela que decide o que fazer com os dois juntos.
        "archived_at": project.archived_at.isoformat() if project.archived_at else None,
        # E ao lado de `archived_at` pelo mesmo motivo (ADR 0037): um projeto pode ter sido
        # encerrado antes de ser apagado, e as duas datas contam coisas diferentes.
        "source_deleted_at": (
            project.source_deleted_at.isoformat() if project.source_deleted_at else None
        ),
        # Frescor da projeção (ADR 0076), e as duas datas nunca vêm preenchidas juntas —
        # `sync_snapshot` as mantém mutuamente exclusivas, e é **qual delas veio** que é o
        # rótulo: `observed_at` é "observado há X" (a origem carimbou o instante em que
        # observou aquele estado), `synced_at` é "sincronizado há X" (o fallback declarado,
        # que é só a hora da cópia). Um terceiro campo escrevendo o rótulo seria a mesma
        # regra em dois lugares, e poderia divergir do par — o argumento do `textfold.py`.
        #
        # As duas nulas significam um projeto que nunca passou por um sync: **não há
        # carimbo**, e a tela não inventa um. É a ADR 0026 outra vez, que removeu daqui um
        # "Atualizado há 2 dias" que ninguém tinha como sustentar.
        #
        # A **idade** não sai daqui de propósito, embora o produtor pudesse calculá-la: ela
        # depende de `now()`, e um número calculado no servidor envelhece dentro da própria
        # resposta. Quem deriva "há X" é quem renderiza, no instante em que renderiza —
        # mesma razão pela qual `_results_projection` recebe `today` por parâmetro.
        "observed_at": project.observed_at.isoformat() if project.observed_at else None,
        "synced_at": project.synced_at.isoformat() if project.synced_at else None,
        # A versão da projeção que produziu este estado. Não é para a tela mostrar: é o que
        # torna "o Biahflow parou de avançar" respondível sem abrir o Postgres, e o que dá
        # sentido ao `applied_version` do `projection.stale_rejected`.
        "projection_version": project.projection_version,
        "health": (
            {"label": project.health_label, "level": project.health_level}
            if project.health_level
            else None
        ),
        "journey": _journey_projection(session, project),
        "digital_employees": [
            {
                "name": employee.name,
                "area": employee.area,
                "description": employee.description,
                "status": employee.status.value,
                "kpi_label": employee.kpi_label,
                "kpi_value": employee.kpi_value,
                "hours_saved_month": (
                    float(employee.hours_saved_month)
                    if employee.hours_saved_month is not None
                    else None
                ),
                "roi_month": float(employee.roi_month) if employee.roi_month is not None else None,
            }
            for employee in session.execute(
                select(DigitalEmployee)
                .where(DigitalEmployee.project_id == project.id)
                .order_by(DigitalEmployee.name, DigitalEmployee.created_at)
            ).scalars()
        ],
        "roi": {
            "net": float(project.roi_net) if project.roi_net is not None else None,
            "ratio": project.roi_ratio,
        },
        "next_meeting": (
            {
                "title": project.next_meeting_title,
                "date": project.next_meeting_date.isoformat(),
            }
            if project.next_meeting_date
            else None
        ),
        "milestones": [
            {
                "title": milestone.title,
                "state": milestone.state.value,
                "due_date": milestone.due_date.isoformat() if milestone.due_date else None,
                "owner_label": milestone.owner_label,
            }
            for milestone in milestones
        ],
        "documents": [
            {
                "title": document.title,
                "type": _document_type(document.title),
                "author": document.author_label,
                "link": document.link,
                "updated_at": (
                    document.source_updated_at.isoformat()
                    if document.source_updated_at
                    else None
                ),
            }
            for document in documents
        ],
        "meetings": [
            {
                "title": meeting.title,
                "date": meeting.held_at.date().isoformat() if meeting.held_at else None,
                "recording_url": meeting.recording_url,
                "has_transcript": meeting.has_transcript,
                "status": meeting.status,
            }
            for meeting in meetings
        ],
        "decisions": [
            {
                "title": decision.title,
                "rationale": decision.rationale,
                "decided_on": decision.decided_on.isoformat() if decision.decided_on else None,
                "owner_label": decision.owner_label,
                # O título da reunião e não o id: a aba mostra "saiu de tal reunião", e um
                # uuid que muda a cada sync não serviria nem de rótulo nem de link.
                "meeting_title": meeting_title,
            }
            for decision, meeting_title in decisions
        ],
        "pendings": [
            {
                # O id só passou a sair na ADR 0032, quando a tela precisou
                # endereçar a pendência para abrir o fio. Antes, a chave de
                # render era o título — que ninguém garante ser único.
                "id": str(pending.id),
                "title": pending.title,
                # O turno que abriu esta pendência, quando foi a IA (ADR 0031).
                # `None` para o que veio do Biahflow, e para a pendência da IA
                # cuja conversa pertence a outra pessoa do projeto.
                "opened_by_message_id": (
                    str(opened_by[pending.id][0]) if pending.id in opened_by else None
                ),
                # A thread, e não só o turno: ele quase nunca está na conversa
                # corrente, e o histórico do chat é de uma só (ADR 0015/0031).
                # Zero quando ninguém comentou, e é o que a tela usa para decidir
                # se vale abrir o fio (ADR 0032).
                "comment_count": comment_counts.get(pending.id, 0),
                "opened_by_conversation_id": (
                    str(opened_by[pending.id][1]) if pending.id in opened_by else None
                ),
                "description": pending.description,
                "owner_label": pending.owner_label,
                "state": pending.state.value,
                "priority": pending.priority.value,
                "origin": pending.origin.value,
                "created_at": pending.created_at.isoformat(),
                "resolved_at": pending.resolved_at.isoformat() if pending.resolved_at else None,
            }
            for pending in pendings
        ],
        "results": _results_projection(milestones),
        # Apuração dos eventos dos agentes (Fase 3, ADR 0013). Vai junto do
        # dashboard para os cards de Resultados terem fonte sem uma segunda ida
        # à rede no SSR. É outra coisa que `results`, que projeta os marcos: um
        # é andamento, o outro é o que os agentes produziram.
        "measured": results.to_payload(
            results.compute_results(
                session,
                TenantContext(
                    organization_id=project.organization_id, project_id=project.id
                ),
            )
        ),
    }
