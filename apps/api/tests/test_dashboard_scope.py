"""Fase 2 — client-scoped dashboard access (ADR 0002/0006).

Signature/HTTP-gate tests are pure units; the membership scoping tests need Postgres and
self-skip via the ``integration`` marker + ``db_session``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from portal_api import access
from portal_api.auth import bearer_principal
from portal_api.integrations import biahflow
from portal_api.main import app
from portal_api.models import MemberRole, Membership, Organization, Project, User
from portal_api.principal import Principal
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


# --- integration: qual projeto a resposta serviu (ADR 0061) ----------------
#
# Até esta fatia `MyDashboardOut` não publicava o id, e o BFF descobria o projeto
# atual comparando o **nome** com a lista de `GET /api/v1/me`. As duas rotas ordenam
# por critérios diferentes — `visible_projects` por `Project.created_at`,
# `default_project` pela membership mais recente — de modo que o nome era a única
# coisa que as ligava. Com um projeto por pessoa, que é como todas as fixtures deste
# repositório nasceram, as duas ordens coincidem e a diferença não tem como aparecer;
# é por isso que o defeito atravessou sete fases sem nada ficar vermelho.


@dataclass(frozen=True)
class Homonyms:
    """Dois projetos de mesmo nome no mesmo tenant, com as duas ordens divergindo."""

    organization_id: uuid.UUID
    #: O que `access.default_project` resolve — membership mais recente.
    served_id: uuid.UUID
    #: O primeiro de `GET /api/v1/me` — projeto mais recente. **Não** é o servido.
    listed_first_id: uuid.UUID
    name: str
    subject: str
    email: str


@pytest.fixture
def homonyms(migrated_engine: Engine) -> Iterator[Homonyms]:
    tag = uuid.uuid4().hex[:8]
    subject, email, name = f"sub-homonimo-{tag}", f"homonimo-{tag}@example.com", "Automação Financeira"
    # **O tenant é sorteado, e isso não é preciosismo.** `sync_snapshot` chaveia a
    # organização por `org_slug(client["id"])`, de modo que um `client_id` fixo é uma
    # linha *compartilhada* com todo teste que use o mesmo número — e o teardown abaixo
    # apaga a organização inteira, com cascata. Com `client_id=71` esta fixture apagava
    # dados de `test_chat_ai.py`, que usa aquele mesmo cliente. A bateria passava só
    # porque a ordem de coleta punha o chat antes; é o verde que depende do ambiente que
    # as ADRs 0058 e 0060 tiraram daqui. A faixa alta separa o sorteio dos números
    # baixos escritos à mão pelas outras fixtures.
    client_id = 900_000 + int(tag, 16) % 90_000
    with Session(migrated_engine) as session:
        older = biahflow.sync_snapshot(
            session, _snapshot(biahflow_project_id=client_id + 1, client_id=client_id, name=name)
        )
        newer = biahflow.sync_snapshot(
            session, _snapshot(biahflow_project_id=client_id + 2, client_id=client_id, name=name)
        )
        assert older.organization_id == newer.organization_id
        # `server_default=func.now()` é o relógio da **transação**: sem carimbo explícito
        # as quatro linhas empatam e a divergência que este teste existe para provar não
        # acontece.
        older.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        newer.created_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        user = User(email=email, full_name="Cliente Homônimo", external_subject=subject)
        session.add(user)
        session.flush()
        for project, stamped in ((newer, datetime(2026, 1, 2, tzinfo=timezone.utc)),
                                 (older, datetime(2026, 6, 2, tzinfo=timezone.utc))):
            session.add(
                Membership(
                    organization_id=project.organization_id,
                    project_id=project.id,
                    user_id=user.id,
                    role=MemberRole.client_member,
                    created_at=stamped,
                )
            )
        session.commit()
        built = Homonyms(older.organization_id, older.id, newer.id, name, subject, email)

    app.dependency_overrides[bearer_principal] = lambda: Principal(
        subject=subject,
        email=email,
        full_name="Cliente Homônimo",
        realm_roles=frozenset({"client_member"}),
    )
    try:
        yield built
    finally:
        app.dependency_overrides.clear()
        with Session(migrated_engine) as cleanup:
            cleanup.execute(
                delete(Organization).where(Organization.id == built.organization_id)
            )
            cleanup.execute(delete(User).where(User.email == email))
            cleanup.commit()


@pytest.mark.integration
def test_my_dashboard_publishes_the_project_it_served(homonyms: Homonyms) -> None:
    """O id do projeto servido vem na resposta, e não é o primeiro de `/me`.

    O caso é o que dói: dois projetos homônimos no mesmo tenant, com o campo `project`
    idêntico nos dois. Sem o id publicado, a tela marcava o atual comparando o nome —
    e com nomes iguais o casamento pegava o primeiro da lista, que aqui é justamente o
    projeto que a API **não** serviu. Daí em diante o `?project=` da ADR 0059 levava a
    escolha errada às nove rotas, e a pendência do projeto certo respondia 404.
    """
    dashboard = client.get("/api/v1/me/dashboard")
    listing = client.get("/api/v1/me")

    assert dashboard.status_code == 200
    assert listing.status_code == 200
    body = dashboard.json()
    assert body["project_id"] == str(homonyms.served_id)
    assert body["project"] == homonyms.name

    listed = listing.json()["projects"]
    # O nome não distingue: é exatamente por isso que o id precisou ser publicado.
    assert [project["name"] for project in listed] == [homonyms.name, homonyms.name]
    # E a ordem das duas rotas diverge de verdade — sem isto o teste passaria por sorte.
    assert listed[0]["id"] == str(homonyms.listed_first_id)
    assert listed[0]["id"] != body["project_id"]


@pytest.mark.integration
def test_the_published_id_is_the_one_default_project_resolves(
    homonyms: Homonyms, migrated_engine: Engine
) -> None:
    """O id publicado é o de `access.default_project`, e não outro critério paralelo."""
    body = client.get("/api/v1/me/dashboard").json()

    with Session(migrated_engine) as session:
        user = UserRepository(session).get_by_email(homonyms.email)
        assert user is not None
        resolved = access.default_project(session, user)

    assert resolved is not None
    assert body["project_id"] == str(resolved.id)


@pytest.mark.integration
def test_the_project_route_does_not_publish_the_id(homonyms: Homonyms) -> None:
    """`/projects/{id}/dashboard` **não** ganha o campo (ADR 0061/0029).

    Quem chama por lá escolheu o id e o tem no caminho; devolvê-lo é sedimento.
    """
    response = client.get(f"/api/v1/projects/{homonyms.listed_first_id}/dashboard")

    assert response.status_code == 200
    assert "project_id" not in response.json()
