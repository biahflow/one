"""Convite e revogação pelo stack HTTP real (ADR 0011).

Só o `bearer_principal` e o cliente do Keycloak são dublados. Daí para baixo é
tudo de verdade: a sessão abre sob `portal_admin`, a autorização acontece antes
da GUC de administração e as policies decidem o que a transação alcança. Um 404
aqui significa que a negação sobreviveu à cadeia inteira.

O Keycloak é dublado porque o que ele faz é mandar e-mail — isso quem prova é o
`tests/e2e/invite.spec.ts`, lendo a caixa do Mailpit. Aqui interessa o contrato:
uma conta por e-mail, e um convite disparado por chamada.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from drive_fake import FakeDrive, FakeFile
from portal_api import admin as admin_module
from portal_api.auth import bearer_principal
from portal_api.keycloak_admin import KeycloakAdminError, RealmUser
from portal_api.main import app
from portal_api.models import (
    AuditLog,
    MemberRole,
    Membership,
    Organization,
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
    project_id: uuid.UUID
    admin: Actor
    client_actor: Actor
    client_membership_id: uuid.UUID
    admin_membership_id: uuid.UUID
    second_admin: Actor


@dataclass
class FakeKeycloak:
    """Registra o que foi pedido e devolve `sub`s estáveis por e-mail."""

    known: dict[str, RealmUser] = field(default_factory=dict)
    created: list[str] = field(default_factory=list)
    invitations: list[str] = field(default_factory=list)
    unverified: set[str] = field(default_factory=set)

    def find_by_email(self, email: str) -> RealmUser | None:
        return self.known.get(email)

    def unverified_emails(self) -> set[str]:
        return set(self.unverified)

    def create_user(self, email: str, full_name: str) -> RealmUser:
        self.created.append(email)
        user = RealmUser(
            subject=f"sub-realm-{uuid.uuid4().hex[:10]}", email=email, email_verified=False
        )
        self.known[email] = user
        self.unverified.add(email)
        return user

    def send_invitation(self, subject: str) -> None:
        self.invitations.append(subject)


@pytest.fixture
def keycloak(monkeypatch: pytest.MonkeyPatch) -> FakeKeycloak:
    fake = FakeKeycloak()
    monkeypatch.setattr(admin_module, "KeycloakAdmin", lambda _settings: fake)
    return fake


@pytest.fixture
def world(migrated_engine: Engine) -> Iterator[dict[str, Tenant]]:
    tag = uuid.uuid4().hex[:8]
    tenants: dict[str, Tenant] = {}
    session = Session(migrated_engine)

    for name in ("acme", "globex"):
        organization = Organization(name=name.title(), slug=f"{name}-api-{tag}")
        session.add(organization)
        session.flush()

        project = Project(
            organization_id=organization.id,
            name=f"Projeto {name.title()}",
            slug=f"{name}-api-project-{tag}",
            status=ProjectStatus.in_implementation,
        )
        session.add(project)
        session.flush()

        admin_user = User(
            email=f"admin-{name}-{tag}@portallabs.test",
            full_name=f"Admin {name.title()}",
            external_subject=f"sub-admin-{name}-{tag}",
            is_internal=True,
        )
        client_user = User(
            email=f"cliente-{name}-{tag}@example.com",
            full_name=f"Cliente {name.title()}",
            external_subject=f"sub-cliente-{name}-{tag}",
        )
        # Um segundo administrador da mesma organização. Existe para os casos em
        # que "tem permissão" e "é a mesma pessoa" precisam ser distinguidos — o
        # `state` do OAuth é o primeiro deles (ADR 0016).
        second_admin_user = User(
            email=f"admin2-{name}-{tag}@portallabs.test",
            full_name=f"Admin {name.title()} II",
            external_subject=f"sub-admin2-{name}-{tag}",
            is_internal=True,
        )
        session.add_all([admin_user, client_user, second_admin_user])
        session.flush()

        # Org-wide, como o seed faz para a equipe interna.
        admin_membership = Membership(
            organization_id=organization.id,
            project_id=None,
            user_id=admin_user.id,
            role=MemberRole.internal_admin,
        )
        client_membership = Membership(
            organization_id=organization.id,
            project_id=project.id,
            user_id=client_user.id,
            role=MemberRole.client_member,
        )
        second_admin_membership = Membership(
            organization_id=organization.id,
            project_id=None,
            user_id=second_admin_user.id,
            role=MemberRole.internal_admin,
        )
        session.add_all([admin_membership, client_membership, second_admin_membership])
        session.flush()

        tenants[name] = Tenant(
            organization_id=organization.id,
            project_id=project.id,
            admin=Actor(
                admin_user.external_subject or "",
                admin_user.email,
                admin_user.full_name,
                ("internal_admin",),
            ),
            client_actor=Actor(
                client_user.external_subject or "", client_user.email, client_user.full_name
            ),
            client_membership_id=client_membership.id,
            admin_membership_id=admin_membership.id,
            second_admin=Actor(
                second_admin_user.external_subject or "",
                second_admin_user.email,
                second_admin_user.full_name,
                ("internal_admin",),
            ),
        )

    session.commit()
    yield tenants

    session.execute(
        delete(AuditLog).where(
            AuditLog.organization_id.in_([t.organization_id for t in tenants.values()])
        )
    )
    session.execute(
        delete(Organization).where(
            Organization.id.in_([t.organization_id for t in tenants.values()])
        )
    )
    session.execute(delete(User).where(User.email.like(f"%-{tag}@%")))
    session.execute(delete(User).where(User.email.like(f"convidado-{tag}%")))
    session.commit()
    session.close()


@pytest.fixture
def authenticated() -> Iterator[Callable[[Actor], None]]:
    def _as(actor: Actor) -> None:
        app.dependency_overrides[bearer_principal] = lambda: Principal(
            subject=actor.subject,
            email=actor.email,
            full_name=actor.full_name,
            realm_roles=frozenset(actor.realm_roles),
        )

    yield _as
    app.dependency_overrides.clear()


def _invitation(tag: str, role: str = "client_member") -> dict:
    return {
        "email": f"convidado-{tag}@cliente.com.br",
        "full_name": "Convidado Novo",
        "role": role,
    }


# --- negativos de permissão (AGENTS.md #6) --------------------------------


def test_a_client_member_reaches_no_admin_route(world, authenticated, keycloak) -> None:
    """Negação é 404 e não 403: nem a existência da rota é confirmada."""
    acme = world["acme"]
    authenticated(acme.client_actor)

    listing = client.get(f"/api/v1/admin/projects/{acme.project_id}/members")
    invite = client.post(
        f"/api/v1/admin/projects/{acme.project_id}/members",
        json=_invitation(uuid.uuid4().hex[:6]),
    )
    revoke = client.delete(
        f"/api/v1/admin/projects/{acme.project_id}/members/{acme.client_membership_id}"
    )

    assert [listing.status_code, invite.status_code, revoke.status_code] == [404, 404, 404]
    assert keycloak.created == [], "não deve nem chegar ao provedor de identidade"


def test_an_administrator_cannot_reach_another_tenant(world, authenticated, keycloak) -> None:
    authenticated(world["acme"].admin)
    globex = world["globex"]

    listing = client.get(f"/api/v1/admin/projects/{globex.project_id}/members")
    invite = client.post(
        f"/api/v1/admin/projects/{globex.project_id}/members",
        json=_invitation(uuid.uuid4().hex[:6]),
    )

    assert listing.status_code == 404
    assert invite.status_code == 404


def test_revoking_a_membership_from_another_project_is_not_found(
    world, authenticated
) -> None:
    """O vínculo existe; para este projeto, não. A resposta não distingue."""
    acme, globex = world["acme"], world["globex"]
    authenticated(acme.admin)

    response = client.delete(
        f"/api/v1/admin/projects/{acme.project_id}/members/{globex.client_membership_id}"
    )

    assert response.status_code == 404


# --- listagem --------------------------------------------------------------


def test_listing_shows_the_projects_members_and_who_is_still_pending(
    world, authenticated, keycloak
) -> None:
    """"Convite pendente" é o e-mail ainda não confirmado no realm — o único
    sinal que distingue "convidei" de "entrou"."""
    acme = world["acme"]
    keycloak.unverified.add(acme.client_actor.email)
    authenticated(acme.admin)

    body = client.get(f"/api/v1/admin/projects/{acme.project_id}/members").json()

    by_email = {member["email"]: member for member in body}
    assert set(by_email) == {
        acme.admin.email,
        acme.second_admin.email,
        acme.client_actor.email,
    }
    assert by_email[acme.admin.email]["active"] is True
    assert by_email[acme.client_actor.email]["active"] is False
    assert world["globex"].client_actor.email not in by_email


def test_listing_survives_the_identity_provider_being_down(
    world, authenticated, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Saber quem já entrou é conveniência; a lista de acesso não pode sumir junto."""
    acme = world["acme"]

    class Broken(FakeKeycloak):
        def unverified_emails(self) -> set[str]:
            raise KeycloakAdminError("keycloak down")

    monkeypatch.setattr(admin_module, "KeycloakAdmin", lambda _settings: Broken())
    authenticated(acme.admin)

    response = client.get(f"/api/v1/admin/projects/{acme.project_id}/members")

    assert response.status_code == 200
    assert all(member["active"] for member in response.json())


