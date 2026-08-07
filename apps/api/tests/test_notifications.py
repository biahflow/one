"""Emissão de notificações a partir do sync (Fase 2, ADR 0012).

O que estes testes protegem, em ordem de importância:

1. **o mesmo webhook reenviado não duplica.** O snapshot do Biahflow é uma
   reconciliação completa, não um delta, então ele chega repetido por desenho;
2. **o primeiro sync não notifica.** Um projeto que acabou de chegar tem marcos
   concluídos e documentos que o cliente nunca "viu acontecer";
3. **a audiência é dado, não convenção** — o cliente recebe o andamento, o time
   interno só o que exige ação dele.

Todos precisam de Postgres de verdade (enum, JSONB, ``ON CONFLICT``) e se
auto-pulam quando não há, como o resto da camada de dados.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api import notifications
from portal_api.integrations import biahflow
from portal_api.models import (
    MemberRole,
    Membership,
    Notification,
    NotificationKind,
    User,
)

pytestmark = pytest.mark.integration


def _snapshot(*, biahflow_project_id: int, client_id: int) -> dict[str, Any]:
    """Snapshot mínimo, com um de cada fato que vira aviso."""
    return {
        "project": {
            "id": biahflow_project_id,
            "name": "Automação Financeira",
            "status": "active",
            "client": {"id": client_id, "name": "Acme Brasil"},
        },
        "completion": 40,
        "milestones": [
            {"id": 1, "title": "Validação", "status": "todo", "party": "provider",
             "due_date": None, "completed_at": None},
        ],
        "journey": {
            "current_phase": "Welcome",
            "phases": [
                {"name": "Welcome", "description": "", "position": 0, "status": "active",
                 "target_date": None, "deliverables": [
                     {"name": "Acesso ao portal", "status": "pending", "link": None}]},
                {"name": "Prove", "description": "", "position": 1, "status": "locked",
                 "target_date": None, "deliverables": []},
            ],
        },
        "health": {"label": "No prazo", "level": "green"},
        "documents": [
            {"id": 41, "name": "Plano de implantação.pdf", "type": "PDF", "author": "Ana",
             "link": "https://drive.example/doc-41", "created_at": "2026-08-01T12:00:00+00:00"},
        ],
        "meetings": [
            {"id": 5, "title": "Kickoff", "date": "2026-08-07", "recording_url": "",
             "has_transcript": False, "status": "held"},
        ],
        "pendencias": [
            {"id": 71, "title": "Aprovar fluxo", "status": "open", "party": "client",
             "created_at": "2026-08-02T10:00:00+00:00", "resolved_at": None},
        ],
    }


def _with_members(session: Session, project, tag: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Um cliente e um interno no projeto. Devolve (client_id, internal_id)."""
    created: list[uuid.UUID] = []
    for name, role in (("cliente", MemberRole.client_member), ("interno", MemberRole.internal_admin)):
        user = User(
            email=f"{name}-{tag}@example.com",
            full_name=name.title(),
            external_subject=f"sub-{name}-{tag}",
            is_internal=role is not MemberRole.client_member,
        )
        session.add(user)
        session.flush()
        session.add(
            Membership(
                organization_id=project.organization_id,
                project_id=project.id,
                user_id=user.id,
                role=role,
            )
        )
        created.append(user.id)
    session.flush()
    return created[0], created[1]


def _notifications(session: Session, project_id: uuid.UUID) -> list[Notification]:
    return list(
        session.execute(
            select(Notification).where(Notification.project_id == project_id)
        ).scalars()
    )


def test_first_sync_notifies_nobody(db_session: Session) -> None:
    """Um projeto novo chega inteiro; nada nele "aconteceu" para o cliente."""
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=101, client_id=51)
    )
    assert _notifications(db_session, project.id) == []


def test_milestone_reaching_done_notifies_the_client(db_session: Session) -> None:
    snapshot = _snapshot(biahflow_project_id=102, client_id=52)
    project = biahflow.sync_snapshot(db_session, snapshot)
    client_id, internal_id = _with_members(db_session, project, "m102")

    snapshot["milestones"][0]["status"] = "done"
    biahflow.sync_snapshot(db_session, snapshot)

    emitted = _notifications(db_session, project.id)
    assert [item.kind for item in emitted] == [NotificationKind.milestone_done]
    assert emitted[0].detail == "Validação"
    # Andamento é assunto do cliente: o time interno acabou de digitar isso no
    # Biahflow e não precisa do próprio eco.
    assert emitted[0].user_id == client_id
    assert internal_id not in {item.user_id for item in emitted}


def test_the_same_webhook_replayed_does_not_duplicate(db_session: Session) -> None:
    """A garantia central: o snapshot é reconciliação completa, não delta."""
    snapshot = _snapshot(biahflow_project_id=103, client_id=53)
    project = biahflow.sync_snapshot(db_session, snapshot)
    _with_members(db_session, project, "m103")

    snapshot["milestones"][0]["status"] = "done"
    biahflow.sync_snapshot(db_session, snapshot)
    first = _notifications(db_session, project.id)

    biahflow.sync_snapshot(db_session, snapshot)
    biahflow.sync_snapshot(db_session, snapshot)

    assert len(first) == 1
    assert [item.id for item in _notifications(db_session, project.id)] == [first[0].id]


