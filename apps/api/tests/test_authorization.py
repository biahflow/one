"""Negative permission cases through the real HTTP stack (AGENTS.md #6, ADR 0010).

Only ``bearer_principal`` is overridden — token validation has its own file. From
there down everything is real: the endpoints open a session under ``portal_app``,
resolve the user, and read through the RLS policies. So a "404" here means the
denial survived the whole chain, not that a mock said no.

The rows are committed by a ``portal_system`` session because the app answers on
a different connection and would not see an open transaction's writes.
"""

from __future__ import annotations

import ast
import pathlib
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from portal_api import openapi
from portal_api.auth import bearer_principal
from portal_api.main import app
from portal_api.models import (
    AuditLog,
    MemberRole,
    Membership,
    Notification,
    NotificationKind,
    Organization,
    PendingItem,
    Project,
    ProjectStatus,
    User,
)
from conftest import captured
from portal_api.principal import Principal

pytestmark = pytest.mark.integration

client = TestClient(app)


@dataclass(frozen=True)
class Actor:
    subject: str
    email: str
    full_name: str
    realm_roles: tuple[str, ...] = ("client_member",)


@dataclass(frozen=True)
class Tenant:
    organization_id: uuid.UUID
    organization_name: str
    project_id: uuid.UUID
    project_name: str
    client: Actor


@dataclass(frozen=True)
class World:
    acme: Tenant
    globex: Tenant
    staff: Actor
    seeded: Actor  # exists in the database with no external_subject yet


@pytest.fixture(scope="session")
def world(migrated_engine: Engine) -> Iterator[World]:
    tag = uuid.uuid4().hex[:8]
    tenants: dict[str, Tenant] = {}

    with Session(migrated_engine) as session:
        for name in ("acme", "globex"):
            organization = Organization(name=name.title(), slug=f"{name}-{tag}")
            session.add(organization)
            session.flush()

            project = Project(
                organization_id=organization.id,
                name=f"Automação {name.title()}",
                slug=f"{name}-project-{tag}",
                status=ProjectStatus.in_implementation,
            )
            session.add(project)
            session.flush()

            user = User(
                email=f"cliente-{name}-{tag}@example.com",
                full_name=f"Cliente {name.title()}",
                external_subject=f"sub-cliente-{name}-{tag}",
            )
            session.add(user)
            session.flush()
            session.add(
                Membership(
                    organization_id=organization.id,
                    project_id=project.id,
                    user_id=user.id,
                    role=MemberRole.client_member,
                )
            )

            tenants[name] = Tenant(
                organization_id=organization.id,
                organization_name=organization.name,
                project_id=project.id,
                project_name=project.name,
                client=Actor(user.external_subject or "", user.email, user.full_name),
            )

        # Staff: organization-wide membership, no project — the case that used to
        # resolve to nothing at all.
        staff = User(
            email=f"ops-{tag}@portallabs.test",
            full_name="Ops Portal Labs",
            external_subject=f"sub-ops-{tag}",
            is_internal=True,
        )
        session.add(staff)
        session.flush()
        session.add(
            Membership(
                organization_id=tenants["acme"].organization_id,
                project_id=None,
                user_id=staff.id,
                role=MemberRole.internal_admin,
            )
        )

        # Seeded like the versioned seed does: known e-mail, no subject yet.
        seeded = User(
            email=f"semeado-{tag}@example.com",
            full_name="Cliente Semeado",
            external_subject=None,
        )
        session.add(seeded)
        session.flush()
        session.add(
            Membership(
                organization_id=tenants["acme"].organization_id,
                project_id=tenants["acme"].project_id,
                user_id=seeded.id,
                role=MemberRole.client_member,
            )
        )
        session.commit()

        built = World(
            acme=tenants["acme"],
            globex=tenants["globex"],
            staff=Actor(
                staff.external_subject or "",
                staff.email,
                staff.full_name,
                ("internal_admin",),
            ),
            seeded=Actor(f"sub-semeado-{tag}", seeded.email, seeded.full_name),
        )

    yield built

    with Session(migrated_engine) as session:
        session.execute(
            delete(Organization).where(
                Organization.id.in_(
                    [built.acme.organization_id, built.globex.organization_id]
                )
            )
        )
        session.execute(delete(User).where(User.email.like(f"%-{tag}@%")))
        session.commit()


@pytest.fixture
def authenticated() -> Iterator[Callable[[Actor], None]]:
    """Swap in a verified principal, exactly as a good token would produce."""

    def _as(actor: Actor) -> None:
        app.dependency_overrides[bearer_principal] = lambda: Principal(
            subject=actor.subject,
            email=actor.email,
            full_name=actor.full_name,
            realm_roles=frozenset(actor.realm_roles),
        )

    yield _as
    app.dependency_overrides.clear()


# --- cross-tenant ---------------------------------------------------------


def test_a_client_cannot_reach_another_tenants_project(world: World, authenticated) -> None:
    """404 and not 403: the answer must not reveal that the project exists."""
    authenticated(world.acme.client)

    mine = client.get(f"/api/v1/projects/{world.acme.project_id}/dashboard")
    theirs = client.get(f"/api/v1/projects/{world.globex.project_id}/dashboard")

    assert mine.status_code == 200
    assert mine.json()["project"] == world.acme.project_name
    assert theirs.status_code == 404


def test_me_lists_only_the_callers_own_projects(world: World, authenticated) -> None:
    authenticated(world.acme.client)

    body = client.get("/api/v1/me").json()

    assert [p["id"] for p in body["projects"]] == [str(world.acme.project_id)]
    assert body["organization"] == world.acme.organization_name
    assert body["roles"] == ["client_member"]
    assert world.globex.project_name not in repr(body)


def test_me_dashboard_resolves_the_clients_own_project(world: World, authenticated) -> None:
    authenticated(world.acme.client)

    body = client.get("/api/v1/me/dashboard").json()

    assert body["project"] == world.acme.project_name
    assert body["organization"] == world.acme.organization_name


# --- identity without authorization ---------------------------------------