# --- convite ---------------------------------------------------------------


def test_inviting_creates_the_account_the_membership_and_sends_one_email(
    world, authenticated, keycloak, migrated_engine: Engine
) -> None:
    acme = world["acme"]
    authenticated(acme.admin)
    tag = uuid.uuid4().hex[:6]
    payload = _invitation(tag)

    response = client.post(
        f"/api/v1/admin/projects/{acme.project_id}/members", json=payload
    )

    assert response.status_code == 201
    assert response.json()["email"] == payload["email"]
    # Convite pendente: a conta existe, mas o e-mail ainda não foi verificado.
    assert response.json()["active"] is False
    assert keycloak.created == [payload["email"]]
    assert len(keycloak.invitations) == 1

    with Session(migrated_engine) as check:
        user = check.execute(
            select(User).where(User.email == payload["email"])
        ).scalar_one()
        assert user.external_subject, "o `sub` do realm é gravado no convite"
        assert user.is_internal is False
        membership = check.execute(
            select(Membership).where(Membership.user_id == user.id)
        ).scalar_one()
        assert membership.project_id == acme.project_id
        assert membership.role is MemberRole.client_member


def test_inviting_twice_does_not_duplicate_anything(
    world, authenticated, keycloak, migrated_engine: Engine
) -> None:
    """Reconvidar é reenviar: mesma conta, mesmo vínculo, e-mail de novo."""
    acme = world["acme"]
    authenticated(acme.admin)
    payload = _invitation(uuid.uuid4().hex[:6])

    first = client.post(f"/api/v1/admin/projects/{acme.project_id}/members", json=payload)
    second = client.post(f"/api/v1/admin/projects/{acme.project_id}/members", json=payload)

    assert [first.status_code, second.status_code] == [201, 201]
    assert first.json()["membership_id"] == second.json()["membership_id"]
    assert keycloak.created == [payload["email"]], "a conta só é criada uma vez"
    assert len(keycloak.invitations) == 2, "mas o e-mail sai de novo"

    with Session(migrated_engine) as check:
        count = len(
            check.execute(
                select(Membership)
                .join(User, User.id == Membership.user_id)
                .where(User.email == payload["email"])
            ).all()
        )
    assert count == 1


