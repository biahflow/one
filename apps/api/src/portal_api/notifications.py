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
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from portal_api import tabs
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
    User,
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
    # Comentário também, e por definição: ele é escrito **para** o outro lado.
    NotificationKind.pending_commented: _EVERYONE,
    # O primeiro aviso que é **só** do time, e o que finalmente usa o `_INTERNAL_ONLY`
    # definido na ADR 0012 e órfão desde então (ADR 0040). O cliente não deve saber que
    # está sendo medido em funil, e não há nada que ele possa fazer com a informação —
    # esquecer esta linha faria o `.get(kind, _CLIENT_ONLY)` de `recipients` contar a ele
    # que ele está travado, que é o defeito mais caro que esta fatia podia introduzir.
    NotificationKind.onboarding_stuck: _INTERNAL_ONLY,
    # O segundo aviso só do time (ADR 0043), e por um motivo diferente do primeiro:
    # lá o cliente não deve saber que está sendo medido; aqui ele **escreveu** a
    # mensagem, e devolvê-la seria contar-lhe o que acabou de digitar.
    NotificationKind.whatsapp_reply: _INTERNAL_ONLY,
}

_MAX_DEDUPE_KEY = 255

#: Que aba do portal cada aviso abre (FDD 021, ADR 0043).
#:
#: **Existe porque o campo tinha consumidor e não tinha escritor.** ``link`` está no
#: modelo desde a Fase 2 e o sino o renderiza como ``<a>`` quando ele vem preenchido
#: — e as dez ramificações do :func:`diff` nunca o preencheram, de modo que todo
#: aviso de cliente chegava sem link desde então. Era o defeito da ADR 0033 na
#: direção que ninguém tinha olhado: lá um painel sobre campo sem escritor, aqui um
#: **controle** sobre campo sem escritor. Quem o encontrou foi o critério de aceite
#: (4) da FDD 021, que exige que o aviso do canal caia "na coisa exata, nunca na
#: home" — e não havia o que carregar.
#:
#: **Mora aqui e não no `diff`** por dois motivos. O `diff` compara dois estados e
#: não conhece o projeto, que é metade da URL; e um mapa por espécie responde "que
#: tela este aviso abre?" numa tabela legível, em vez de espalhar a resposta por dez
#: construções onde ela divergiria uma a uma. Quem passa ``link`` explícito — o
#: alerta do funil, que aponta para ``/admin/funil`` — continua vencendo.
LINK_TAB: dict[NotificationKind, str] = {
    NotificationKind.project_status_changed: tabs.TAB_OVERVIEW,
    # A jornada com o "Você está aqui" e os entregáveis desbloqueados moram na
    # visão geral, não no cronograma — o cronograma é dos marcos.
    NotificationKind.phase_advanced: tabs.TAB_OVERVIEW,
    NotificationKind.deliverable_delivered: tabs.TAB_OVERVIEW,
    NotificationKind.milestone_done: tabs.TAB_SCHEDULE,
    NotificationKind.document_added: tabs.TAB_DOCUMENTS,
    NotificationKind.meeting_scheduled: tabs.TAB_MEETINGS,
    NotificationKind.transcript_ready: tabs.TAB_MEETINGS,
    NotificationKind.pending_opened: tabs.TAB_PENDINGS,
    NotificationKind.pending_resolved: tabs.TAB_PENDINGS,
    NotificationKind.pending_commented: tabs.TAB_PENDINGS,
    # A resposta do cliente abre as pendências, que é onde o time responde **dentro
    # do portal** — que é a razão de ela virar aviso aqui em vez de thread lá fora.
    NotificationKind.whatsapp_reply: tabs.TAB_PENDINGS,
    # `onboarding_stuck` **não** entra: é interno, não abre aba de cliente nenhuma,
    # e já traz `link` próprio. Uma linha aqui o mandaria para a tela do cliente.
}


def deep_link(project_id: uuid.UUID, kind: NotificationKind) -> str | None:
    """A URL relativa que abre o assunto deste aviso. ``None`` quando não há aba.

    O projeto entra porque o portal é uma tela só com troca de projeto por
    ``?project=``, e a aba porque a tela navega **por rótulo** desde a Fase 2 — a
    decisão que a busca já tinha tomado (ADR 0024), reusada em vez de duplicada.

    ``None`` é uma resposta legítima e o remetente do canal a respeita: sem aba, não
    há "coisa exata" a abrir, e a FDD 021 proíbe cair na home. O aviso continua no
    sino, que é onde ele sempre esteve.
    """
    tab = LINK_TAB.get(kind)
    if tab is None:
        return None
    return f"/?project={project_id}&tab={quote(tab)}"


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


def reply_target(session: Session, user: User) -> Project | None:
    """O projeto em que a resposta desta pessoa deve aparecer (ADR 0043).

    A resposta chega pelo canal com **um telefone e nada mais** — sem projeto, sem
    tenant, sem contexto. O destino é o projeto vivo mais recente em que a pessoa
    tem vínculo: é onde o assunto provavelmente está, e é o único que ela e o time
    com certeza compartilham.

    ``None`` quando não há nenhum, e a rota respeita: sem projeto vivo não há sino
    onde pôr o aviso, nem tenant a que a linha pertença. Inventar um seria criar
    projeto a partir de uma mensagem de fora.

    Empate desfeito pelo ``id`` pela razão escrita em ``onboarding._anchor_project``:
    ``created_at`` é ``server_default now()``, e no Postgres ``now()`` é o instante de
    início da transação — dois projetos criados pelo mesmo sync têm o mesmo carimbo,
    e ordenar só por data não é ordem total.
    """
    return session.execute(
        select(Project)
        .join(
            Membership,
            (Membership.organization_id == Project.organization_id)
            & ((Membership.project_id == Project.id) | (Membership.project_id.is_(None))),
        )
        .where(
            Membership.user_id == user.id,
            Project.archived_at.is_(None),
            Project.source_deleted_at.is_(None),
        )
        .order_by(Project.created_at.desc(), Project.id.desc())
        .limit(1)
    ).scalars().first()


def fan_out(
    session: Session,
    project: Project,
    changes: list[Change],
    *,
    occurred_at: datetime | None = None,
    exclude_user_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Grava uma linha por destinatário e devolve os ids criados.

    ``ON CONFLICT DO NOTHING`` sobre ``uq_notification_user_dedupe_key``: o
    webhook do Biahflow é uma reconciliação completa, não um delta, então o mesmo
    payload chega mais de uma vez por desenho. O que não foi inserido não volta
    no ``RETURNING``, e é justamente isso que impede o e-mail de sair de novo.

    Roda sob ``portal_system`` (o caminho do sync) — ``portal_app`` não tem
    ``INSERT`` nesta tabela.

    ``exclude_user_id`` existe para o comentário (ADR 0032): avisar alguém do que
    ele mesmo acabou de escrever é o tipo de ruído que ensina a ignorar o sino.
    Fica aqui, e não em ``recipients``, porque a audiência é do **tipo** de aviso
    e a exclusão é deste **evento** — juntá-las faria o `AUDIENCE` deixar de ser
    uma tabela legível.
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
            # O explícito vence: o alerta do funil aponta para `/admin/funil`, que
            # não é aba de cliente e não sairia de `deep_link`.
            "link": change.link or deep_link(project.id, change.kind),
            "occurred_at": when,
            "dedupe_key": change.dedupe_key,
        }
        for change in changes
        for user_id in recipients(session, project, change.kind)
        if user_id != exclude_user_id
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