def test_an_authenticated_user_without_membership_authorizes_nothing(
    world: World, authenticated, db_session: Session
) -> None:
    """Authentication is not authorization — and the difference is visible.

    The user row is provisioned on first login, so the portal can greet them, and
    every project query still resolves to nothing.
    """
    stranger = Actor(
        subject=f"sub-stranger-{uuid.uuid4().hex[:8]}",
        email=f"stranger-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Estranho",
    )
    authenticated(stranger)

    me = client.get("/api/v1/me")
    dashboard = client.get("/api/v1/me/dashboard")
    project = client.get(f"/api/v1/projects/{world.acme.project_id}/dashboard")

    assert me.status_code == 200
    assert me.json()["projects"] == []
    assert dashboard.status_code == 404
    assert project.status_code == 404

    provisioned = db_session.execute(
        select(User).where(User.external_subject == stranger.subject)
    ).scalar_one()
    assert provisioned.email == stranger.email
    db_session.execute(delete(User).where(User.id == provisioned.id))
    db_session.commit()


def test_a_seeded_row_is_claimed_on_first_login(
    world: World, authenticated, db_session: Session
) -> None:
    """The realm and the versioned seed meet here: the e-mail links, the sub sticks."""
    authenticated(world.seeded)

    body = client.get("/api/v1/me/dashboard").json()

    assert body["project"] == world.acme.project_name
    linked = db_session.execute(
        select(User).where(User.email == world.seeded.email)
    ).scalar_one()
    assert linked.external_subject == world.seeded.subject


# --- roles ----------------------------------------------------------------


def _event_body(project_id: uuid.UUID) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "project_id": str(project_id),
        "occurred_at": "2026-08-03T10:00:00Z",
        "agent_key": "finance-agent",
        "time_saved_seconds": 120,
        "avoided_cost_cents": 5000,
        "run_reference": "run-001",
    }


def test_agent_events_reject_a_human_session(world: World, authenticated) -> None:
    """A rota é só por chave desde a Fase 3 (ADR 0013).

    Até a Fase 2 um `internal_admin` publicava evento com o próprio Bearer. Um
    agente não tem sessão de usuário, então o Bearer deixou de valer aqui — e um
    cliente autenticado, que nunca pôde, continua não podendo.
    """
    authenticated(world.acme.client)

    response = client.post("/api/v1/agent-events", json=_event_body(world.acme.project_id))

    assert response.status_code == 401