def test_inviting_an_internal_role_marks_the_user_as_staff(
    world, authenticated, keycloak, migrated_engine: Engine
) -> None:
    """`is_internal` vem da membership, não do realm role (ADR 0010/0011)."""
    acme = world["acme"]
    authenticated(acme.admin)
    payload = _invitation(uuid.uuid4().hex[:6], role="internal_member")

    client.post(f"/api/v1/admin/projects/{acme.project_id}/members", json=payload)

    with Session(migrated_engine) as check:
        user = check.execute(
            select(User).where(User.email == payload["email"])
        ).scalar_one()
    assert user.is_internal is True


def test_an_invitation_is_audited_without_the_email(
    world, authenticated, keycloak, migrated_engine: Engine
) -> None:
    acme = world["acme"]
    authenticated(acme.admin)
    payload = _invitation(uuid.uuid4().hex[:6])

    client.post(f"/api/v1/admin/projects/{acme.project_id}/members", json=payload)

    with Session(migrated_engine) as check:
        entry = check.execute(
            select(AuditLog).where(
                AuditLog.organization_id == acme.organization_id,
                AuditLog.action == "membership.invited",
            )
        ).scalar_one()
    assert entry.actor_user_id is not None
    assert payload["email"] not in repr(entry.data)


def test_a_malformed_email_never_reaches_the_identity_provider(
    world, authenticated, keycloak
) -> None:
    acme = world["acme"]
    authenticated(acme.admin)

    response = client.post(
        f"/api/v1/admin/projects/{acme.project_id}/members",
        json={"email": "sem-arroba", "full_name": "Alguém", "role": "client_member"},
    )

    assert response.status_code == 422
    assert keycloak.created == []


# --- revogação -------------------------------------------------------------


def test_revoking_removes_the_access_and_keeps_the_person(
    world, authenticated, migrated_engine: Engine
) -> None:
    acme = world["acme"]
    authenticated(acme.admin)

    response = client.delete(
        f"/api/v1/admin/projects/{acme.project_id}/members/{acme.client_membership_id}"
    )

    assert response.status_code == 204
    with Session(migrated_engine) as check:
        assert check.get(Membership, acme.client_membership_id) is None
        assert (
            check.execute(
                select(User).where(User.email == acme.client_actor.email)
            ).scalar_one_or_none()
            is not None
        ), "a conta continua existindo — some o acesso, não a pessoa"


def test_an_administrator_cannot_revoke_their_own_access(
    world, authenticated, migrated_engine: Engine
) -> None:
    """Sem isto, um clique deixaria o administrador fora da própria tela."""
    acme = world["acme"]
    authenticated(acme.admin)
    # Vínculo direto no projeto, além do org-wide, para haver o que revogar.
    with Session(migrated_engine) as arrange:
        own = Membership(
            organization_id=acme.organization_id,
            project_id=acme.project_id,
            user_id=arrange.execute(
                select(User.id).where(User.email == acme.admin.email)
            ).scalar_one(),
            role=MemberRole.internal_admin,
        )
        arrange.add(own)
        arrange.commit()
        own_id = own.id

    response = client.delete(
        f"/api/v1/admin/projects/{acme.project_id}/members/{own_id}"
    )

    assert response.status_code == 409


# --- chaves dos agentes e premissas financeiras (Fase 3, ADR 0013) ---------


def test_no_client_member_reaches_the_results_administration(
    world, authenticated, agent_pepper
) -> None:
    """Negativo de permissão para cada rota nova (AGENTS.md #6)."""
    acme = world["acme"]
    authenticated(acme.client_actor)
    base = f"/api/v1/admin/projects/{acme.project_id}"

    responses = [
        client.get(f"{base}/keys"),
        client.post(f"{base}/keys", json={"name": "agente"}),
        client.post(f"{base}/keys/{uuid.uuid4()}/rotate"),
        client.delete(f"{base}/keys/{uuid.uuid4()}"),
        client.get(f"{base}/assumptions"),
        client.post(
            f"{base}/assumptions",
            json={
                "effective_from": "2026-01-01",
                "hourly_rate_cents": 10_000,
                "monthly_investment_cents": 300_000,
            },
        ),
    ]

    assert {response.status_code for response in responses} == {404}


def test_an_administrator_cannot_mint_a_key_for_another_tenant(
    world, authenticated, agent_pepper
) -> None:
    authenticated(world["acme"].admin)
    globex = world["globex"]

    response = client.post(
        f"/api/v1/admin/projects/{globex.project_id}/keys", json={"name": "agente"}
    )

    assert response.status_code == 404


