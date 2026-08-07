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
import uuid
from datetime import date, datetime, timezone
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from portal_api import notifications, pending_comments, results
from portal_api.models import (
    ConversationMessage,
    DeliverableState,
    DigitalEmployee,
    DigitalEmployeeStatus,
    Document,
    DocumentOrigin,
    DocumentSource,
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
# Portal Labs; "client" é a própria organização do cliente, resolvida no sync.
PROVIDER_LABEL = "Portal Labs"

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


def org_slug(biahflow_client_id: int) -> str:
    return f"biahflow-client-{biahflow_client_id}"


def project_slug(biahflow_project_id: int) -> str:
    return f"biahflow-{biahflow_project_id}"


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


def sync_snapshot(session: Session, snapshot: dict[str, Any]) -> Project:
    """Upsert a Biahflow snapshot into the portal read model. Idempotent.

    Também é o produtor das notificações (ADR 0012): o portal não origina status,
    então a única forma de saber que algo *mudou* é comparar o read model antes e
    depois do upsert. O estado é fotografado antes de qualquer escrita e o diff
    sai no fim — ver :mod:`portal_api.notifications`.
    """
    project_data = snapshot["project"]
    client_data = project_data["client"]

    organization = session.execute(
        select(Organization).where(Organization.slug == org_slug(client_data["id"]))
    ).scalar_one_or_none()
    if organization is None:
        organization = Organization(name=client_data["name"], slug=org_slug(client_data["id"]))
        session.add(organization)
        session.flush()
    else:
        organization.name = client_data["name"]

    slug = project_slug(project_data["id"])
    project = session.execute(
        select(Project).where(
            Project.organization_id == organization.id, Project.slug == slug
        )
    ).scalar_one_or_none()
    # Antes de qualquer escrita: é este retrato que vira notificação lá embaixo.
    # `None` para um projeto que ainda não existe, e é o que faz o primeiro sync
    # chegar em silêncio em vez de com uma caixa de entrada cheia.
    before = notifications.snapshot_state(session, project)

    if project is None:
        project = Project(organization_id=organization.id, slug=slug)
        session.add(project)
    project.name = project_data["name"]
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

    # Reuniões: o texto da transcrição não atravessa — só o fato de existir.
    session.execute(delete(Meeting).where(Meeting.project_id == project.id))
    for meeting in snapshot.get("meetings", []):
        held = meeting.get("date")
        session.add(
            Meeting(
                organization_id=organization.id,
                project_id=project.id,
                title=meeting["title"],
                held_at=_parse_datetime(f"{held}T00:00:00+00:00") if held else None,
                recording_url=meeting.get("recording_url") or None,
                status=meeting.get("status") or None,
                has_transcript=bool(meeting.get("has_transcript")),
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


def _results_projection(milestones: list[Milestone]) -> dict[str, Any]:
    """KPIs de andamento derivados dos marcos (o Biahflow envia os mesmos em ``resultados``).

    São recalculados aqui, e não denormalizados em colunas, para não divergirem do read model.
    """
    total = len(milestones)
    done = sum(1 for milestone in milestones if milestone.state == MilestoneState.done)
    today = date.today()
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
    return {
        "project": project.name,
        "status": project.status.value,
        "completion": project.completion_percent,
        # Ao lado de `status`, não dentro dele (ADR 0036): o andamento continua sendo o que era
        # quando o projeto foi encerrado, e é a tela que decide o que fazer com os dois juntos.
        "archived_at": project.archived_at.isoformat() if project.archived_at else None,
        # E ao lado de `archived_at` pelo mesmo motivo (ADR 0037): um projeto pode ter sido
        # encerrado antes de ser apagado, e as duas datas contam coisas diferentes.
        "source_deleted_at": (
            project.source_deleted_at.isoformat() if project.source_deleted_at else None
        ),
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
