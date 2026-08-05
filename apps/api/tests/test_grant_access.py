"""O bootstrap do primeiro vínculo de uma organização (Fase 6, ADR 0025).

O teste que dá sentido a todos os outros é
``test_after_the_bootstrap_the_admin_screen_answers``: conceder uma linha em
``membership`` só vale alguma coisa se, depois dela, a pessoa alcançar `/admin`
— que é o caminho que a ADR 0011 fechou e que este módulo existe para
inaugurar. Os demais fixam que ele **não** vira uma porta paralela àquela tela.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from portal_api.auth import bearer_principal
from portal_api.grant_access import BOOTSTRAP_ROLES, GrantRefused, grant, main
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
class Orphan:
    """Uma organização como o sync do Biahflow a deixa: com projeto e sem ninguém."""

    organization_id: uuid.UUID
    organization_slug: str
    project_id: uuid.UUID
    email: str
    subject: str
    user_id: uuid.UUID


@pytest.fixture
def orphan(migrated_engine: Engine) -> Iterator[Orphan]:
    tag = uuid.uuid4().hex[:8]
    slug = f"biahflow-client-{tag}"
    with Session(migrated_engine) as session:
        organization = Organization(name="Igreja Cartas Vivas", slug=slug)
        session.add(organization)
        session.flush()
        project = Project(
            organization_id=organization.id,
            name="Teste",
            slug=f"biahflow-{tag}",
            status=ProjectStatus.discovery,
            completion_percent=0,
        )
        session.add(project)
        # A pessoa existe (já entrou no portal alguma vez) e **não** tem vínculo
        # nesta organização — é o estado real depois do primeiro sync.
        person = User(
            email=f"helena-{tag}@portallabs.com.br",
            full_name="Helena Dias",
            external_subject=f"sub-bootstrap-{tag}",
            is_internal=True,
        )
        session.add(person)
        session.flush()
        built = Orphan(
            organization.id, slug, project.id, person.email,
            person.external_subject or "", person.id,
        )
        session.commit()

    yield built

    with Session(migrated_engine) as session:
        session.execute(delete(Organization).where(Organization.id == built.organization_id))
        session.execute(delete(User).where(User.id == built.user_id))
        session.commit()


@pytest.fixture
def authenticated() -> Iterator[Callable[[Orphan], None]]:
    def _as(who: Orphan) -> None:
        app.dependency_overrides[bearer_principal] = lambda: Principal(
            subject=who.subject,
            email=who.email,
            full_name="Helena Dias",
            realm_roles=frozenset({"internal_admin"}),
        )

    yield _as
    app.dependency_overrides.clear()


def _memberships(session: Session, organization_id: uuid.UUID) -> list[Membership]:
    return list(
        session.execute(
            select(Membership).where(Membership.organization_id == organization_id)
        ).scalars()
    )


# --- o que ele faz ----------------------------------------------------------


def test_it_grants_the_first_administrator_of_an_orphan_organization(
    orphan: Orphan, migrated_engine: Engine
) -> None:
    with Session(migrated_engine) as session:
        assert _memberships(session, orphan.organization_id) == []

        result = grant(
            session,
            email=orphan.email,
            organization_slug=orphan.organization_slug,
            role=MemberRole.internal_admin,
        )
        session.commit()

        assert result.created is True
        rows = _memberships(session, orphan.organization_id)
        assert len(rows) == 1
        # De escopo organizacional: o sync cria um projeto por projeto do
        # Biahflow, e um vínculo por projeto obrigaria a repetir o bootstrap.
        assert rows[0].project_id is None
        assert rows[0].role == MemberRole.internal_admin


def test_after_the_bootstrap_the_admin_screen_answers(
    orphan: Orphan, authenticated, migrated_engine: Engine
) -> None:
    """A asserção que prova que o bootstrap serviu para alguma coisa.

    Antes: 404, porque `require_project(..., ADMIN_ONLY)` não encontra papel.
    Depois: 200, e daí em diante tudo passa pela tela — que é o ponto.
    """
    authenticated(orphan)
    antes = client.get(f"/api/v1/admin/projects/{orphan.project_id}/members")
    assert antes.status_code == 404

    with Session(migrated_engine) as session:
        grant(
            session,
            email=orphan.email,
            organization_slug=orphan.organization_slug,
            role=MemberRole.internal_admin,
        )
        session.commit()

    depois = client.get(f"/api/v1/admin/projects/{orphan.project_id}/members")
    assert depois.status_code == 200


def test_running_twice_does_not_duplicate_the_membership(
    orphan: Orphan, migrated_engine: Engine
) -> None:
    """Idempotente como o seed — e continua idempotente **depois** de a
    organização ter admin, senão repetir o comando viraria a recusa."""
    with Session(migrated_engine) as session:
        primeiro = grant(
            session, email=orphan.email,
            organization_slug=orphan.organization_slug, role=MemberRole.internal_admin,
        )
        session.commit()
        segundo = grant(
            session, email=orphan.email,
            organization_slug=orphan.organization_slug, role=MemberRole.internal_admin,
        )
        session.commit()

        assert primeiro.created is True
        assert segundo.created is False
        assert len(_memberships(session, orphan.organization_id)) == 1


def test_the_grant_is_written_to_the_audit_log(
    orphan: Orphan, migrated_engine: Engine
) -> None:
    """O vínculo mais poderoso do sistema não pode ser o único sem rastro."""
    with Session(migrated_engine) as session:
        grant(
            session, email=orphan.email,
            organization_slug=orphan.organization_slug, role=MemberRole.internal_admin,
        )
        session.commit()

        entry = session.execute(
            select(AuditLog).where(
                AuditLog.organization_id == orphan.organization_id,
                AuditLog.action == "membership.bootstrapped",
            )
        ).scalar_one()
        assert entry.data["via"] == "grant_access"
        assert entry.data["role"] == "internal_admin"


# --- o que ele recusa -------------------------------------------------------


def test_it_refuses_when_the_organization_already_has_an_administrator(
    orphan: Orphan, migrated_engine: Engine
) -> None:
    """A recusa que o mantém sendo bootstrap.

    Com um admin no lugar, existe alguém que alcança `/admin` — auditável e com
    tela. Um CLI que continua servindo depois de desnecessário vira o caminho
    preferido por conveniência, e a ADR 0011 passa a valer só no papel.
    """
    with Session(migrated_engine) as session:
        outra_pessoa = User(
            email=f"outro-{uuid.uuid4().hex[:8]}@portallabs.com.br",
            full_name="Outro Interno",
            external_subject=f"sub-outro-{uuid.uuid4().hex[:8]}",
            is_internal=True,
        )
        session.add(outra_pessoa)
        session.flush()
        session.add(
            Membership(
                organization_id=orphan.organization_id,
                project_id=None,
                user_id=outra_pessoa.id,
                role=MemberRole.internal_admin,
            )
        )
        session.commit()

        with pytest.raises(GrantRefused, match="já tem internal_admin"):
            grant(
                session, email=orphan.email,
                organization_slug=orphan.organization_slug, role=MemberRole.internal_admin,
            )
        session.rollback()

        # E nada foi criado para quem pediu.
        assert not any(m.user_id == orphan.user_id for m in _memberships(session, orphan.organization_id))

        session.execute(delete(User).where(User.id == outra_pessoa.id))
        session.commit()


def test_it_refuses_an_unknown_email_and_an_unknown_organization(
    orphan: Orphan, migrated_engine: Engine
) -> None:
    with Session(migrated_engine) as session:
        with pytest.raises(GrantRefused, match="não tem linha em `user`"):
            grant(
                session, email="ninguem@exemplo.com",
                organization_slug=orphan.organization_slug, role=MemberRole.internal_admin,
            )
        with pytest.raises(GrantRefused, match="não existe"):
            grant(
                session, email=orphan.email,
                organization_slug="organizacao-que-nao-existe", role=MemberRole.internal_admin,
            )
        session.rollback()
        assert _memberships(session, orphan.organization_id) == []


def test_it_refuses_to_bootstrap_a_client(orphan: Orphan, migrated_engine: Engine) -> None:
    """Cliente entra por convite, que cria a conta no realm e manda o e-mail.

    Um vínculo criado aqui seria acesso para alguém que não consegue entrar.
    """
    assert MemberRole.client_member not in BOOTSTRAP_ROLES
    with Session(migrated_engine) as session:
        with pytest.raises(GrantRefused, match="não é de bootstrap"):
            grant(
                session, email=orphan.email,
                organization_slug=orphan.organization_slug, role=MemberRole.client_member,
            )


def test_the_cli_exits_nonzero_when_it_refuses(orphan: Orphan) -> None:
    """Costuma rodar dentro de um script de implantação, onde um erro silencioso
    viraria "achei que tinha concedido"."""
    assert main(
        ["--email", "ninguem@exemplo.com", "--organization", orphan.organization_slug]
    ) == 1
    assert main(["--email", orphan.email, "--organization", orphan.organization_slug]) == 0