def test_the_plaintext_key_is_returned_once_and_never_stored(
    world, authenticated, agent_pepper, migrated_engine: Engine
) -> None:
    from portal_api.models import AgentApiKey

    acme = world["acme"]
    authenticated(acme.admin)

    created = client.post(
        f"/api/v1/admin/projects/{acme.project_id}/keys",
        json={"name": "Agente Financeiro"},
    )
    listed = client.get(f"/api/v1/admin/projects/{acme.project_id}/keys")

    assert created.status_code == 201
    key = created.json()["key"]
    assert key.startswith("plk_")

    # A listagem devolve o prefixo e mais nada — não há caminho de volta ao
    # segredo, nem pela API nem pelo banco.
    entry = next(
        item for item in listed.json() if item["key_id"] == created.json()["key_id"]
    )
    assert "key" not in entry
    assert entry["key_prefix"] == key[:12]

    with Session(migrated_engine) as session:
        record = session.get(AgentApiKey, uuid.UUID(created.json()["key_id"]))
        assert record.key_hash != key
        assert key not in record.key_hash


def test_a_minted_key_actually_authenticates_the_ingestion(
    world, authenticated, agent_pepper
) -> None:
    """A ponta a ponta que interessa: o que a tela cria é o que o agente usa."""
    acme = world["acme"]
    authenticated(acme.admin)
    key = client.post(
        f"/api/v1/admin/projects/{acme.project_id}/keys", json={"name": "agente"}
    ).json()["key"]

    ingested = client.post(
        "/api/v1/agent-events",
        json={
            "event_id": str(uuid.uuid4()),
            "project_id": str(acme.project_id),
            "occurred_at": "2026-08-03T10:00:00Z",
            "agent_key": "finance-agent",
            "time_saved_seconds": 600,
            "avoided_cost_cents": 100,
            "run_reference": "run-1",
        },
        headers={"X-Agent-Key": key},
    )

    assert ingested.status_code == 202


def test_rotating_replaces_the_key_and_keeps_the_trail(
    world, authenticated, agent_pepper
) -> None:
    acme = world["acme"]
    authenticated(acme.admin)
    base = f"/api/v1/admin/projects/{acme.project_id}"
    original = client.post(f"{base}/keys", json={"name": "agente"}).json()

    rotated = client.post(f"{base}/keys/{original['key_id']}/rotate")

    assert rotated.status_code == 201
    assert rotated.json()["key"] != original["key"]
    # A sucessora aponta para a antecessora: sem isso, "de onde veio esta chave"
    # ficaria sem resposta.
    assert rotated.json()["rotated_from_id"] == original["key_id"]

    listing = {item["key_id"]: item for item in client.get(f"{base}/keys").json()}
    assert listing[original["key_id"]]["revoked_at"] is not None
    assert listing[rotated.json()["key_id"]]["revoked_at"] is None


def test_a_revoked_key_stops_working_immediately(
    world, authenticated, agent_pepper
) -> None:
    acme = world["acme"]
    authenticated(acme.admin)
    base = f"/api/v1/admin/projects/{acme.project_id}"
    created = client.post(f"{base}/keys", json={"name": "agente"}).json()

    def _ingest():
        return client.post(
            "/api/v1/agent-events",
            json={
                "event_id": str(uuid.uuid4()),
                "project_id": str(acme.project_id),
                "occurred_at": "2026-08-03T10:00:00Z",
                "agent_key": "finance-agent",
                "time_saved_seconds": 60,
                "avoided_cost_cents": 0,
                "run_reference": "run-x",
            },
            headers={"X-Agent-Key": created["key"]},
        )

    assert _ingest().status_code == 202
    assert client.delete(f"{base}/keys/{created['key_id']}").status_code == 204
    assert _ingest().status_code == 401


def test_the_key_audit_never_carries_the_secret(
    world, authenticated, agent_pepper, migrated_engine: Engine
) -> None:
    acme = world["acme"]
    authenticated(acme.admin)

    created = client.post(
        f"/api/v1/admin/projects/{acme.project_id}/keys", json={"name": "agente"}
    ).json()

    with Session(migrated_engine) as session:
        entry = session.execute(
            select(AuditLog).where(
                AuditLog.action == "agent_key.created",
                AuditLog.entity_id == uuid.UUID(created["key_id"]),
            )
        ).scalars().one()
    # `trace_id` entrou em toda linha de auditoria na ADR 0018; o resto do
    # conteúdo é o que este teste guarda, e a asserção continua exaustiva —
    # nenhum campo além destes dois, e o segredo em nenhum deles.
    assert entry.data == {
        "key_prefix": created["key_prefix"],
        "trace_id": entry.data["trace_id"],
    }
    assert entry.data["trace_id"]
    assert created["key"] not in f"{entry.data}"


def test_a_new_assumption_closes_the_current_one(
    world, authenticated, agent_pepper
) -> None:
    """Premissa não se edita no lugar: fecha uma, abre outra."""
    acme = world["acme"]
    authenticated(acme.admin)
    base = f"/api/v1/admin/projects/{acme.project_id}/assumptions"

    first = client.post(
        base,
        json={
            "effective_from": "2026-01-01",
            "hourly_rate_cents": 10_000,
            "monthly_investment_cents": 300_000,
        },
    )
    second = client.post(
        base,
        json={
            "effective_from": "2026-03-01",
            "hourly_rate_cents": 12_000,
            "monthly_investment_cents": 300_000,
        },
    )

    assert [first.status_code, second.status_code] == [201, 201]
    history = {item["assumption_id"]: item for item in client.get(base).json()}
    # A anterior foi fechada exatamente onde a nova começa: sem buraco e sem
    # sobreposição, que é o que torna o histórico explicável.
    assert history[first.json()["assumption_id"]]["effective_to"] == "2026-03-01"
    assert history[second.json()["assumption_id"]]["effective_to"] is None


