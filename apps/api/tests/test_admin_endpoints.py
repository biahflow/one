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
        session.add_all([admin_user, client_user])
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
        session.add_all([admin_membership, client_membership])
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
    assert set(by_email) == {acme.admin.email, acme.client_actor.email}
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
    assert entry.data == {"key_prefix": created["key_prefix"]}
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
