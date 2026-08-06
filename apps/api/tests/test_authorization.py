"""Negative permission cases through the real HTTP stack (AGENTS.md #6, ADR 0010).

Only ``bearer_principal`` is overridden — token validation has its own file. From
there down everything is real: the endpoints open a session under ``portal_app``,
resolve the user, and read through the RLS policies. So a "404" here means the
denial survived the whole chain, not that a mock said no.

The rows are committed by a ``portal_system`` session because the app answers on
a different connection and would not see an open transaction's writes.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

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
    """Não recebe id de usuário: a preferência é sempre a de quem chamou."""
    authenticated(world.acme.client)

    assert client.patch(
        "/api/v1/me/preferences", json={"notify_by_email": False}
    ).json() == {"notify_by_email": False}
    assert client.patch(
        "/api/v1/me/preferences", json={"notify_by_email": True}
    ).json() == {"notify_by_email": True}


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