def test_a_new_pending_reaches_the_client_and_the_internal_team(db_session: Session) -> None:
    snapshot = _snapshot(biahflow_project_id=104, client_id=54)
    project = biahflow.sync_snapshot(db_session, snapshot)
    client_id, internal_id = _with_members(db_session, project, "m104")

    snapshot["pendencias"].append(
        {"id": 72, "title": "Definir alçada", "status": "open", "party": "provider",
         "created_at": "2026-08-03T10:00:00+00:00", "resolved_at": None}
    )
    biahflow.sync_snapshot(db_session, snapshot)

    emitted = _notifications(db_session, project.id)
    assert {item.kind for item in emitted} == {NotificationKind.pending_opened}
    assert {item.user_id for item in emitted} == {client_id, internal_id}


def test_documents_meetings_transcripts_and_phases_each_notify(db_session: Session) -> None:
    snapshot = _snapshot(biahflow_project_id=105, client_id=55)
    project = biahflow.sync_snapshot(db_session, snapshot)
    _with_members(db_session, project, "m105")

    snapshot["documents"].append(
        {"id": 42, "name": "Mapa de integrações", "type": "", "author": "Rafael",
         "link": "", "created_at": "2026-08-03T09:30:00+00:00"}
    )
    snapshot["meetings"][0]["has_transcript"] = True
    snapshot["meetings"].append(
        {"id": 6, "title": "Comitê", "date": "2026-08-20", "recording_url": "",
         "has_transcript": False, "status": "scheduled"}
    )
    snapshot["journey"]["phases"][1]["status"] = "active"
    snapshot["journey"]["phases"][0]["deliverables"][0]["status"] = "delivered"
    biahflow.sync_snapshot(db_session, snapshot)

    kinds = {item.kind for item in _notifications(db_session, project.id)}
    assert kinds == {
        NotificationKind.document_added,
        NotificationKind.transcript_ready,
        NotificationKind.meeting_scheduled,
        NotificationKind.phase_advanced,
        NotificationKind.deliverable_delivered,
    }


def test_a_resolved_pending_notifies_and_a_status_change_too(db_session: Session) -> None:
    snapshot = _snapshot(biahflow_project_id=106, client_id=56)
    project = biahflow.sync_snapshot(db_session, snapshot)
    _with_members(db_session, project, "m106")

    snapshot["pendencias"][0]["status"] = "resolved"
    snapshot["pendencias"][0]["resolved_at"] = "2026-08-04T10:00:00+00:00"
    snapshot["project"]["status"] = "completed"
    biahflow.sync_snapshot(db_session, snapshot)

    kinds = {item.kind for item in _notifications(db_session, project.id)}
    assert kinds == {
        NotificationKind.pending_resolved,
        NotificationKind.project_status_changed,
    }


def test_a_member_of_another_project_receives_nothing(db_session: Session) -> None:
    """Fan-out segue a membership: quem não está no projeto não é destinatário."""
    snapshot = _snapshot(biahflow_project_id=107, client_id=57)
    project = biahflow.sync_snapshot(db_session, snapshot)
    _with_members(db_session, project, "m107")

    other = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=108, client_id=58)
    )
    outsider, _ = _with_members(db_session, other, "m108")

    snapshot["milestones"][0]["status"] = "done"
    biahflow.sync_snapshot(db_session, snapshot)

    assert outsider not in {item.user_id for item in _notifications(db_session, project.id)}


def test_every_notification_kind_declares_its_audience() -> None:
    """O `.get(kind, _CLIENT_ONLY)` de `recipients` faz o esquecimento **enviar ao cliente**.

    Três linhas contra o defeito mais caro que a ADR 0040 podia introduzir: o aviso de
    cliente travado é o primeiro cuja audiência é só o time, e sem a entrada no `AUDIENCE`
    ele contaria ao próprio cliente que ele está sendo medido — que é o que a FDD 020 proíbe
    na seção de jornada.

    A guarda é sobre **completude** e não sobre o valor de cada linha: quem escrever a
    próxima espécie escolhe a audiência, e o que não pode é escolher por omissão.
    """
    faltando = [
        kind.value for kind in NotificationKind if kind not in notifications.AUDIENCE
    ]

    assert faltando == []


def test_dedupe_key_survives_a_title_longer_than_the_column() -> None:
    """Marco vai a 200 caracteres e a coluna a 255: a chave não pode estourar."""
    key = notifications._key("milestone", "x" * 300, "done")
    assert len(key) <= 255
    assert key.startswith("milestone:")
    assert key == notifications._key("milestone", "x" * 300, "done")  # determinística


@pytest.mark.integration
def test_a_comment_notifies_the_other_side_and_not_its_author(db_session: Session) -> None:
    """Avisar alguém do que ele mesmo escreveu é o ruído que ensina a ignorar o sino.

    `fan_out` derivava destinatários só de `AUDIENCE`, que é do **tipo** do aviso;
    `exclude_user_id` é deste **evento** (ADR 0032), e é por isso que ele fica no
    `fan_out` e não em `recipients` — juntá-los faria o `AUDIENCE` deixar de ser
    uma tabela legível.
    """
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=131, client_id=81)
    )
    client_id, internal_id = _with_members(db_session, project, "m131")

    created = notifications.fan_out(
        db_session,
        project,
        [
            notifications.Change(
                kind=notifications.NotificationKind.pending_commented,
                title="Cliente comentou numa pendência",
                detail="Enviar a planilha",
                dedupe_key=f"comment:{uuid.uuid4()}",
            )
        ],
        exclude_user_id=client_id,
    )

    recipients = set(
        db_session.execute(
            select(Notification.user_id).where(Notification.id.in_(created))
        ).scalars()
    )
    assert recipients == {internal_id}
