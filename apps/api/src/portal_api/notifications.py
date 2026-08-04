"""Emissão de notificações — o único lugar que cria uma ``Notification`` (ADR 0012).

O produtor é o sync do Biahflow, e por uma razão de arquitetura: o portal não
origina status (ADR 0006/0008), então ele não tem como saber que "o marco X foi
concluído" a não ser comparando o read model antes e depois do snapshot. Daí o
formato deste módulo: :func:`snapshot_state` fotografa os fatos **antes** dos
``delete()`` de ``sync_snapshot``, :func:`diff` compara com o depois, e
:func:`fan_out` grava uma linha por destinatário.

Duas armadilhas que o desenho evita de propósito:

* **o primeiro sync não notifica.** Sem o guarda de ``before is None`` um projeto
  recém-chegado dispararia um aviso por marco, documento e reunião que já
  nasceram concluídos — a caixa de entrada do cliente no primeiro login;
* **o sync recria as linhas espelhadas**, então nada aqui pode comparar por
  ``id``. As chaves são as mesmas que compõem o ``dedupe_key`` (título do marco,
  ``external_id`` do documento, ``external_ref`` da pendência), que é o que
  também torna o reenvio do mesmo webhook inofensivo.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from portal_api.models import (
    DeliverableState,
    Document,
    Meeting,
    MemberRole,
    Membership,
    Milestone,
    MilestoneState,
    Notification,
    NotificationKind,
    PendingItem,
    PendingState,
    PhaseDeliverable,
    PhaseState,
    Project,
    ProjectPhase,
)

# Quem recebe o quê. O cliente recebe tudo — é dele o projeto e é essa a razão de
# o portal existir. O time interno recebe só o que exige ação dele, porque o
# resto ele *acabou de digitar* no Biahflow: avisar alguém da própria escrita é
# ruído, e ruído é como uma central de notificações morre.
_EVERYONE = frozenset(MemberRole)
_CLIENT_ONLY = frozenset({MemberRole.client_member})
_INTERNAL_ONLY = frozenset({MemberRole.internal_admin, MemberRole.internal_member})

AUDIENCE: dict[NotificationKind, frozenset[MemberRole]] = {
    NotificationKind.milestone_done: _CLIENT_ONLY,
    NotificationKind.phase_advanced: _CLIENT_ONLY,
    NotificationKind.deliverable_delivered: _CLIENT_ONLY,
    NotificationKind.document_added: _CLIENT_ONLY,
    NotificationKind.meeting_scheduled: _CLIENT_ONLY,
    NotificationKind.transcript_ready: _CLIENT_ONLY,
    NotificationKind.pending_resolved: _CLIENT_ONLY,
    NotificationKind.project_status_changed: _CLIENT_ONLY,
    # A pendência é o único fato que pede ação dos dois lados.
    NotificationKind.pending_opened: _EVERYONE,
}

_MAX_DEDUPE_KEY = 255


@dataclass(frozen=True)
class Change:
    """Um fato que mudou, já no vocabulário do cliente."""

    kind: NotificationKind
    title: str
    dedupe_key: str
    detail: str | None = None
    link: str | None = None


@dataclass(frozen=True)
class ProjectState:
    """Os fatos do projeto que valem um aviso, indexados por chave estável."""

    status: str | None = None
    health_label: str | None = None
    milestones: dict[str, MilestoneState] = field(default_factory=dict)
    phases: dict[str, PhaseState] = field(default_factory=dict)
    deliverables: dict[tuple[str, str], DeliverableState] = field(default_factory=dict)
    documents: dict[str, str] = field(default_factory=dict)
    meetings: dict[str, bool] = field(default_factory=dict)
    pendings: dict[str, tuple[str, PendingState]] = field(default_factory=dict)


def _key(*parts: str) -> str:
    """Chave de dedupe estável, e curta o bastante para a coluna.

    Título de marco vai a 200 caracteres e a coluna tem 255, então concatenar às
    cegas estouraria. O hash preserva a identidade do fato sem depender do
    tamanho — e continua determinístico, que é tudo o que a unique constraint
    precisa.
    """
    joined = ":".join(parts)
    if len(joined) <= _MAX_DEDUPE_KEY:
        return joined
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return f"{parts[0]}:{digest}"


def snapshot_state(session: Session, project: Project | None) -> ProjectState | None:
    """Fotografa o estado atual do projeto. ``None`` para um projeto que ainda não existe.

    O ``None`` é o que faz o primeiro sync não notificar nada.
    """
    if project is None or project.id is None:
        return None

    phases = {
        phase.id: phase
        for phase in session.execute(
            select(ProjectPhase).where(ProjectPhase.project_id == project.id)
        ).scalars()
    }
    deliverables = {
        (phases[deliverable.phase_id].name, deliverable.name): deliverable.state
        for deliverable in session.execute(
            select(PhaseDeliverable).where(PhaseDeliverable.project_id == project.id)
        ).scalars()
        if deliverable.phase_id in phases
    }

    return ProjectState(
        status=project.status.value if project.status else None,
        health_label=project.health_label,
        milestones={
            milestone.title: milestone.state
            for milestone in session.execute(
                select(Milestone).where(Milestone.project_id == project.id)
            ).scalars()
        },
        phases={phase.name: phase.state for phase in phases.values()},
        deliverables=deliverables,
        documents={
            document.external_id: document.title
            for document in session.execute(
                select(Document).where(Document.project_id == project.id)
            ).scalars()
            if document.external_id
        },
        meetings={
            meeting.title: meeting.has_transcript
            for meeting in session.execute(
                select(Meeting).where(Meeting.project_id == project.id)
            ).scalars()
        },
        pendings={
            item.external_ref: (item.title, item.state)
            for item in session.execute(
                select(PendingItem).where(PendingItem.project_id == project.id)
            ).scalars()
            if item.external_ref
        },
    )


def diff(before: ProjectState | None, after: ProjectState | None) -> list[Change]:
    """O que mudou entre dois estados, na ordem em que o cliente lê."""
    if before is None or after is None:
        return []

    changes: list[Change] = []

    if after.status != before.status and after.status is not None:
        changes.append(
            Change(
                kind=NotificationKind.project_status_changed,
                title="O status do projeto mudou",
                detail=f"Agora: {after.status}",
                # Com a data: um projeto que volta ao status anterior semanas
                # depois é um fato novo, e o cliente deve saber.
                dedupe_key=_key("project", "status", after.status, _today()),
            )
        )
    if after.health_label != before.health_label and after.health_label is not None:
        changes.append(
            Change(
                kind=NotificationKind.project_status_changed,
                title=f"Acompanhamento do projeto: {after.health_label}",
                dedupe_key=_key("project", "health", after.health_label, _today()),
            )
        )

    for name, state in after.phases.items():
        if state is PhaseState.active and before.phases.get(name) is not PhaseState.active:
            changes.append(
                Change(
                    kind=NotificationKind.phase_advanced,
                    title=f"Nova fase da jornada: {name}",
                    detail="Você está aqui.",
                    dedupe_key=_key("phase", name, "active"),
                )
            )

    for title, state in after.milestones.items():
        if state is MilestoneState.done and before.milestones.get(title) is not MilestoneState.done:
            changes.append(
                Change(
                    kind=NotificationKind.milestone_done,
                    title="Marco concluído",
                    detail=title,
                    dedupe_key=_key("milestone", title, "done"),
                )
            )

    for (phase_name, name), state in after.deliverables.items():
        was = before.deliverables.get((phase_name, name))
        if state is DeliverableState.delivered and was is not DeliverableState.delivered:
            changes.append(
                Change(
                    kind=NotificationKind.deliverable_delivered,
                    title="Entregável liberado",
                    detail=f"{name} ({phase_name})",
                    dedupe_key=_key("deliverable", phase_name, name, "delivered"),
                )
            )

    for external_id, title in after.documents.items():
        if external_id not in before.documents:
            changes.append(
                Change(
                    kind=NotificationKind.document_added,
                    title="Novo documento no projeto",
                    detail=title,
                    dedupe_key=_key("document", external_id),
                )
            )

    for title, has_transcript in after.meetings.items():
        if title not in before.meetings:
            changes.append(
                Change(
                    kind=NotificationKind.meeting_scheduled,
                    title="Reunião agendada",
                    detail=title,
                    dedupe_key=_key("meeting", title),
                )
            )
        if has_transcript and not before.meetings.get(title, False):
            changes.append(
                Change(
                    kind=NotificationKind.transcript_ready,
                    title="Transcrição disponível",
                    detail=title,
                    dedupe_key=_key("transcript", title),
                )
            )

    for external_ref, (title, state) in after.pendings.items():
        was = before.pendings.get(external_ref)
        if was is None and state is PendingState.open:
            changes.append(
                Change(
                    kind=NotificationKind.pending_opened,
                    title="Nova pendência",
                    detail=title,
                    dedupe_key=_key("pending", external_ref, "opened"),
                )
            )
        elif (
            was is not None
            and state is PendingState.resolved
            and was[1] is not PendingState.resolved
        ):
            changes.append(
                Change(
                    kind=NotificationKind.pending_resolved,
                    title="Pendência resolvida",
                    detail=title,
                    dedupe_key=_key("pending", external_ref, "resolved"),
                )
            )

    return changes


def recipients(
    session: Session, project: Project, kind: NotificationKind
) -> list[uuid.UUID]:
    """Quem recebe este tipo de aviso neste projeto.

    Considera a membership direta e a de organização inteira (``project_id IS
    NULL``), a mesma regra de ``MembershipRepository.roles_for_project`` — quem
    tem acesso ao projeto por qualquer um dos dois caminhos é destinatário.
    """
    allowed = AUDIENCE.get(kind, _CLIENT_ONLY)
    rows = session.execute(
        select(Membership.user_id, Membership.role).where(
            Membership.organization_id == project.organization_id,
            (Membership.project_id == project.id) | (Membership.project_id.is_(None)),
        )
    ).all()
    # dict e não set: a ordem estável deixa o teste (e o digest) determinísticos.
    return list({user_id: None for user_id, role in rows if role in allowed})


def fan_out(
    session: Session,
    project: Project,
    changes: list[Change],
    *,
    occurred_at: datetime | None = None,
) -> list[uuid.UUID]:
    """Grava uma linha por destinatário e devolve os ids criados.

    ``ON CONFLICT DO NOTHING`` sobre ``uq_notification_user_dedupe_key``: o
    webhook do Biahflow é uma reconciliação completa, não um delta, então o mesmo
    payload chega mais de uma vez por desenho. O que não foi inserido não volta
    no ``RETURNING``, e é justamente isso que impede o e-mail de sair de novo.

    Roda sob ``portal_system`` (o caminho do sync) — ``portal_app`` não tem
    ``INSERT`` nesta tabela.
    """
    if not changes:
        return []

    when = occurred_at or datetime.now(timezone.utc)
    rows = [
        {
            "id": uuid.uuid4(),
            "organization_id": project.organization_id,
            "project_id": project.id,
            "user_id": user_id,
            "kind": change.kind,
            "title": change.title,
            "detail": change.detail,
            "link": change.link,
            "occurred_at": when,
            "dedupe_key": change.dedupe_key,
        }
        for change in changes
        for user_id in recipients(session, project, change.kind)
    ]
    if not rows:
        return []

    stmt = (
        insert(Notification)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_notification_user_dedupe_key")
        .returning(Notification.id)
    )
    return list(session.execute(stmt).scalars())


def emit_changes(
    session: Session, project: Project, before: ProjectState | None
) -> list[uuid.UUID]:
    """Compara o estado atual com ``before`` e emite o que mudou. Idempotente."""
    return fan_out(session, project, diff(before, snapshot_state(session, project)))


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()