def test_an_assumption_cannot_retroact_over_the_open_one(
    world, authenticated, agent_pepper
) -> None:
    """Retroagir reescreveria um número já mostrado ao cliente."""
    acme = world["acme"]
    authenticated(acme.admin)
    base = f"/api/v1/admin/projects/{acme.project_id}/assumptions"
    client.post(
        base,
        json={
            "effective_from": "2026-06-01",
            "hourly_rate_cents": 10_000,
            "monthly_investment_cents": 300_000,
        },
    )

    response = client.post(
        base,
        json={
            "effective_from": "2026-05-01",
            "hourly_rate_cents": 99_000,
            "monthly_investment_cents": 300_000,
        },
    )

    assert response.status_code == 409


# --- conhecimento do projeto (Fase 4, ADR 0014) ---------------------------
# O upload é a única porta pela qual um arquivo entra no portal, e ela é de
# administração: o cliente pergunta, não envia.


def _file(name: str = "contrato.txt", content: bytes = b"O suporte dura 12 meses.", mime: str = "text/plain"):
    return {"file": (name, content, mime)}


def test_no_client_member_reaches_the_knowledge_administration(
    world, authenticated, fake_storage
) -> None:
    """Negativo de permissão para cada rota nova (AGENTS.md #6)."""
    acme = world["acme"]
    authenticated(acme.client_actor)
    base = f"/api/v1/admin/projects/{acme.project_id}/documents"

    responses = [
        client.get(base),
        client.post(base, files=_file(), data={"title": "Contrato"}),
        client.delete(f"{base}/{uuid.uuid4()}"),
    ]

    assert {response.status_code for response in responses} == {404}
    assert fake_storage == {}, "não deve nem chegar ao storage"


def test_an_administrator_cannot_upload_into_another_tenant(
    world, authenticated, fake_storage
) -> None:
    authenticated(world["acme"].admin)
    globex = world["globex"]

    response = client.post(
        f"/api/v1/admin/projects/{globex.project_id}/documents",
        files=_file(),
        data={"title": "Contrato"},
    )

    assert response.status_code == 404
    assert fake_storage == {}


def test_an_upload_is_stored_pending_and_queued_for_indexing(
    world, authenticated, fake_storage, queued_ingestions, migrated_engine
) -> None:
    acme = world["acme"]
    authenticated(acme.admin)
    base = f"/api/v1/admin/projects/{acme.project_id}/documents"

    created = client.post(base, files=_file(), data={"title": "Contrato de suporte"})

    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "Contrato de suporte"
    assert body["ingest_state"] == "pending"
    assert body["chunk_count"] == 0
    assert body["byte_size"] == len(b"O suporte dura 12 meses.")
    # A chave do objeto carrega o tenant inteiro.
    (key,) = fake_storage
    assert key.startswith(f"org/{acme.organization_id}/project/{acme.project_id}/document/")
    assert queued_ingestions == [body["document_id"]]

    listed = client.get(base).json()
    assert [item["document_id"] for item in listed] == [body["document_id"]]

    _cleanup_documents(migrated_engine, acme.project_id)


def test_the_markdown_the_browser_calls_octet_stream_is_still_accepted(
    world, authenticated, fake_storage, queued_ingestions, migrated_engine
) -> None:
    """O tipo é conferido no servidor; o palpite pelo nome é a segunda tentativa."""
    acme = world["acme"]
    authenticated(acme.admin)

    created = client.post(
        f"/api/v1/admin/projects/{acme.project_id}/documents",
        files={"file": ("notas.md", b"# Notas\n\nO escopo fechou.", "application/octet-stream")},
        data={"title": ""},
    )

    assert created.status_code == 201
    assert created.json()["mime_type"] == "text/markdown"
    # Sem título informado, o nome do arquivo serve de rótulo.
    assert created.json()["title"] == "notas.md"

    _cleanup_documents(migrated_engine, acme.project_id)


def test_a_format_the_portal_cannot_read_never_reaches_the_storage(
    world, authenticated, fake_storage, queued_ingestions
) -> None:
    acme = world["acme"]
    authenticated(acme.admin)

    response = client.post(
        f"/api/v1/admin/projects/{acme.project_id}/documents",
        files={"file": ("planilha.zip", b"PK\x03\x04", "application/zip")},
    )

    assert response.status_code == 415
    assert fake_storage == {}
    assert queued_ingestions == []


def test_a_file_over_the_cap_is_refused_before_anything_is_written(
    world, authenticated, fake_storage, monkeypatch
) -> None:
    from portal_api.config import get_settings

    monkeypatch.setattr(get_settings(), "document_max_bytes", 32)
    acme = world["acme"]
    authenticated(acme.admin)

    response = client.post(
        f"/api/v1/admin/projects/{acme.project_id}/documents",
        files=_file(content=b"x" * 64),
    )

    assert response.status_code == 413
    assert fake_storage == {}


def test_an_empty_file_is_refused(world, authenticated, fake_storage) -> None:
    acme = world["acme"]
    authenticated(acme.admin)

    response = client.post(
        f"/api/v1/admin/projects/{acme.project_id}/documents", files=_file(content=b"")
    )

    assert response.status_code == 422
    assert fake_storage == {}


