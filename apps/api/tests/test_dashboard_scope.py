"""Fase 2 — client-scoped dashboard access (ADR 0002/0006).

Signature/HTTP-gate tests are pure units; the membership scoping tests need Postgres and
self-skip via the ``integration`` marker + ``db_session``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from portal_api import access
from portal_api.integrations import biahflow
from portal_api.main import app
from portal_api.models import Membership, Project, User
from portal_api.repositories import UserRepository

client = TestClient(app)


def _snapshot(*, biahflow_project_id: int, client_id: int, name: str = "Automação Financeira") -> dict[str, Any]:
    return {
        "project": {
            "id": biahflow_project_id, "name": name, "description": "", "status": "active",
            "start_date": "2026-08-01", "due_date": "2026-09-30", "is_overdue": False,
            "client": {"id": client_id, "name": "Acme Brasil"},
        },
        "completion": 50,
        "milestones": [
            {"id": 1, "title": "Validação", "status": "in_progress", "due_date": "2026-09-09",
             "completed_at": None, "is_overdue": False},
        ],
        "documents": [
            {"id": 1, "name": f"Contrato {name}.pdf", "type": "PDF", "author": "Jurídico",
             "link": f"https://drive.example/{biahflow_project_id}",
             "created_at": "2026-08-01T12:00:00+00:00"},
        ],
        "meetings": [
            {"id": 1, "title": f"Comitê {name}", "date": "2026-08-07", "recording_url": "",
             "has_transcript": True, "status": "held"},
        ],
        "pendencias": [
            {"id": 1, "title": f"Pendência de {name}", "status": "open", "party": "client",
             "created_at": "2026-08-02T10:00:00+00:00", "resolved_at": None},
        ],
    }


def _synced(session: Session, *, biahflow_project_id: int, client_id: int, email: str) -> Project:
    project = biahflow.sync_snapshot(
        session, _snapshot(biahflow_project_id=biahflow_project_id, client_id=client_id)
    )
    biahflow.ensure_demo_client(session, project, email, "Cliente Demo")
    return project


# --- unit: identity gate ---------------------------------------------------

def test_dashboard_endpoints_require_a_token() -> None:
    """Sem `Authorization: Bearer` não há principal, e o gate responde 401 (ADR 0010)."""
    assert client.get(f"/api/v1/projects/{uuid.uuid4()}/dashboard").status_code == 401
    assert client.get("/api/v1/me/dashboard").status_code == 401
    assert client.get("/api/v1/me").status_code == 401


def test_a_malformed_token_is_rejected_too() -> None:
    headers = {"Authorization": "Bearer not-a-jwt"}

    assert client.get("/api/v1/me/dashboard", headers=headers).status_code == 401


# --- integration: membership scoping --------------------------------------

@pytest.mark.integration
def test_member_can_resolve_own_project(db_session: Session) -> None:
    project = _synced(db_session, biahflow_project_id=21, client_id=31, email="ana@acme.test")
    ana = UserRepository(db_session).get_by_email("ana@acme.test")

    assert access.scoped_project(db_session, ana, project.id).id == project.id  # type: ignore[union-attr]
    assert access.default_project(db_session, ana).id == project.id  # type: ignore[union-attr]


@pytest.mark.integration
def test_non_member_and_unknown_user_are_denied(db_session: Session) -> None:
    """Negative permission: another client's project and unknown users resolve to None (→404)."""
    mine = _synced(db_session, biahflow_project_id=22, client_id=32, email="ana@acme.test")
    theirs = biahflow.sync_snapshot(db_session, _snapshot(biahflow_project_id=23, client_id=99))
    ana = UserRepository(db_session).get_by_email("ana@acme.test")

    # membro de 'mine' não alcança o projeto de outro tenant
    assert access.scoped_project(db_session, ana, theirs.id) is None
    # usuário sem vínculo nenhum não alcança nada
    stranger = UserRepository(db_session).add(
        User(email="ghost@acme.test", full_name="Ghost", external_subject="sub-ghost")
    )
    assert access.scoped_project(db_session, stranger, mine.id) is None
    assert access.default_project(db_session, stranger) is None


@pytest.mark.integration
def test_dashboard_never_projects_another_tenants_knowledge(db_session: Session) -> None:
    """Negative permission: documentos, reuniões e pendências não vazam entre projetos."""
    mine = _synced(db_session, biahflow_project_id=25, client_id=35, email="ana@acme.test")
    theirs = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=26, client_id=99, name="Outro Projeto")
    )

    dashboard = biahflow.build_dashboard(db_session, mine)
    rendered = repr(dashboard)

    assert "Outro Projeto" not in rendered
    assert [d["title"] for d in dashboard["documents"]] == ["Contrato Automação Financeira.pdf"]
    assert [m["title"] for m in dashboard["meetings"]] == ["Comitê Automação Financeira"]
    assert [p["title"] for p in dashboard["pendings"]] == ["Pendência de Automação Financeira"]
    # E o inverso: o dashboard do outro tenant também não traz nada do primeiro.
    assert "Automação Financeira" not in repr(biahflow.build_dashboard(db_session, theirs))


@pytest.mark.integration
def test_ensure_demo_client_is_idempotent(db_session: Session) -> None:
    project = biahflow.sync_snapshot(db_session, _snapshot(biahflow_project_id=24, client_id=33))
    first = biahflow.ensure_demo_client(db_session, project, "dup@acme.test", "Dup")
    second = biahflow.ensure_demo_client(db_session, project, "dup@acme.test", "Dup")

    assert first.id == second.id
    count = db_session.execute(
        select(func.count()).select_from(Membership).where(
            Membership.user_id == first.id, Membership.project_id == project.id
        )
    ).scalar_one()
    assert count == 1