def test_a_project_key_publishes_into_its_own_project(world: World, agent_key) -> None:
    key = agent_key(world.acme)

    response = client.post(
        "/api/v1/agent-events",
        json=_event_body(world.acme.project_id),
        headers={"X-Agent-Key": key},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"


def test_a_key_cannot_publish_into_another_organizations_project(
    world: World, agent_key
) -> None:
    """A propriedade que os testes de Bearer protegiam, agora provada por chave.

    O corpo pede um projeto; a credencial diz outro. Quem manda é a credencial,
    e a recusa é 404 — nunca 403 — para não revelar que o projeto existe.
    """
    key = agent_key(world.acme)

    response = client.post(
        "/api/v1/agent-events",
        json=_event_body(world.globex.project_id),
        headers={"X-Agent-Key": key},
    )

    assert response.status_code == 404


def test_internal_staff_reach_the_organizations_project(world: World, authenticated) -> None:
    """The org-wide membership carries no project id, and used to 404 for staff."""
    authenticated(world.staff)

    dashboard = client.get("/api/v1/me/dashboard")

    assert dashboard.status_code == 200
    assert dashboard.json()["project"] == world.acme.project_name


# --- the app role's only writes -------------------------------------------


def test_a_gap_in_the_chat_writes_a_pendencia_and_an_audit_entry(
    world: World, authenticated, db_session: Session
) -> None:
    """The two inserts ``portal_app`` is allowed to make, exercised end to end.

    ``audit_log`` grants INSERT and no SELECT, so this also pins the mapper down:
    an ``INSERT ... RETURNING`` there would need a read the policy denies.
    """
    authenticated(world.acme.client)

    response = client.post(
        "/api/v1/chat",
        json={"question": "Qual é a política de retenção de dados do contrato?"},
    )

    assert response.status_code == 200
    assert response.json()["pending_created"] is True

    pendings = db_session.execute(
        select(PendingItem).where(PendingItem.project_id == world.acme.project_id)
    ).scalars().all()
    assert len(pendings) == 1

    entry = db_session.execute(
        select(AuditLog).where(AuditLog.organization_id == world.acme.organization_id)
    ).scalars().one()
    assert entry.action == "chat.pending_created"
    assert entry.entity_id == pendings[0].id
    # Não anônima: o autor da pergunta fica registrado.
    assert entry.actor_user_id is not None


# --- notificações e preferências (Fase 2, ADR 0012) ------------------------


def test_notifications_require_a_project(world: World, authenticated) -> None:
    """Sem membership não há projeto, e sem projeto a caixa não existe — 404."""
    stranger = Actor(
        subject=f"sub-stranger-{uuid.uuid4().hex[:8]}",
        email=f"stranger-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Estranho",
    )
    authenticated(stranger)

    assert client.get("/api/v1/me/notifications").status_code == 404
    assert client.post("/api/v1/me/notifications/read", json={}).status_code == 404


def test_search_requires_a_project(world: World, authenticated) -> None:
    """Sem membership não há projeto, e sem projeto não há o que procurar (ADR 0024).

    O caso negativo que a regra 6 do `AGENTS.md` pede de "qualquer endpoint **ou
    busca** nova" — e a rota é escopada, então a negação é 404 como todas as
    outras, nunca 403.
    """
    stranger = Actor(
        subject=f"sub-curioso-{uuid.uuid4().hex[:8]}",
        email=f"curioso-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Sem Projeto",
    )
    authenticated(stranger)

    assert client.get("/api/v1/me/search", params={"q": "contrato"}).status_code == 404


def test_conversations_require_a_project(world: World, authenticated) -> None:
    """Sem membership não há projeto, e sem projeto não há conversa — 404 (ADR 0015).

    Vale para o feedback também: ele resolve o projeto antes de olhar a mensagem,
    então quem não pertence a lugar nenhum não descobre nem que o id existe.
    """
    stranger = Actor(
        subject=f"sub-mudo-{uuid.uuid4().hex[:8]}",
        email=f"mudo-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Sem Projeto",
    )
    authenticated(stranger)

    assert client.get("/api/v1/me/conversations/latest").status_code == 404
    assert (
        client.post(
            f"/api/v1/me/conversations/messages/{uuid.uuid4()}/feedback",
            json={"helpful": True},
        ).status_code
        == 404
    )


def test_a_client_only_sees_and_reads_their_own_notifications(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """Duas pessoas, um projeto: cada uma só alcança a própria linha.

    As linhas entram por uma sessão comitada de verdade, e não pela ``db_session``
    transacional: o app responde em outra conexão e não enxergaria uma transação
    ainda aberta — a mesma razão do fixture ``world``.
    """
    tag = uuid.uuid4().hex[:8]
    with Session(migrated_engine) as setup:
        owner = setup.execute(
            select(User).where(User.external_subject == world.acme.client.subject)
        ).scalar_one()
        colleague = User(
            email=f"colega-{tag}@example.com",
            full_name="Colega",
            external_subject=f"sub-colega-{tag}",
        )
        setup.add(colleague)
        setup.flush()
        setup.add(
            Membership(
                organization_id=world.acme.organization_id,
                project_id=world.acme.project_id,
                user_id=colleague.id,
                role=MemberRole.client_member,
            )
        )
        for recipient, title in ((owner, "Para o cliente"), (colleague, "Para o colega")):
            setup.add(
                Notification(
                    organization_id=world.acme.organization_id,
                    project_id=world.acme.project_id,
                    user_id=recipient.id,
                    kind=NotificationKind.milestone_done,
                    title=title,
                    occurred_at=datetime.now(timezone.utc),
                    dedupe_key=f"{title}-{tag}",
                )
            )
        setup.commit()
        colleague_id = colleague.id

    try:
        authenticated(world.acme.client)
        listed = client.get("/api/v1/me/notifications").json()

        assert [item["title"] for item in listed["items"]] == ["Para o cliente"]
        assert listed["unread_count"] == 1

        marked = client.post("/api/v1/me/notifications/read", json={}).json()
        assert marked["marked"] == 1
        assert client.get("/api/v1/me/notifications").json()["unread_count"] == 0

        # A do colega continua não lida: marcar "todas" é todas *as suas*.
        with Session(migrated_engine) as check:
            others = check.execute(
                select(Notification).where(Notification.user_id == colleague_id)
            ).scalars().all()
            assert [item.read_at for item in others] == [None]
    finally:
        with Session(migrated_engine) as cleanup:
            cleanup.execute(
                delete(Notification).where(
                    Notification.project_id == world.acme.project_id
                )
            )
            cleanup.execute(delete(User).where(User.id == colleague_id))
            cleanup.commit()


def test_the_email_preference_belongs_to_the_caller(world: World, authenticated) -> None:
    """Não recebe id de usuário: a preferência é sempre a de quem chamou.

    A resposta cresceu na ADR 0043 e a igualdade exata **fica**: ela é o que garante
    que a rota devolve o estado inteiro das preferências e não só o campo que o
    chamador mexeu — que é justamente o que a tela passou a adotar, em vez de
    recalcular do próprio lado.
    """
    authenticated(world.acme.client)

    assert client.patch(
        "/api/v1/me/preferences", json={"notify_by_email": False}
    ).json() == {
        "notify_by_email": False,
        "notify_by_whatsapp": False,
        "phone_hint": "",
    }
    assert client.patch(
        "/api/v1/me/preferences", json={"notify_by_email": True}
    ).json() == {
        "notify_by_email": True,
        "notify_by_whatsapp": False,
        "phone_hint": "",
    }


def test_the_channel_refuses_consent_without_a_number(world: World, authenticated) -> None:
    """Ligar o canal sem telefone é 422, não um interruptor ligado sobre nada.

    E o caminho feliz na sequência prova que a recusa é sobre o número e não sobre
    o canal: com o telefone gravado, o mesmo PATCH passa — e o número volta
    **mascarado**, porque a pessoa precisa reconhecer o que está cadastrado sem a
    resposta carregar o número inteiro.
    """
    authenticated(world.acme.client)

    refused = client.patch(
        "/api/v1/me/preferences", json={"notify_by_whatsapp": True}
    )
    assert refused.status_code == 422

    assert client.patch(
        "/api/v1/me/preferences", json={"phone": "+55 (11) 98765-4321"}
    ).json()["phone_hint"] == "••••4321"

    granted = client.patch("/api/v1/me/preferences", json={"notify_by_whatsapp": True})
    assert granted.status_code == 200
    assert granted.json()["notify_by_whatsapp"] is True

    # E o número inteiro não aparece em resposta nenhuma desta rota.
    assert "98765" not in granted.text

    # Apagar o número **revoga** o consentimento, que é o espelho do 422 acima: se
    # ligar sem número é recusado, ficar ligado depois de o número sumir seria o
    # mesmo estado impossível entrando pela outra porta. Isto também limpa o estado
    # para o teste seguinte — o `world` é compartilhado.
    erased = client.patch("/api/v1/me/preferences", json={"phone": ""})
    assert erased.json() == {
        "notify_by_email": True,
        "notify_by_whatsapp": False,
        "phone_hint": "",
    }


# --- URL temporária do documento (Fase 5, ADR 0017) -------------------------


def _document_of(engine: Engine, tenant: Tenant, *, scan_state) -> uuid.UUID:
    from portal_api.models import Document, DocumentOrigin, DocumentSource

    with Session(engine) as session:
        record = Document(
            organization_id=tenant.organization_id,
            project_id=tenant.project_id,
            title="Contrato",
            source=DocumentSource.upload,
            origin=DocumentOrigin.portal,
            mime_type="text/plain",
            scan_state=scan_state,
        )
        session.add(record)
        session.flush()
        record.storage_key = f"org/{tenant.organization_id}/document/{record.id}/x.txt"
        session.commit()
        return record.id


def test_a_document_from_another_project_has_no_download_url(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """O caso de BOLA que esta rota introduz, e a razão de ela existir com teste.

    O cliente da Acme conhece um id — de qualquer forma que o tenha conhecido — e
    pede a URL. A negação é 404 porque a Globex não deve nem confirmar que aquele
    documento existe.
    """
    from portal_api.scanner import ScanState

    document_id = _document_of(migrated_engine, world.globex, scan_state=ScanState.clean)
    authenticated(world.acme.client)

    response = client.get(f"/api/v1/me/documents/{document_id}/download")

    assert response.status_code == 404


def test_an_unscanned_document_has_no_download_url(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """Mesmo dono, mesmo projeto — e ainda assim 404.

    A URL assinada não é apenas um atalho de leitura: ela entrega o arquivo a
    quem tiver o link, fora da sessão. Emiti-la para o que ninguém varreu seria
    contornar a fronteira da ADR 0017 pela porta da frente.
    """
    from portal_api.scanner import ScanState

    document_id = _document_of(migrated_engine, world.acme, scan_state=ScanState.pending)
    authenticated(world.acme.client)

    response = client.get(f"/api/v1/me/documents/{document_id}/download")

    assert response.status_code == 404


def test_an_infected_document_has_no_download_url(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    from portal_api.scanner import ScanState

    document_id = _document_of(
        migrated_engine, world.acme, scan_state=ScanState.infected
    )
    authenticated(world.acme.client)

    response = client.get(f"/api/v1/me/documents/{document_id}/download")

    # O mesmo 404 dos outros dois: a resposta não distingue "não existe" de "não
    # passou", e o cliente não fica sabendo que o portal recebeu um arquivo
    # infectado. Quem precisa saber disso é a administração, e a tela dela diz.
    assert response.status_code == 404


# --- a listagem que dá caller às rotas de organização (Fase 6, ADR 0027) ----


def test_a_client_administers_no_organization_and_the_list_says_so(
    world: World, authenticated
) -> None:
    """Lista vazia com 200 — a única rota de `admin.py` que não responde 404.

    E é o desenho: aqui não há recurso nomeado cuja existência se possa vazar.
    "Não administro nenhuma" é uma verdade sobre o chamador, do mesmo feitio que
    `projects` vazio em `GET /api/v1/me`.
    """
    authenticated(world.acme.client)

    response = client.get("/api/v1/admin/organizations")

    assert response.status_code == 200
    assert response.json() == []


def test_the_list_carries_the_callers_organization_and_not_the_other_tenants(
    world: World, authenticated
) -> None:
    """As duas metades importam, e a segunda é a que torna a primeira significativa.

    O `internal_admin` da Acme recebe o uuid da Acme — que é a peça que nenhuma
    resposta da API devolvia e sem a qual as seis rotas de organização não têm
    caller possível (ADR 0027). E **não** recebe o da Globex, que é a mesma
    fronteira que `test_staff_cannot_reach_another_organizations_retention`
    afirma do outro lado: não basta a rota de escrita recusar o tenant alheio se
    a listagem o entrega.
    """
    authenticated(world.staff)

    body = client.get("/api/v1/admin/organizations").json()

    listed = {item["organization_id"] for item in body}
    assert listed == {str(world.acme.organization_id)}
    assert str(world.globex.organization_id) not in listed
    # O slug vai junto porque é a confirmação que o expurgo exige digitada.
    assert all(item["slug"] for item in body)


# --- retenção e expurgo (Fase 5, ADR 0017) ----------------------------------


def test_a_client_cannot_read_or_set_the_retention_policy(
    world: World, authenticated
) -> None:
    authenticated(world.acme.client)
    organization_id = world.acme.organization_id

    read = client.get(f"/api/v1/admin/organizations/{organization_id}/retention")
    write = client.put(
        f"/api/v1/admin/organizations/{organization_id}/retention",
        json={"notification_days": 1},
    )

    assert read.status_code == 404
    assert write.status_code == 404


def test_a_client_cannot_request_an_erasure(world: World, authenticated) -> None:
    """A ação mais destrutiva do portal, pedida por quem não a administra."""
    authenticated(world.acme.client)

    response = client.post(
        f"/api/v1/admin/organizations/{world.acme.organization_id}/erasure",
        json={"reason": "pedido do titular", "confirm_slug": "qualquer-coisa"},
    )

    assert response.status_code == 404


def test_staff_cannot_reach_another_organizations_retention(
    world: World, authenticated
) -> None:
    """O `internal_admin` da Acme não administra a Globex.

    É a mesma fronteira do resto de `admin.py`, e ela precisa valer também para a
    primeira rota cujo escopo é a organização inteira.
    """
    authenticated(world.staff)

    response = client.get(
        f"/api/v1/admin/organizations/{world.globex.organization_id}/retention"
    )

    assert response.status_code == 404


def test_a_client_cannot_read_the_onboarding_funnel(world: World, authenticated) -> None:
    """O cliente não deve nem saber que está sendo medido em funil (FDD 020).

    Aqui a regra 6 do `AGENTS.md` guarda mais do que uma fronteira de tenant: a resposta
    descreve o comportamento de uma pessoa nomeada, que é a classe mais sensível da
    `data-classification.md`.
    """
    authenticated(world.acme.client)

    response = client.get(
        f"/api/v1/admin/organizations/{world.acme.organization_id}/onboarding"
    )

    assert response.status_code == 404


def test_staff_cannot_read_another_organizations_onboarding_funnel(
    world: World, authenticated
) -> None:
    """A rota computa sob `portal_system`, e a fronteira continua sendo a de sempre.

    É o par negativo que importa mais nesta fatia: a leitura roda com a credencial que
    enxerga todos os tenants — porque `pending_item` não tem policy para `portal_admin` —,
    e o que a mantém escopada é o `_authorized_org` **antes** dela, nunca o id da URL.
    """
    authenticated(world.staff)

    response = client.get(
        f"/api/v1/admin/organizations/{world.globex.organization_id}/onboarding"
    )

    assert response.status_code == 404


def test_a_client_cannot_read_or_set_the_ai_spending_cap(
    world: World, authenticated
) -> None:
    """As duas rotas do teto de gasto de IA, que não tinham teste de espécie alguma.

    Elas existem desde a ADR 0022 e ganharam tela na ADR 0027; as catorze
    asserções de `test_ai_quota.py` fixam o teto escrevendo a linha direto no
    banco pela fixture, então o caminho que uma pessoa percorre — a rota — nunca
    havia sido exercitado. Foi o que a guarda da regra 6 encontrou.
    """
    authenticated(world.acme.client)
    organization_id = world.acme.organization_id

    read = client.get(f"/api/v1/admin/organizations/{organization_id}/ai-quota")
    write = client.put(
        f"/api/v1/admin/organizations/{organization_id}/ai-quota",
        json={"monthly_limit_cents": 1},
    )

    assert read.status_code == 404
    assert write.status_code == 404


def test_staff_cannot_reach_another_organizations_ai_spending_cap(
    world: World, authenticated
) -> None:
    """A outra metade: administrar a Acme não é administrar a Globex.

    Vale a pena separado porque o teto é dinheiro de **outro** tenant, e porque
    `_authorized_org` é o único ponto que separa as duas organizações aqui.
    """
    authenticated(world.staff)
    organization_id = world.globex.organization_id

    read = client.get(f"/api/v1/admin/organizations/{organization_id}/ai-quota")
    write = client.put(
        f"/api/v1/admin/organizations/{organization_id}/ai-quota",
        json={"monthly_limit_cents": 1},
    )

    assert read.status_code == 404
    assert write.status_code == 404


def test_a_client_cannot_read_the_erasure_history(world: World, authenticated) -> None:
    """O `POST` tinha negativo desde a ADR 0017; o `GET` do histórico, não.

    E é ele que lista o que já foi pedido — motivo, quem executou e o que saiu —,
    de modo que ler sem poder pedir ainda seria ler a decisão alheia.
    """
    authenticated(world.acme.client)

    response = client.get(
        f"/api/v1/admin/organizations/{world.acme.organization_id}/erasure"
    )

    assert response.status_code == 404


# --- a apuração por período (Fase 3, ADR 0013) ------------------------------


def test_the_results_route_refuses_another_tenants_project(
    world: World, authenticated
) -> None:
    """A **única** rota de cliente que recebe um id de projeto no caminho.

    Ou seja, o caso literal da regra 1 do `AGENTS.md` — "nunca use um
    identificador fornecido pelo cliente sem validar o vínculo no servidor" — e
    não havia teste nenhum a exercitando: a guarda da regra 6 a encontrou junto
    com o teto de IA. As demais rotas do cliente resolvem o projeto por
    `access.default_project`, e o que o navegador não manda é o que ninguém
    precisa validar.
    """
    authenticated(world.acme.client)

    alheio = client.get(f"/api/v1/projects/{world.globex.project_id}/results")
    inexistente = client.get(f"/api/v1/projects/{uuid.uuid4()}/results")

    # Os dois são o mesmo 404: distinguir "não é seu" de "não existe" criaria o
    # oráculo que a ADR 0010 evita.
    assert alheio.status_code == 404
    assert inexistente.status_code == 404


def test_the_chat_requires_a_project(world: World, authenticated) -> None:
    """Sem membership não há projeto, e sem projeto não há o que responder.

    O irmão exato de `test_notifications_require_a_project` e
    `test_search_requires_a_project`, que existiam — o chat era a rota `/me` sem
    identificador que tinha ficado sem o seu, e a guarda da regra 6 mostrou que
    a omissão não tinha razão de ser.
    """
    stranger = Actor(
        subject=f"sub-sem-projeto-{uuid.uuid4().hex[:8]}",
        email=f"sem-projeto-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Sem Projeto",
    )
    authenticated(stranger)

    response = client.post("/api/v1/chat", json={"question": "Qual é o status?"})

    assert response.status_code == 404


# --- o sinal do assistente (Fase 6, ADR 0030) -------------------------------


def test_a_client_cannot_read_the_assistant_signal(world: World, authenticated) -> None:
    """A rota lê a avaliação que **outras pessoas** deixaram. Um cliente vê a
    própria conversa pelo histórico do chat e nada além disso."""
    authenticated(world.acme.client)

    response = client.get(
        f"/api/v1/admin/projects/{world.acme.project_id}/assistant-signal"
    )

    assert response.status_code == 404


def test_staff_cannot_read_the_assistant_signal_of_another_project(
    world: World, authenticated
) -> None:
    authenticated(world.staff)

    response = client.get(
        f"/api/v1/admin/projects/{world.globex.project_id}/assistant-signal"
    )

    assert response.status_code == 404


def test_a_named_conversation_of_someone_else_is_not_found(
    world: World, authenticated, db_session: Session
) -> None:
    """A rota nova da ADR 0031, com o caso que dá sentido a ela.

    Duas barreiras, e nenhuma escrita na rota: o repositório filtra por
    `user_id` e a policy de `conversation` exige
    `user_id = portal.current_user_id()`.
    """
    from portal_api.models import Conversation

    other = db_session.execute(
        select(User).where(User.external_subject == world.globex.client.subject)
    ).scalar_one()
    conversation = Conversation(
        organization_id=world.globex.organization_id,
        project_id=world.globex.project_id,
        user_id=other.id,
        title="pergunta da globex",
        last_message_at=datetime.now(timezone.utc),
    )
    db_session.add(conversation)
    db_session.commit()

    authenticated(world.acme.client)
    response = client.get(f"/api/v1/me/conversations/{conversation.id}")

    assert response.status_code == 404

    db_session.delete(conversation)
    db_session.commit()


# --- comentários na pendência (Fase 2, ADR 0032) -----------------------------


def _pending_of(engine: Engine, tenant: Tenant) -> uuid.UUID:
    """Uma pendência **commitada** no tenant, porque a API responde por outra
    conexão e não veria a transação aberta do `db_session` (ver o docstring do
    módulo)."""
    with Session(engine) as session:
        pending = PendingItem(
            organization_id=tenant.organization_id,
            project_id=tenant.project_id,
            title="Enviar a planilha",
        )
        session.add(pending)
        session.commit()
        return pending.id


def test_a_client_cannot_read_or_write_comments_of_another_project(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """404 e **não lista vazia**: uma lista vazia diria "existe e ninguém
    comentou", que é informação sobre um recurso que o chamador não alcança."""
    other = _pending_of(migrated_engine, world.globex)
    authenticated(world.acme.client)

    read = client.get(f"/api/v1/me/pendings/{other}/comments")
    write = client.post(f"/api/v1/me/pendings/{other}/comments", json={"body": "oi"})

    assert read.status_code == 404
    assert write.status_code == 404


def test_a_comment_records_who_wrote_it_and_which_side(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """O lado é gravado, não derivado do papel atual (ADR 0032): quem deixa de ser
    interno não muda o lado de quem falou naquele dia."""
    mine = _pending_of(migrated_engine, world.acme)
    authenticated(world.acme.client)

    created = client.post(
        f"/api/v1/me/pendings/{mine}/comments", json={"body": "Já enviei ontem."}
    )

    assert created.status_code == 201
    body = created.json()
    assert body["author_label"] == world.acme.client.full_name
    assert body["author_is_internal"] is False

    listed = client.get(f"/api/v1/me/pendings/{mine}/comments").json()
    assert [item["body"] for item in listed["items"]] == ["Já enviei ontem."]


def test_a_cross_tenant_attempt_leaves_a_trace_the_runbook_can_count(
    world: World, authenticated
) -> None:
    """A negação passa a ter sinal, e ele distingue dois fatos (ADR 0034).

    `docs/observability.md` lista "anomalias de autorização" entre os indicadores
    desde a Fase 1, e `access.py` não tinha uma linha de log: um cliente
    autenticado percorrendo ids alheios produzia só `http.request` com
    `status: 404` e o template da rota — sem ator, e portanto sem como contar
    por pessoa, que é o que separa um link velho de uma enumeração.

    As duas metades importam. O evento existe **e** a resposta continua opaca:
    se a fatia tivesse mudado o corpo ou o código de status para distinguir "não
    é seu" de "não existe", teria criado o oráculo que a ADR 0010 evita.
    """
    authenticated(world.acme.client)

    with captured("portal_api.access") as records:
        theirs = client.get(f"/api/v1/projects/{world.globex.project_id}/dashboard")

    # Opaca: o projeto do vizinho responde exatamente como um id que não existe.
    ghost = client.get(f"/api/v1/projects/{uuid.uuid4()}/dashboard")
    assert theirs.status_code == ghost.status_code == 404
    assert theirs.json() == ghost.json()

    denied = [r for r in records if r.getMessage() == "authz.denied"]
    assert len(denied) == 1
    assert denied[0].reason == "not_a_member"
    # O prefixo, nunca o `sub` inteiro — o precedente é do `chat_limit.py`.
    assert denied[0].subject_prefix == world.acme.client.subject[:8]
    assert len(denied[0].subject_prefix) <= 8


def test_a_member_without_the_role_is_a_different_reason(world: World, authenticated) -> None:
    """"Não é membro" e "é membro e o papel não basta" levam a investigações
    diferentes: a primeira é acesso cruzado, a segunda é escalada dentro do
    próprio tenant. Um `reason` só apagaria a distinção justamente onde ela
    decide o que fazer."""
    # O cliente **é** membro do próprio projeto; o que ele não é é
    # `internal_admin`, e `_authorized` de `admin.py` exige exatamente isso.
    authenticated(world.acme.client)

    with captured("portal_api.access") as records:
        refused = client.get(f"/api/v1/admin/projects/{world.acme.project_id}/members")

    assert refused.status_code == 404
    denied = [r for r in records if r.getMessage() == "authz.denied"]
    assert [r.reason for r in denied] == ["role_insufficient"]


# --- o projeto encerrado no Biahflow (Fase 6, ADR 0036) ----------------------


@contextmanager
def _read_only(
    migrated_engine: Engine, project_id: uuid.UUID, column: str = "archived_at"
) -> Iterator[None]:
    """Põe o projeto em modo de consulta e desfaz, porque `world` é de sessão inteira.

    `column` escolhe o motivo — `archived_at` (ADR 0036) ou `source_deleted_at` (ADR 0037).
    Os dois fecham a escrita com 409, e o teste abaixo cobra que fechem pelo motivo certo.
    """
    with Session(migrated_engine) as session:
        session.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(**{column: datetime.now(timezone.utc)})
        )
        session.commit()
    try:
        yield
    finally:
        with Session(migrated_engine) as session:
            session.execute(
                update(Project).where(Project.id == project_id).values(**{column: None})
            )
            session.commit()


def test_o_projeto_encerrado_recusa_escrita_com_409_e_nao_com_404(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """Projeto encerrado fecha a escrita e mantém a leitura (ADR 0036).

    O código importa mais do que parece. 404 neste contrato significa **uma coisa só** — o
    chamador não tem vínculo —, e é a única resposta que a regra 6 verifica em toda rota
    escopada. Usá-lo aqui tornaria "você não tem acesso" indistinguível de "este projeto
    acabou", e um cliente legítimo passaria a receber a mesma resposta de um invasor.
    """
    authenticated(world.acme.client)

    with _read_only(migrated_engine, world.acme.project_id):
        recusado = client.post("/api/v1/chat", json={"question": "Qual é o status?"})
        assert recusado.status_code == 409

        # A leitura continua aberta: o histórico é a evidência das respostas já dadas.
        dashboard = client.get("/api/v1/me/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["archived_at"] is not None

    # E restaurado, volta a responder — a interface do Biahflow arquiva e desarquiva por item.
    assert client.get("/api/v1/me/dashboard").json()["archived_at"] is None


def test_o_projeto_apagado_na_origem_recusa_escrita_e_diz_qual_motivo(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """Apagado no Biahflow fecha a escrita como encerrado, mas não é a mesma coisa (ADR 0037).

    Mesmo código — 409, pelo mesmo argumento da ADR 0036 —, e `detail` diferente, porque quem
    lê o corpo é a tela e as duas frases que ela mostra ao cliente não são intercambiáveis:
    encerrado tem volta pela interface do Biahflow, apagado não tem nenhuma.

    A leitura segue aberta pela razão de sempre: o histórico é a evidência das respostas já
    dadas, e este lado não apaga nada por conta de um webhook (ADR 0017).
    """
    authenticated(world.acme.client)

    with _read_only(migrated_engine, world.acme.project_id, "source_deleted_at"):
        recusado = client.post("/api/v1/chat", json={"question": "Qual é o status?"})
        assert recusado.status_code == 409
        assert recusado.json()["detail"] == "Project deleted at source"

        dashboard = client.get("/api/v1/me/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["source_deleted_at"] is not None
        # E o encerramento continua nulo: são colunas diferentes porque são fatos diferentes.
        assert dashboard.json()["archived_at"] is None


def test_encerrado_e_apagado_juntos_recusam_pelo_motivo_mais_forte(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """Um projeto pode ser arquivado e depois apagado, e aí as duas datas existem.

    A ordem em `_refuse_when_read_only` é o que decide o que o cliente lê, e a tela usa a
    mesma — se as duas divergirem, o portal passa a dizer "encerrado" na barra e "removido"
    no chat sobre o mesmo projeto.
    """
    authenticated(world.acme.client)

    with _read_only(migrated_engine, world.acme.project_id):
        with _read_only(migrated_engine, world.acme.project_id, "source_deleted_at"):
            recusado = client.post("/api/v1/chat", json={"question": "Qual é o status?"})
            assert recusado.status_code == 409
            assert recusado.json()["detail"] == "Project deleted at source"


def test_quem_nao_tem_vinculo_leva_404_mesmo_no_projeto_encerrado(
    world: World, authenticated, migrated_engine: Engine
) -> None:
    """As duas negações não podem se confundir, e esta é a metade que erra em silêncio.

    Se o 409 fosse levantado antes de resolver o vínculo, ele contaria a um estranho que o
    projeto existe — exatamente o que "404, nunca 403" existe para impedir.
    """
    stranger = Actor(
        subject=f"sub-sem-projeto-{uuid.uuid4().hex[:8]}",
        email=f"sem-projeto-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Sem Projeto",
    )
    authenticated(stranger)

    with _read_only(migrated_engine, world.acme.project_id):
        recusado = client.post("/api/v1/chat", json={"question": "Qual é o status?"})
        assert recusado.status_code == 404

    # E vale igual para o projeto apagado na origem, que é o motivo mais forte (ADR 0037):
    # sem o 404 vindo primeiro, o 409 contaria a um estranho que o projeto um dia existiu.
    with _read_only(migrated_engine, world.acme.project_id, "source_deleted_at"):
        apagado = client.post("/api/v1/chat", json={"question": "Qual é o status?"})
        assert apagado.status_code == 404


# --- a regra 6, derivada do contrato (ADR 0035) -----------------------------
#
# Até aqui este arquivo era a prova da regra 6 e também o seu inventário: 30
# funções escritas à mão contra 46 pares rota+método publicados. Nada perguntava
# se a lista estava inteira, que é a forma exata do defeito da ADR 0033 — lá a
# guarda percorria oito nomes digitados num contrato de 56 esquemas.
#
# A pergunta agora sai do contrato, e não de quem lembrou: **toda rota que
# promete 404 tem de provar o 404.** A promessa é o `responses` do próprio
# artefato publicado, de modo que as superfícies que legitimamente não negam por
# tenant — as duas sondas, o webhook e as duas rotas `/me` sem identificador —
# se isentam sozinhas, sem allowlist para manter.

#: Os dois mecanismos de credencial do produto: a sessão OIDC (ADR 0010) e a
#: chave de agente (ADR 0013). Um teste que não troca de ator não é negativo de
#: permissão — é só uma chamada que deu 404.
_ACTOR_FIXTURES = {"authenticated", "agent_key"}

_HTTP_VERBS = {"get", "post", "patch", "put", "delete"}


def _url_pattern(node: ast.expr, variables: dict[str, str]) -> str | None:
    """Resolve a expressão de URL para o padrão, com `{}` no lugar do dinâmico.

    Três formas, e as três são reais neste diretório: o literal, a f-string
    (`f"/api/v1/admin/organizations/{org.id}/retention"`) e a variável local
    montada antes (`base = f"..."` seguido de `f"{base}/keys"`), que é como
    `test_admin_endpoints.py` escreve o laço de negativos.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return variables.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            elif isinstance(piece, ast.FormattedValue):
                inner = _url_pattern(piece.value, variables)
                parts.append(inner if inner is not None else "{}")
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _url_pattern(node.left, variables)
        right = _url_pattern(node.right, variables)
        return None if left is None or right is None else left + right
    return None


def _string_variables(fn: ast.AST) -> dict[str, str]:
    known: dict[str, str] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                resolved = _url_pattern(node.value, known)
                if resolved is not None:
                    known[target.id] = resolved
    return known


def _requests_in(fn: ast.AST) -> set[tuple[str, str]]:
    """Os pares (verbo, padrão de URL) que este corpo dispara pelo `TestClient`."""
    variables = _string_variables(fn)
    found: set[tuple[str, str]] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in _HTTP_VERBS):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "client"):
            continue
        if not node.args:
            continue
        url = _url_pattern(node.args[0], variables)
        if url:
            found.add((func.attr, _normalise_path(url)))
    return found


def _normalise_path(url: str) -> str:
    """`/x/{project_id}/y?a=1` e `/x/{uuid4()}/y` viram o mesmo `/x/{}/y`."""
    return re.sub(r"\{[^}]*\}", "{}", url).split("?")[0].rstrip("/")


def _response_variables(
    fn: ast.AST, helpers: dict[str, set[tuple[str, str]]]
) -> dict[str, set[tuple[str, str]]]:
    """Nome da variável → as requisições cuja resposta ela guarda.

    Cobre as três formas que aparecem aqui: uma chamada (`refused = client.get(…)`),
    uma lista delas (`responses = [client.get(…), client.post(…)]`, o laço de
    negativos de `test_admin_endpoints.py`) e o auxiliar de módulo
    (`response = _post(…)`, em `test_agent_events.py`).
    """
    variables = _string_variables(fn)
    held: dict[str, set[tuple[str, str]]] = {}
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        sources = (
            node.value.elts
            if isinstance(node.value, (ast.List, ast.Tuple))
            else [node.value]
        )
        pairs: set[tuple[str, str]] = set()
        for source in sources:
            if not isinstance(source, ast.Call):
                continue
            func = source.func
            if isinstance(func, ast.Name) and func.id in helpers:
                pairs |= helpers[func.id]
            elif (
                isinstance(func, ast.Attribute)
                and func.attr in _HTTP_VERBS
                and isinstance(func.value, ast.Name)
                and func.value.id == "client"
                and source.args
            ):
                url = _url_pattern(source.args[0], variables)
                if url:
                    pairs.add((func.attr, _normalise_path(url)))
        if pairs:
            held[target.id] = pairs
    return held


def _denied_in(fn: ast.AST, helpers: dict[str, set[tuple[str, str]]]) -> set[tuple[str, str]]:
    """As requisições **deste** teste cuja resposta ele afirma ser 404.

    A ligação é entre o 404 e a resposta, e não entre o 404 e o arquivo. Isso foi
    medido: com o elo frouxo — "a função chama a rota e em algum lugar do corpo há
    um 404" — `POST /api/v1/chat` aparecia coberto por
    `test_rating_a_colleagues_answer_is_404`, onde o chat só monta a conversa e o
    404 é da rota de feedback. A guarda nasceria verde sobre uma rota sem negativo,
    que é exatamente o defeito da ADR 0033.
    """
    held = _response_variables(fn, helpers)
    denied: set[tuple[str, str]] = set()
    for node in ast.walk(fn):
        if not isinstance(node, (ast.Assert, ast.Compare)):
            continue
        if not any(
            isinstance(inner, ast.Constant) and inner.value == 404
            for inner in ast.walk(node)
        ):
            continue
        # Quem é mencionado ao lado do 404: as variáveis de resposta e as chamadas
        # feitas ali mesmo (`assert client.get(…).status_code == 404`).
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and inner.id in held:
                denied |= held[inner.id]
        denied |= _requests_in(node)
    return denied


def _proven_denials() -> set[tuple[str, str]]:
    """Todo par rota+verbo que algum teste nega com 404, trocando de ator.

    Segue os auxiliares de módulo, e isso não é refinamento: `test_agent_events.py`
    manda a requisição por um `_post()` de três linhas, então uma varredura que só
    olhasse `client.post(...)` dentro da função de teste concluiria que a rota de
    eventos — a única com credencial própria — não tem negativo nenhum.
    """
    proven: set[tuple[str, str]] = set()
    for path in sorted(pathlib.Path(__file__).parent.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        helpers = {
            node.name: _requests_in(node)
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("test_")
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            parameters = {arg.arg for arg in node.args.args}
            if not (parameters & _ACTOR_FIXTURES):
                continue
            proven |= _denied_in(node, helpers)
    return proven


#: A única rota que promete 404 e não pode prová-lo, com o motivo. Ela responde
#: **200 com lista vazia** por desenho (ADR 0027) — não há recurso nomeado cuja
#: existência se possa vazar —, e o 404 no contrato vem do `CLIENT_ERRORS` que
#: toda rota de `admin.py` carrega. O negativo dela existe e tem outra forma: a
#: lista não traz a organização alheia, afirmado em
#: `test_the_organizations_listing_only_shows_what_the_caller_administers`.
_CANNOT_ANSWER_404 = {
    ("get", "/api/v1/admin/organizations"): (
        "responde 200 com lista vazia (ADR 0027); o negativo é a filtragem da lista"
    ),
}


def test_every_route_that_promises_a_404_proves_it() -> None:
    """Regra 6 do `AGENTS.md`, cobrada do contrato e não da memória.

    Nasceu vermelha com seis pares, e o mais caro deles não era um esquecimento
    de borda: `GET /api/v1/projects/{project_id}/results` é a **única** rota de
    cliente que recebe um identificador de projeto no caminho, ou seja, o caso
    literal da regra 1 — "nunca use um identificador fornecido pelo cliente sem
    validar o vínculo no servidor" —, e não havia teste nenhum a exercitando.
    Junto vieram as duas rotas do teto de gasto de IA, que não tinham teste de
    espécie alguma, o histórico do expurgo e o chat.
    """
    document = openapi.schema()
    proven = _proven_denials()

    missing = sorted(
        f"{method.upper()} {path}"
        for path, operations in document["paths"].items()
        for method, operation in operations.items()
        if "404" in operation["responses"]
        and (method.lower(), _normalise_path(path)) not in proven
        and (method.lower(), _normalise_path(path)) not in _CANNOT_ANSWER_404
    )

    assert missing == [], (
        "estas rotas prometem 404 no contrato e nenhum teste prova a negação: "
        + ", ".join(missing)
        + ". Escreva o caso negativo de permissão (regra 6 do `AGENTS.md`) — um"
        " teste que troque de ator e afirme 404."
    )


def test_the_exception_to_the_404_proof_is_still_needed() -> None:
    """A linha some quando o motivo some — a regra do `advisories.json` (ADR 0023)."""
    document = openapi.schema()
    proven = _proven_denials()

    obsolete = sorted(
        f"{method.upper()} {path}"
        for method, path in _CANNOT_ANSWER_404
        if (method, path) in proven
        or "404" not in document["paths"].get(path, {}).get(method, {}).get("responses", {})
    )

    assert obsolete == [], (
        f"`_CANNOT_ANSWER_404` guarda linhas que deixaram de ser necessárias: {obsolete}."
    )