def test_deleting_removes_the_row_the_index_and_the_object(
    world, authenticated, fake_storage, queued_ingestions, migrated_engine
) -> None:
    from portal_api import worker
    from portal_api.models import Document, DocumentChunk

    acme = world["acme"]
    authenticated(acme.admin)
    base = f"/api/v1/admin/projects/{acme.project_id}/documents"
    document_id = client.post(base, files=_file(), data={"title": "Contrato"}).json()["document_id"]
    worker.scan_document(document_id)
    worker.ingest_document(document_id)

    assert client.get(base).json()[0]["chunk_count"] > 0

    removed = client.delete(f"{base}/{document_id}")

    assert removed.status_code == 204
    assert client.get(base).json() == []
    assert fake_storage == {}
    with Session(migrated_engine) as session:
        assert session.get(Document, uuid.UUID(document_id)) is None
        assert (
            session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == uuid.UUID(document_id)
                )
            ).first()
            is None
        )


def test_a_document_mirrored_from_biahflow_is_not_deletable_here(
    world, authenticated, fake_storage, migrated_engine
) -> None:
    """Ele volta no próximo sync; prometer a remoção seria mentir (ADR 0006)."""
    from portal_api.models import Document, DocumentOrigin, DocumentSource

    acme = world["acme"]
    with Session(migrated_engine) as session:
        mirrored = Document(
            organization_id=acme.organization_id,
            project_id=acme.project_id,
            title="Ata do Biahflow",
            source=DocumentSource.drive,
            origin=DocumentOrigin.biahflow,
        )
        session.add(mirrored)
        session.commit()
        mirrored_id = mirrored.id

    authenticated(acme.admin)
    response = client.delete(
        f"/api/v1/admin/projects/{acme.project_id}/documents/{mirrored_id}"
    )

    assert response.status_code == 404
    _cleanup_documents(migrated_engine, acme.project_id)


def test_the_upload_is_audited_without_the_content(
    world, authenticated, fake_storage, queued_ingestions, migrated_engine
) -> None:
    acme = world["acme"]
    authenticated(acme.admin)

    client.post(
        f"/api/v1/admin/projects/{acme.project_id}/documents",
        files=_file(content=b"Valor confidencial: 1.000.000"),
        data={"title": "Contrato"},
    )

    with Session(migrated_engine) as session:
        entry = session.execute(
            select(AuditLog).where(
                AuditLog.project_id == acme.project_id,
                AuditLog.action == "document.uploaded",
            )
        ).scalar_one()
        # Exaustivo de propósito (ver o comentário em `agent_key.created`): o
        # `trace_id` da ADR 0018 é o único campo novo, e nada do conteúdo do
        # arquivo entra aqui.
        assert entry.data == {
            "mime_type": "text/plain",
            "byte_size": 29,
            "trace_id": entry.data["trace_id"],
        }
        assert entry.data["trace_id"]
        assert "confidencial" not in repr(entry.data)

    _cleanup_documents(migrated_engine, acme.project_id)


def _cleanup_documents(engine: Engine, project_id: uuid.UUID) -> None:
    """As rotas comitam de verdade; o que elas deixaram sai aqui."""
    from portal_api.models import Document

    with Session(engine) as session:
        session.execute(delete(Document).where(Document.project_id == project_id))
        session.commit()


# --- Conector do Google Drive (Fase 4, ADR 0016) -------------------------------


@pytest.fixture
def drive_ready(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeDrive]:
    """Conector configurado e ligado a um Drive de mentira."""
    from portal_api import crypto
    from portal_api.config import get_settings
    from portal_api.integrations import google_drive

    settings = get_settings()
    monkeypatch.setattr(settings, "google_drive_client_id", "client-id")
    monkeypatch.setattr(settings, "google_drive_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_drive_api_base_url", "http://drive/drive/v3")
    monkeypatch.setattr(settings, "google_oauth_token_url", "http://drive/token")
    monkeypatch.setattr(settings, "drive_token_encryption_key", crypto.generate_key())

    fake = FakeDrive()
    fake.folder("folder-autorizada", "Contratos")
    transport = fake.client()
    monkeypatch.setattr(google_drive, "session_client", lambda: transport)
    yield fake
    transport.close()


def _connect_drive(project_id: uuid.UUID) -> None:
    """Percorre o fluxo real: pede a URL, extrai o `state`, devolve o callback."""
    import httpx

    started = client.post(f"/api/v1/admin/projects/{project_id}/drive/authorize-url")
    assert started.status_code == 201
    state = httpx.URL(started.json()["authorize_url"]).params["state"]
    finished = client.post(
        "/api/v1/admin/drive/callback", json={"code": "código", "state": state}
    )
    assert finished.status_code == 200, finished.text


def test_no_client_member_reaches_the_drive_connector(
    world, authenticated, drive_ready
) -> None:
    """Negativo de permissão para cada rota nova (AGENTS.md #6)."""
    acme = world["acme"]
    authenticated(acme.client_actor)
    base = f"/api/v1/admin/projects/{acme.project_id}/drive"

    responses = [
        client.get(base),
        client.post(f"{base}/authorize-url"),
        client.get(f"{base}/folders"),
        client.put(f"{base}/folder", json={"folder_id": "folder-autorizada"}),
        client.post(f"{base}/sync"),
        client.delete(base),
    ]

    assert {response.status_code for response in responses} == {404}


