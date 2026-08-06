"""Tests for the Biahflow integration (ADR 0006).

Signature/HTTP tests are pure units. The read-model upsert and isolation tests need a real
Postgres and self-skip (via the ``integration`` marker + ``db_session``) when it is absent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api import main
from portal_api.integrations import biahflow
from portal_api.main import app
from portal_api.models import (
    Document,
    DocumentChunk,
    DocumentIngestState,
    DocumentOrigin,
    DocumentSource,
    Milestone,
    MilestoneState,
    Organization,
    PendingItem,
    PendingOrigin,
    Project,
    ProjectStatus,
)
from portal_api.repositories import MilestoneRepository, TenantContext

client = TestClient(app)


@contextmanager
def _session_scope(session: Session) -> Iterator[Session]:
    """Empresta a sessão transacional do teste ao endpoint, sem commitar de verdade."""
    yield session
    session.flush()


def _snapshot(*, biahflow_project_id: int = 7, client_id: int = 3) -> dict[str, Any]:
    return {
        "project": {
            "id": biahflow_project_id,
            "name": "Automação Financeira",
            "description": "",
            "status": "active",
            "start_date": "2026-08-01",
            "due_date": "2026-09-30",
            "is_overdue": False,
            "client": {"id": client_id, "name": "Acme Brasil"},
        },
        "completion": 50,
        "milestones": [
            {"id": 1, "title": "Validação", "status": "done", "party": "provider",
             "due_date": "2026-09-09", "completed_at": None, "is_overdue": False},
            {"id": 2, "title": "Treinamento", "status": "todo", "party": "client",
             "due_date": "2026-09-18", "completed_at": None, "is_overdue": False},
        ],
        "journey": {
            "current_phase": "Prove",
            "phases": [
                {"name": "Welcome", "description": "", "position": 0, "status": "done",
                 "target_date": None, "deliverables": [
                     {"name": "Acesso ao portal", "status": "delivered", "link": None}]},
                {"name": "Prove", "description": "", "position": 1, "status": "active",
                 "target_date": "2026-09-20", "deliverables": [
                     {"name": "Funcionário Digital", "status": "pending", "link": None}]},
                {"name": "Scale", "description": "", "position": 2, "status": "locked",
                 "target_date": None, "deliverables": []},
            ],
        },
        "roi": {"revenue": 1000.0, "cost": 250.0, "net": 750.0, "roi": 3.0},
        "next_meeting": {"id": 5, "title": "Revisão de fase", "date": "2026-08-20"},
        "health": {"label": "No prazo", "level": "green"},
        "digital_employees": [
            {"id": 1, "name": "Agente Financeiro", "area": "Financeiro",
             "description": "Concilia contas.", "status": "active",
             "kpi_label": "Conciliação", "kpi_value": "80%",
             "hours_saved_month": 120.0, "roi_month": 14000.0},
        ],
        "documents": [
            {"id": 41, "name": "Plano de implantação.pdf", "type": "PDF",
             "author": "Ana Souza", "link": "https://drive.example/doc-41",
             "created_at": "2026-08-01T12:00:00+00:00"},
            {"id": 42, "name": "Mapa de integrações", "type": "",
             "author": "Rafael", "link": "", "created_at": "2026-07-28T09:30:00+00:00"},
        ],
        "meetings": [
            {"id": 5, "title": "Revisão de fase", "date": "2026-08-20",
             "recording_url": "", "has_transcript": False, "status": "scheduled"},
            {"id": 4, "title": "Kickoff do projeto", "date": "2026-08-07",
             "recording_url": "https://rec.example/4", "has_transcript": True,
             "status": "held"},
        ],
        # A primeira traz `priority`; a segunda **não**, de propósito: o campo é
        # opcional no snapshot e o teste abaixo cobra os dois caminhos.
        "pendencias": [
            {"id": 71, "title": "Aprovar fluxo de exceções", "status": "open",
             "party": "client", "priority": "high",
             "created_at": "2026-08-02T10:00:00+00:00",
             "resolved_at": None},
            {"id": 72, "title": "Definir alçada de aprovação", "status": "resolved",
             "party": "provider", "created_at": "2026-07-25T10:00:00+00:00",
             "resolved_at": "2026-08-01T15:00:00+00:00"},
        ],
        "resultados": {"conclusao_pct": 50, "marcos_total": 2, "marcos_done": 1,
                       "atrasados": 0, "no_prazo_pct": 100, "status": "active"},
    }


# --- unit: signature -------------------------------------------------------

def test_verify_signature_accepts_matching_hmac() -> None:
    body = b'{"project_id": 7}'
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert biahflow.verify_signature("secret", body, f"sha256={digest}") is True
    assert biahflow.verify_signature("secret", body, digest) is True  # sem prefixo também


def test_verify_signature_rejects_bad_or_missing() -> None:
    body = b"{}"
    assert biahflow.verify_signature("secret", body, "sha256=deadbeef") is False
    assert biahflow.verify_signature("secret", body, None) is False
    assert biahflow.verify_signature("", body, "sha256=whatever") is False


def test_fetch_snapshot_calls_biahflow_snapshot_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/portal/projects/7/snapshot/"
        assert request.headers["Authorization"] == "Bearer tkn"
        return httpx.Response(200, json=_snapshot())

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    data = biahflow.fetch_snapshot("http://biahflow/api/v1", "tkn", 7, client=http_client)
    assert data["project"]["id"] == 7


def test_webhook_rejects_bad_signature() -> None:
    response = client.post(
        "/api/v1/integrations/biahflow/webhook",
        content=b'{"project_id": 7}',
        headers={"X-Biahflow-Signature": "sha256=wrong"},
    )
    assert response.status_code == 401


# --- integration: read-model upsert ---------------------------------------


@pytest.mark.integration
def test_sync_snapshot_creates_read_model(db_session: Session) -> None:
    project = biahflow.sync_snapshot(db_session, _snapshot(biahflow_project_id=11, client_id=9))

    assert project.slug == "biahflow-11"
    assert project.status is ProjectStatus.in_implementation  # "active" → in_implementation
    assert project.completion_percent == 50
    org = db_session.get(Organization, project.organization_id)
    assert org is not None and org.slug == "biahflow-client-9"
    states = {m.title: m.state for m in db_session.execute(
        select(Milestone).where(Milestone.project_id == project.id)
    ).scalars()}
    assert states == {"Validação": MilestoneState.done, "Treinamento": MilestoneState.planned}


@pytest.mark.integration
def test_sync_snapshot_is_idempotent_and_replaces_milestones(db_session: Session) -> None:
    snap = _snapshot(biahflow_project_id=12, client_id=10)
    first = biahflow.sync_snapshot(db_session, snap)

    snap["completion"] = 100
    snap["project"]["status"] = "completed"
    snap["milestones"] = [snap["milestones"][0]]  # remove one
    second = biahflow.sync_snapshot(db_session, snap)

    assert first.id == second.id  # mesmo projeto, não duplica
    assert second.status is ProjectStatus.live
    assert second.completion_percent == 100
    remaining = db_session.execute(
        select(Milestone).where(Milestone.project_id == second.id)
    ).scalars().all()
    assert len(remaining) == 1  # milestones substituídos pelo snapshot


@pytest.mark.integration
def test_synced_project_is_isolated_from_other_tenants(db_session: Session) -> None:
    """Negative permission: another tenant's repo can't see the synced milestones."""
    project = biahflow.sync_snapshot(db_session, _snapshot(biahflow_project_id=13, client_id=11))
    milestone = db_session.execute(
        select(Milestone).where(Milestone.project_id == project.id)
    ).scalars().first()
    assert milestone is not None

    other = MilestoneRepository(
        db_session, TenantContext(organization_id=uuid.uuid4(), project_id=uuid.uuid4())
    )
    assert other.get(milestone.id) is None
    assert other.list() == []


@pytest.mark.integration
def test_build_dashboard_projects_read_model(db_session: Session) -> None:
    project = biahflow.sync_snapshot(db_session, _snapshot(biahflow_project_id=14, client_id=12))
    dashboard = biahflow.build_dashboard(db_session, project)

    assert dashboard["status"] == "in_implementation"
    assert dashboard["completion"] == 50
    assert [m["title"] for m in dashboard["milestones"]] == ["Validação", "Treinamento"]


@pytest.mark.integration
def test_sync_snapshot_projects_journey_roi_and_next_meeting(db_session: Session) -> None:
    project = biahflow.sync_snapshot(db_session, _snapshot(biahflow_project_id=15, client_id=13))
    dashboard = biahflow.build_dashboard(db_session, project)

    journey = dashboard["journey"]
    assert journey["current_phase"] == "Prove"  # "Você está aqui"
    assert [p["name"] for p in journey["phases"]] == ["Welcome", "Prove", "Scale"]
    assert journey["phases"][0]["state"] == "done"
    assert journey["phases"][0]["deliverables"][0] == {
        "name": "Acesso ao portal", "state": "delivered", "link": None,
    }
    assert journey["phases"][1]["state"] == "active"
    assert dashboard["roi"] == {"net": 750.0, "ratio": 3.0}
    assert dashboard["next_meeting"] == {"title": "Revisão de fase", "date": "2026-08-20"}
    assert dashboard["health"] == {"label": "No prazo", "level": "green"}
    employees = dashboard["digital_employees"]
    assert employees[0]["name"] == "Agente Financeiro"
    assert employees[0]["status"] == "active"
    assert employees[0]["roi_month"] == 14000.0


@pytest.mark.integration
def test_sync_snapshot_replaces_phases_and_deliverables(db_session: Session) -> None:
    snap = _snapshot(biahflow_project_id=16, client_id=14)
    biahflow.sync_snapshot(db_session, snap)
    # Avança a jornada: Welcome→done já era; Prove conclui e Scale ativa, sem duplicar.
    snap["journey"]["current_phase"] = "Scale"
    snap["journey"]["phases"][1]["status"] = "done"
    snap["journey"]["phases"][2]["status"] = "active"
    project = biahflow.sync_snapshot(db_session, snap)
    dashboard = biahflow.build_dashboard(db_session, project)

    assert dashboard["journey"]["current_phase"] == "Scale"
    assert len(dashboard["journey"]["phases"]) == 3  # substituídas, não duplicadas


# --- integration: documentos, reuniões, pendências e resultados -------------


@pytest.mark.integration
def test_sync_snapshot_mirrors_documents_meetings_and_pendings(db_session: Session) -> None:
    project = biahflow.sync_snapshot(db_session, _snapshot(biahflow_project_id=17, client_id=15))
    dashboard = biahflow.build_dashboard(db_session, project)

    documents = {d["title"]: d for d in dashboard["documents"]}
    assert documents["Plano de implantação.pdf"]["type"] == "PDF"
    assert documents["Plano de implantação.pdf"]["author"] == "Ana Souza"
    assert documents["Plano de implantação.pdf"]["link"] == "https://drive.example/doc-41"
    # Sem extensão no nome e sem link: nada é inventado.
    assert documents["Mapa de integrações"]["type"] is None
    assert documents["Mapa de integrações"]["link"] is None

    meetings = {m["title"]: m for m in dashboard["meetings"]}
    assert meetings["Kickoff do projeto"]["has_transcript"] is True
    assert meetings["Kickoff do projeto"]["status"] == "held"
    assert meetings["Kickoff do projeto"]["date"] == "2026-08-07"
    assert meetings["Revisão de fase"]["has_transcript"] is False

    pendings = {p["title"]: p for p in dashboard["pendings"]}
    assert pendings["Aprovar fluxo de exceções"]["state"] == "open"
    assert pendings["Definir alçada de aprovação"]["state"] == "resolved"
    assert pendings["Definir alçada de aprovação"]["resolved_at"] is not None
    # `created_at` vem do Biahflow, não do momento do sync.
    assert pendings["Aprovar fluxo de exceções"]["created_at"].startswith("2026-08-02")
    # A prioridade também (ADR 0029). Até esta fatia o sync **não a lia**: a
    # coluna tinha enum desde a Fase 1, o `PendingOut` a declarava e o payload a
    # entregava, e nada nunca escrevia outro valor além do default — uma coluna
    # com contrato e sem produtor é uma constante disfarçada de dado.
    assert pendings["Aprovar fluxo de exceções"]["priority"] == "high"
    # E a pendência sem o campo cai no default, porque ele é opcional no
    # snapshot: o portal não pode exigir que a outra ponta já o envie.
    assert pendings["Definir alçada de aprovação"]["priority"] == "medium"


@pytest.mark.integration
def test_party_becomes_owner_label(db_session: Session) -> None:
    """``provider`` é a Portal Labs; ``client`` é a organização do próprio cliente."""
    project = biahflow.sync_snapshot(db_session, _snapshot(biahflow_project_id=18, client_id=16))
    dashboard = biahflow.build_dashboard(db_session, project)

    owners = {m["title"]: m["owner_label"] for m in dashboard["milestones"]}
    assert owners == {"Validação": "Portal Labs", "Treinamento": "Acme Brasil"}
    pendings = {p["title"]: p["owner_label"] for p in dashboard["pendings"]}
    assert pendings["Aprovar fluxo de exceções"] == "Acme Brasil"
    assert pendings["Definir alçada de aprovação"] == "Portal Labs"


@pytest.mark.integration
def test_sync_replaces_biahflow_pendings_but_keeps_portal_ones(db_session: Session) -> None:
    """Critério de aceite: a pendência aberta pela IA (ADR 0007) sobrevive ao re-sync."""
    snap = _snapshot(biahflow_project_id=19, client_id=17)
    project = biahflow.sync_snapshot(db_session, snap)
    db_session.add(
        PendingItem(
            organization_id=project.organization_id,
            project_id=project.id,
            title="Falta evidência sobre o cálculo de economia",
            origin=PendingOrigin.portal,
        )
    )
    db_session.flush()

    snap["pendencias"] = [snap["pendencias"][0]]  # o time resolveu/removeu uma no Biahflow
    biahflow.sync_snapshot(db_session, snap)
    dashboard = biahflow.build_dashboard(db_session, project)

    titles = [p["title"] for p in dashboard["pendings"]]
    assert "Falta evidência sobre o cálculo de economia" in titles  # não foi apagada
    assert "Definir alçada de aprovação" not in titles  # espelhada: substituída
    assert titles.count("Aprovar fluxo de exceções") == 1  # não duplicou


@pytest.mark.integration
def test_sync_replaces_biahflow_documents_but_keeps_the_uploaded_ones(
    db_session: Session,
) -> None:
    """O arquivo enviado no portal — e o índice dele — sobrevive ao webhook.

    Mesma razão da pendência acima: o sync substitui o que espelha, e só isso.
    Sem a distinção de origem, indexar um documento seria trabalho com prazo de
    validade até o próximo snapshot.
    """
    snap = _snapshot(biahflow_project_id=25, client_id=23)
    project = biahflow.sync_snapshot(db_session, snap)
    uploaded = Document(
        organization_id=project.organization_id,
        project_id=project.id,
        title="Contrato assinado.pdf",
        source=DocumentSource.upload,
        origin=DocumentOrigin.portal,
        ingest_state=DocumentIngestState.indexed,
    )
    db_session.add(uploaded)
    db_session.flush()
    db_session.add(
        DocumentChunk(
            organization_id=project.organization_id,
            project_id=project.id,
            document_id=uploaded.id,
            ordinal=0,
            text="O suporte contratado dura 12 meses.",
            location="página 1",
            char_count=35,
            content_hash="hash-do-trecho",
        )
    )
    db_session.flush()

    biahflow.sync_snapshot(db_session, snap)

    survivors = list(
        db_session.execute(
            select(Document).where(Document.project_id == project.id)
        ).scalars()
    )
    titles = [document.title for document in survivors]
    assert "Contrato assinado.pdf" in titles
    assert titles.count("Contrato assinado.pdf") == 1
    # E o índice não foi levado junto por CASCADE.
    assert (
        db_session.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == uploaded.id)
        ).first()
        is not None
    )


@pytest.mark.integration
def test_results_projection_counts_milestones_and_overdue(db_session: Session) -> None:
    snap = _snapshot(biahflow_project_id=20, client_id=18)
    snap["milestones"].append(
        {"id": 3, "title": "Entrada em produção", "status": "todo", "party": "provider",
         "due_date": "2020-01-01", "completed_at": None, "is_overdue": True},
    )
    project = biahflow.sync_snapshot(db_session, snap)

    results = biahflow.build_dashboard(db_session, project)["results"]
    assert results == {
        "milestones_total": 3,
        "milestones_done": 1,
        "overdue": 1,  # vencido e não concluído
        "on_time_percent": 67,
    }


@pytest.mark.integration
@pytest.mark.parametrize("object_type", ["meeting", "pendencia"])
def test_webhook_syncs_new_object_types(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, object_type: str
) -> None:
    """Os novos ``object_type`` do Biahflow (ADR 0005 de lá) não exigem tratamento próprio.

    O webhook só lê ``project_id`` e refaz o snapshot inteiro, então qualquer tipo de objeto
    converge para o mesmo caminho de sync — inclusive os que ainda nem existem.
    """
    biahflow_project_id = 25 if object_type == "meeting" else 26
    snap = _snapshot(biahflow_project_id=biahflow_project_id, client_id=19)
    monkeypatch.setattr(main.settings, "biahflow_webhook_secret", "s3cr3t")
    monkeypatch.setattr(main.biahflow, "fetch_snapshot", lambda *args, **kwargs: snap)
    # O webhook pede o papel `system` (ADR 0010); o fixture já roda nele, então o
    # stub só precisa aceitar e ignorar o argumento.
    monkeypatch.setattr(main, "get_session", lambda *args, **kwargs: _session_scope(db_session))

    body = json.dumps(
        {"event": "updated", "object_type": object_type, "project_id": biahflow_project_id}
    ).encode()
    signature = hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/v1/integrations/biahflow/webhook",
        content=body,
        headers={"X-Biahflow-Signature": f"sha256={signature}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "synced"
    project = db_session.execute(
        select(Project).where(Project.slug == biahflow.project_slug(biahflow_project_id))
    ).scalars().one()
    dashboard = biahflow.build_dashboard(db_session, project)
    assert len(dashboard["meetings"]) == 2
    assert len(dashboard["pendings"]) == 2


@pytest.mark.integration
def test_the_dashboard_says_which_turn_opened_an_ai_pending(db_session: Session) -> None:
    """O FK existia desde a ADR 0015 e era lido só como booleano (ADR 0031).

    A pendência espelhada do Biahflow não tem turno; a aberta pela IA tem — e é
    o que dá ao cliente o caminho de volta à pergunta que ele mesmo fez.
    """
    from portal_api.models import (
        Conversation,
        ConversationMessage,
        ConversationRole,
        PendingItem,
        PendingOrigin,
        User,
    )

    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=91, client_id=90)
    )
    asker = User(
        email=f"quem-perguntou-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Quem Perguntou",
        external_subject=str(uuid.uuid4()),
    )
    db_session.add(asker)
    db_session.flush()
    pending = PendingItem(
        organization_id=project.organization_id,
        project_id=project.id,
        title="Responder dúvida do cliente: quanto falta?",
        origin=PendingOrigin.portal,
    )
    db_session.add(pending)
    conversation = Conversation(
        organization_id=project.organization_id,
        project_id=project.id,
        user_id=asker.id,
        title="quanto falta?",
        last_message_at=datetime.now(timezone.utc),
    )
    db_session.add(conversation)
    db_session.flush()
    turn = ConversationMessage(
        organization_id=project.organization_id,
        project_id=project.id,
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        ordinal=2,
        role=ConversationRole.assistant,
        text="Não há evidência suficiente.",
        pending_item_id=pending.id,
    )
    db_session.add(turn)
    db_session.flush()

    pendings = {
        item["title"]: item
        for item in biahflow.build_dashboard(db_session, project)["pendings"]
    }

    assert pendings["Responder dúvida do cliente: quanto falta?"][
        "opened_by_message_id"
    ] == str(turn.id)
    # A do Biahflow não veio de conversa nenhuma, e dizer o contrário seria
    # inventar procedência.
    assert pendings["Aprovar fluxo de exceções"]["opened_by_message_id"] is None