def test_an_administrator_cannot_connect_a_drive_in_another_tenant(
    world, authenticated, drive_ready
) -> None:
    authenticated(world["acme"].admin)
    globex = world["globex"]

    response = client.post(
        f"/api/v1/admin/projects/{globex.project_id}/drive/authorize-url"
    )

    assert response.status_code == 404


def test_a_project_without_a_drive_answers_disconnected_and_not_404(
    world, authenticated, drive_ready
) -> None:
    """404 aqui faria a tela confundir "você não administra" com "ninguém conectou"."""
    acme = world["acme"]
    authenticated(acme.admin)

    response = client.get(f"/api/v1/admin/projects/{acme.project_id}/drive")

    assert response.status_code == 200
    assert response.json()["connected"] is False


def test_connecting_stores_the_account_and_never_returns_the_token(
    world, authenticated, drive_ready, migrated_engine
) -> None:
    """O segredo não sai da API — diferente da chave de agente, que atravessa uma vez."""
    acme = world["acme"]
    authenticated(acme.admin)

    _connect_drive(acme.project_id)
    response = client.get(f"/api/v1/admin/projects/{acme.project_id}/drive")

    body = response.json()
    assert body["connected"] is True
    assert body["google_account_email"] == "interno@portallabs.local"
    assert "refresh" not in response.text.lower()
    assert "refresh-token-do-google" not in response.text

    from portal_api.models import ProjectDriveConnection

    with Session(migrated_engine) as session:
        record = session.execute(
            select(ProjectDriveConnection).where(
                ProjectDriveConnection.project_id == acme.project_id
            )
        ).scalar_one()
        # Guardado, mas selado: o valor em claro não existe no banco.
        assert record.refresh_token_sealed
        assert "refresh-token-do-google" not in record.refresh_token_sealed


def test_a_replayed_state_finds_nothing(world, authenticated, drive_ready) -> None:
    """Uso único: quem chega em segundo não acha mais lastro nenhum."""
    import httpx

    acme = world["acme"]
    authenticated(acme.admin)
    started = client.post(f"/api/v1/admin/projects/{acme.project_id}/drive/authorize-url")
    state = httpx.URL(started.json()["authorize_url"]).params["state"]

    first = client.post("/api/v1/admin/drive/callback", json={"code": "c", "state": state})
    second = client.post("/api/v1/admin/drive/callback", json={"code": "c", "state": state})

    assert first.status_code == 200
    assert second.status_code == 404


def test_an_expired_state_is_refused(world, authenticated, drive_ready, monkeypatch) -> None:
    import httpx

    from portal_api.config import get_settings

    acme = world["acme"]
    authenticated(acme.admin)
    monkeypatch.setattr(get_settings(), "drive_oauth_state_ttl_seconds", -1)
    started = client.post(f"/api/v1/admin/projects/{acme.project_id}/drive/authorize-url")
    state = httpx.URL(started.json()["authorize_url"]).params["state"]

    response = client.post(
        "/api/v1/admin/drive/callback", json={"code": "c", "state": state}
    )

    assert response.status_code == 404


def test_an_unknown_state_opens_nothing(world, authenticated, drive_ready) -> None:
    authenticated(world["acme"].admin)

    response = client.post(
        "/api/v1/admin/drive/callback", json={"code": "c", "state": "inventado"}
    )

    assert response.status_code == 404


def test_a_state_minted_for_someone_else_is_refused(
    world, authenticated, drive_ready
) -> None:
    """O `state` prova que é o mesmo fluxo; o dono prova que é a mesma pessoa."""
    import httpx

    acme = world["acme"]
    authenticated(acme.admin)
    started = client.post(f"/api/v1/admin/projects/{acme.project_id}/drive/authorize-url")
    state = httpx.URL(started.json()["authorize_url"]).params["state"]

    authenticated(acme.second_admin)
    response = client.post(
        "/api/v1/admin/drive/callback", json={"code": "c", "state": state}
    )

    assert response.status_code == 404


def test_a_broader_granted_scope_is_refused_and_nothing_is_stored(
    world, authenticated, drive_ready
) -> None:
    import httpx

    acme = world["acme"]
    authenticated(acme.admin)
    drive_ready.granted_scope = "https://www.googleapis.com/auth/drive"
    started = client.post(f"/api/v1/admin/projects/{acme.project_id}/drive/authorize-url")
    state = httpx.URL(started.json()["authorize_url"]).params["state"]

    response = client.post(
        "/api/v1/admin/drive/callback", json={"code": "c", "state": state}
    )

    assert response.status_code == 400
    assert client.get(f"/api/v1/admin/projects/{acme.project_id}/drive").json()["connected"] is False


def test_a_consent_without_a_refresh_token_is_refused(
    world, authenticated, drive_ready
) -> None:
    """Sem `prompt=consent` o Google devolve isto, e a conexão nasceria inutilizável."""
    import httpx

    acme = world["acme"]
    authenticated(acme.admin)
    drive_ready.refresh_token = None
    started = client.post(f"/api/v1/admin/projects/{acme.project_id}/drive/authorize-url")
    state = httpx.URL(started.json()["authorize_url"]).params["state"]

    response = client.post(
        "/api/v1/admin/drive/callback", json={"code": "c", "state": state}
    )

    assert response.status_code == 400


def test_connecting_without_an_encryption_key_answers_503(
    world, authenticated, drive_ready, monkeypatch
) -> None:
    """Falha antes de mandar a pessoa para a tela do Google."""
    from portal_api.config import get_settings

    acme = world["acme"]
    authenticated(acme.admin)
    monkeypatch.setattr(get_settings(), "drive_token_encryption_key", "")
    monkeypatch.setattr(get_settings(), "drive_token_encryption_key_previous", "")

    response = client.post(f"/api/v1/admin/projects/{acme.project_id}/drive/authorize-url")

    assert response.status_code == 503


def test_choosing_a_file_instead_of_a_folder_is_refused(
    world, authenticated, drive_ready
) -> None:
    acme = world["acme"]
    authenticated(acme.admin)
    _connect_drive(acme.project_id)
    drive_ready.add(
        FakeFile(id="um-arquivo", name="a.txt", mime_type="text/plain", parents=["folder-autorizada"])
    )

    response = client.put(
        f"/api/v1/admin/projects/{acme.project_id}/drive/folder",
        json={"folder_id": "um-arquivo"},
    )

    assert response.status_code == 502


def test_sync_now_queues_and_is_audited(
    world, authenticated, drive_ready, migrated_engine, monkeypatch
) -> None:
    from portal_api import worker

    acme = world["acme"]
    authenticated(acme.admin)
    _connect_drive(acme.project_id)
    client.put(
        f"/api/v1/admin/projects/{acme.project_id}/drive/folder",
        json={"folder_id": "folder-autorizada"},
    )
    queued: list[str] = []
    monkeypatch.setattr(worker, "queue_drive_sync", queued.append)

    response = client.post(f"/api/v1/admin/projects/{acme.project_id}/drive/sync")

    assert response.status_code == 202
    assert len(queued) == 1
    with Session(migrated_engine) as session:
        actions = set(
            session.execute(
                select(AuditLog.action).where(AuditLog.project_id == acme.project_id)
            ).scalars()
        )
    assert {"drive.authorize_started", "drive.connected", "drive.folder_changed", "drive.sync_requested"} <= actions


def test_the_audit_trail_never_carries_the_token(
    world, authenticated, drive_ready, migrated_engine
) -> None:
    acme = world["acme"]
    authenticated(acme.admin)
    _connect_drive(acme.project_id)

    with Session(migrated_engine) as session:
        entries = list(
            session.execute(
                select(AuditLog).where(AuditLog.project_id == acme.project_id)
            ).scalars()
        )
    assert entries
    assert all("refresh-token-do-google" not in str(entry.data) for entry in entries)


def test_disconnecting_revokes_and_keeps_the_trail(
    world, authenticated, drive_ready, migrated_engine
) -> None:
    """O segredo some; a linha fica — o rastro de que este projeto leu aquele Drive."""
    from portal_api.models import ProjectDriveConnection

    acme = world["acme"]
    authenticated(acme.admin)
    _connect_drive(acme.project_id)

    response = client.delete(f"/api/v1/admin/projects/{acme.project_id}/drive")

    assert response.status_code == 204
    with Session(migrated_engine) as session:
        record = session.execute(
            select(ProjectDriveConnection).where(
                ProjectDriveConnection.project_id == acme.project_id
            )
        ).scalar_one()
        assert record.refresh_token_sealed is None
        assert record.enabled is False
        assert record.disconnected_at is not None
        assert record.connected_at is not None


# --- o beco sem saída do expurgo (Fase 6, ADR 0028) -------------------------


def test_a_failed_erasure_lets_the_screen_ask_again(
    world, authenticated, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A asserção que liga a ADR 0028 à tela da ADR 0027.

    Esta rota devolve o pedido existente em vez de enfileirar um segundo, e o
    filtro é `pending | running`. Antes desta fatia uma falha do banco deixava a
    linha em `running` para sempre — nada a reivindicava de volta —, então a
    tela respondia "já existe um pedido em execução" **para sempre** e o tenant
    ficava permanentemente inapagável pela interface. Uma obrigação contratual
    virava um beco sem saída por causa de um `except` que não existia.
    """
    from portal_api import worker
    from portal_api.models import DataErasureRequest, ErasureState

    acme = world["acme"]
    authenticated(acme.admin)
    with Session(migrated_engine) as session:
        slug = session.get(Organization, acme.organization_id).slug

    body = {"reason": "encerramento de contrato", "confirm_slug": slug}
    first = client.post(
        f"/api/v1/admin/organizations/{acme.organization_id}/erasure", json=body
    )
    assert first.status_code == 202
    first_id = first.json()["request_id"]

    monkeypatch.setattr(
        worker.retention,
        "run_erasure",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("deadlock")),
    )
    assert worker._run_erasure(uuid.UUID(first_id)) is False

    second = client.post(
        f"/api/v1/admin/organizations/{acme.organization_id}/erasure", json=body
    )

    assert second.status_code == 202
    # Pedido **novo**, e não o anterior devolvido: é a diferença entre poder
    # tentar de novo e ficar preso.
    assert second.json()["request_id"] != first_id
    with Session(migrated_engine) as session:
        # E o histórico do que falhou fica, com o motivo — a tela o mostra em
        # vermelho, e sem ele "o que aconteceu com aquela organização" volta a
        # não ter resposta (ADR 0017).
        failed = session.get(DataErasureRequest, uuid.UUID(first_id))
        assert failed is not None
        assert failed.state is ErasureState.failed
        assert "deadlock" in (failed.error or "")
