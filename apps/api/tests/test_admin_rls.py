"""Isolamento do caminho de administração, no nível do banco (ADR 0011).

Roda no papel `portal_admin` com `select()` cru e sem repositório, pelo mesmo
motivo de `test_rls_isolation.py`: o ponto é provar que a barreira existe
*abaixo* da camada de aplicação. Se a autorização do endpoint sumisse amanhã,
estes testes ainda deveriam passar.

Dois invariantes valem mais que o resto:

* antes de `portal.admin_organization_id`, um administrador enxerga apenas os
  próprios vínculos — é nessa janela que o endpoint verifica o papel dele, e é
  isso que impede a verificação de ser circular;
* o papel de requisição (`portal_app`) **não** pode escrever `membership`. Se
  ganhar esse privilégio, a credencial separada virou decoração.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from portal_api.models import (
    MemberRole,
    Membership,
    Organization,
    Project,
    ProjectStatus,
    User,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Tenant:
    organization_id: uuid.UUID
    project_id: uuid.UUID
    admin_user_id: uuid.UUID
    admin_subject: str
    client_user_id: uuid.UUID
    client_subject: str
    client_membership_id: uuid.UUID


@dataclass(frozen=True)
class World:
    acme: Tenant
    globex: Tenant
    #: Alguém do realm que ainda não tem linha em `user` — o convidado.
    invitee_subject: str


@pytest.fixture
def world(migrated_engine: Engine) -> Iterator[World]:
    """Dois tenants completos, escritos pelo papel de sistema e **commitados**.

    Sessão própria e não o fixture `db_session`: aquele vive dentro de uma
    transação revertida no teardown, e o `admin_session` responde por outra
    conexão — não enxergaria nada.
    """
    tag = uuid.uuid4().hex[:8]
    tenants: dict[str, Tenant] = {}
    db_session = Session(migrated_engine)

    for name in ("acme", "globex"):
        organization = Organization(name=name.title(), slug=f"{name}-adm-{tag}")
        db_session.add(organization)
        db_session.flush()

        project = Project(
            organization_id=organization.id,
            name=f"Projeto {name.title()}",
            slug=f"{name}-adm-project-{tag}",
            status=ProjectStatus.in_implementation,
        )
        db_session.add(project)
        db_session.flush()

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
        db_session.add_all([admin_user, client_user])
        db_session.flush()

        db_session.add(
            Membership(
                organization_id=organization.id,
                project_id=None,
                user_id=admin_user.id,
                role=MemberRole.internal_admin,
            )
        )
        client_membership = Membership(
            organization_id=organization.id,
            project_id=project.id,
            user_id=client_user.id,
            role=MemberRole.client_member,
        )
        db_session.add(client_membership)
        db_session.flush()

        tenants[name] = Tenant(
            organization_id=organization.id,
            project_id=project.id,
            admin_user_id=admin_user.id,
            admin_subject=admin_user.external_subject or "",
            client_user_id=client_user.id,
            client_subject=client_user.external_subject or "",
            client_membership_id=client_membership.id,
        )

    db_session.commit()
    yield World(
        acme=tenants["acme"], globex=tenants["globex"], invitee_subject=f"sub-convidado-{tag}"
    )

    db_session.execute(
        delete(Organization).where(
            Organization.id.in_([t.organization_id for t in tenants.values()])
        )
    )
    db_session.execute(delete(User).where(User.email.like(f"%-{tag}@%")))
    db_session.commit()
    db_session.close()


# --- a janela em que a autorização acontece -------------------------------


def test_before_the_admin_guc_an_administrator_sees_only_their_own_membership(
    world: World, admin_session: Session, bind_admin_context
) -> None:
    """É esta janela que torna a verificação do endpoint confiável.

    Com a GUC de administração ainda nula, o papel `portal_admin` enxerga o mesmo
    que qualquer usuário: os próprios vínculos. Se enxergasse mais, "eu sou
    internal_admin nesta organização?" seria uma pergunta que ele responde a si
    mesmo com privilégio.
    """
    bind_admin_context(
        subject=world.acme.admin_subject, user_id=world.acme.admin_user_id
    )

    visible = list(admin_session.execute(select(Membership.user_id)).scalars())

    assert visible == [world.acme.admin_user_id]


def test_the_admin_guc_opens_exactly_one_organization(
    world: World, admin_session: Session, bind_admin_context
) -> None:
    bind_admin_context(
        subject=world.acme.admin_subject,
        user_id=world.acme.admin_user_id,
        admin_organization_id=world.acme.organization_id,
    )

    organizations = set(
        admin_session.execute(select(Membership.organization_id)).scalars()
    )

    assert organizations == {world.acme.organization_id}
    assert world.globex.organization_id not in organizations


def test_a_membership_of_another_organization_is_invisible_even_by_id(
    world: World, admin_session: Session, bind_admin_context
) -> None:
    """Ter o UUID em mãos não ajuda — é o que preserva o 404 no endpoint."""
    bind_admin_context(
        subject=world.acme.admin_subject,
        user_id=world.acme.admin_user_id,
        admin_organization_id=world.acme.organization_id,
    )

    assert admin_session.get(Membership, world.globex.client_membership_id) is None
    assert admin_session.get(Membership, world.acme.client_membership_id) is not None


# --- escrita --------------------------------------------------------------


def test_granting_access_inside_the_administered_organization_works(
    world: World, admin_session: Session, bind_admin_context
) -> None:
    bind_admin_context(
        subject=world.acme.admin_subject,
        user_id=world.acme.admin_user_id,
        admin_organization_id=world.acme.organization_id,
    )

    admin_session.add(
        Membership(
            organization_id=world.acme.organization_id,
            project_id=world.acme.project_id,
            user_id=world.acme.admin_user_id,
            role=MemberRole.internal_admin,
        )
    )
    admin_session.flush()


def test_granting_access_in_another_organization_is_refused_by_the_policy(
    world: World, admin_session: Session, bind_admin_context
) -> None:
    """O alvo é o tenant vizinho: a policy barra antes de qualquer regra de app."""
    bind_admin_context(
        subject=world.acme.admin_subject,
        user_id=world.acme.admin_user_id,
        admin_organization_id=world.acme.organization_id,
    )

    admin_session.add(
        Membership(
            organization_id=world.globex.organization_id,
            project_id=world.globex.project_id,
            user_id=world.acme.admin_user_id,
            role=MemberRole.internal_admin,
        )
    )
    with pytest.raises(ProgrammingError):
        admin_session.flush()


def test_revoking_across_organizations_touches_nothing(
    world: World, admin_session: Session, bind_admin_context
) -> None:
    """DELETE não estoura: ele simplesmente não alcança linha nenhuma."""
    bind_admin_context(
        subject=world.acme.admin_subject,
        user_id=world.acme.admin_user_id,
        admin_organization_id=world.acme.organization_id,
    )

    result = admin_session.execute(
        delete(Membership).where(Membership.id == world.globex.client_membership_id)
    )

    assert result.rowcount == 0


# --- a linha do convidado -------------------------------------------------


def test_the_invitee_guc_opens_one_row_and_only_that_one(
    world: World, admin_session: Session, bind_admin_context
) -> None:
    """Sem esta GUC, convidar alguém que já tem conta por outra organização
    colidiria no e-mail único; com um predicado por e-mail livre, o endpoint
    viraria um diretório de todos os usuários do portal."""
    bind_admin_context(
        subject=world.acme.admin_subject,
        user_id=world.acme.admin_user_id,
        admin_organization_id=world.acme.organization_id,
        invitee_subject=world.globex.client_subject,
    )

    reachable = set(admin_session.execute(select(User.id)).scalars())

    # O cliente do outro tenant é alcançável porque é *ele* quem está sendo
    # convidado; o administrador do outro tenant, não.
    assert world.globex.client_user_id in reachable
    assert world.globex.admin_user_id not in reachable


def test_provisioning_an_invitee_requires_the_matching_subject(
    world: World, admin_session: Session, bind_admin_context
) -> None:
    bind_admin_context(
        subject=world.acme.admin_subject,
        user_id=world.acme.admin_user_id,
        admin_organization_id=world.acme.organization_id,
        invitee_subject=world.invitee_subject,
    )

    admin_session.add(
        User(
            email=f"outro-{uuid.uuid4().hex[:6]}@example.com",
            full_name="Alguém Diferente",
            external_subject="sub-nao-e-o-convidado",
        )
    )
    with pytest.raises(ProgrammingError):
        admin_session.flush()


# --- o invariante que justifica a credencial separada ---------------------


def test_the_request_credential_cannot_write_membership(app_engine: Engine) -> None:
    """Se `portal_app` ganhar escrita aqui, o quarto papel virou decoração.

    Consultado no catálogo e não por tentativa: o privilégio é o fato, e é ele
    que impede um bug de endpoint de virar concessão de acesso.
    """
    with Session(app_engine) as session:
        privileges = set(
            session.execute(
                text(
                    """
                    SELECT privilege_type
                      FROM information_schema.table_privileges
                     WHERE table_schema = 'portal'
                       AND table_name = 'membership'
                       AND grantee = 'portal_app'
                    """
                )
            ).scalars()
        )

    assert privileges == {"SELECT"}


def test_the_admin_credential_is_not_a_way_around_rls(admin_engine: Engine) -> None:
    """`portal_admin` é NOBYPASSRLS: o alcance vem da GUC, não do privilégio."""
    with Session(admin_engine) as session:
        row = session.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
        ).one()

    assert row.rolsuper is False
    assert row.rolbypassrls is False


# --- o sinal do assistente, e o que ele deliberadamente não alcança (ADR 0030)


@pytest.fixture
def recorded_turn(world: World, migrated_engine: Engine) -> Iterator[uuid.UUID]:
    """Um turno do chat na Acme, escrito pelo papel de sistema e commitado."""
    from portal_api.models import (
        Conversation,
        ConversationMessage,
        ConversationRole,
        MessageConfidence,
        MessageFeedback,
    )

    with Session(migrated_engine) as session:
        conversation = Conversation(
            organization_id=world.acme.organization_id,
            project_id=world.acme.project_id,
            user_id=world.acme.client_user_id,
            title="Quando entraremos em produção?",
            last_message_at=datetime.now(timezone.utc),
        )
        session.add(conversation)
        session.flush()
        message = ConversationMessage(
            organization_id=world.acme.organization_id,
            project_id=world.acme.project_id,
            conversation_id=conversation.id,
            user_id=world.acme.client_user_id,
            ordinal=2,
            role=ConversationRole.assistant,
            text="Não há evidência suficiente no contexto do projeto.",
            confidence=MessageConfidence.insufficient_context,
            feedback=MessageFeedback.not_helpful,
            feedback_comment="A resposta não respondeu o que perguntei.",
        )
        session.add(message)
        session.commit()
        created = message.id
        thread = conversation.id

    yield created

    with Session(migrated_engine) as session:
        session.execute(delete(Conversation).where(Conversation.id == thread))
        session.commit()


def test_the_admin_reads_the_signal_of_an_answer_they_did_not_receive(
    world: World, admin_session: Session, bind_admin_context, recorded_turn: uuid.UUID
) -> None:
    """A metade positiva: sem isto a tela do sinal leria zero linhas.

    A conversa é da pessoa que perguntou — as policies de `portal_app` são
    `user_id = portal.current_user_id()` —, então o time interno precisava de uma
    policy própria para ler a avaliação que o cliente deixou para ele.
    """
    from portal_api.models import ConversationMessage

    bind_admin_context(
        subject=world.acme.admin_subject,
        user_id=world.acme.admin_user_id,
        admin_organization_id=world.acme.organization_id,
    )

    row = admin_session.execute(
        select(
            ConversationMessage.id,
            ConversationMessage.feedback,
            ConversationMessage.feedback_comment,
            ConversationMessage.confidence,
        ).where(ConversationMessage.id == recorded_turn)
    ).one()

    assert row.id == recorded_turn
    assert row.feedback_comment == "A resposta não respondeu o que perguntei."


def test_the_admin_cannot_read_what_the_client_asked(
    world: World, admin_session: Session, bind_admin_context, recorded_turn: uuid.UUID
) -> None:
    """A metade negativa, e é ela que define a fatia (ADR 0030).

    A policy decide **quais linhas**; ela não sabe decidir quais colunas. Sem o
    GRANT de coluna, dar ao time interno acesso à avaliação daria junto acesso à
    pergunta do cliente — conteúdo confidencial dele
    (`docs/data-classification.md`), que `ai/service.py` já se recusa a pôr no
    `audit_log` pelo mesmo motivo.
    """
    from portal_api.models import ConversationMessage

    bind_admin_context(
        subject=world.acme.admin_subject,
        user_id=world.acme.admin_user_id,
        admin_organization_id=world.acme.organization_id,
    )

    with pytest.raises(ProgrammingError) as refused:
        admin_session.execute(
            select(ConversationMessage.text).where(
                ConversationMessage.id == recorded_turn
            )
        ).all()

    assert "permission denied" in str(refused.value).lower()


def test_the_admin_cannot_read_the_thread_title_either(
    world: World, admin_session: Session, bind_admin_context, recorded_turn: uuid.UUID
) -> None:
    """A exclusão que quase passou.

    `conversation.title` é derivado da **primeira pergunta**
    (`conversations._title_from`). Barrar `text` e conceder `title` entregaria a
    pergunta pela porta dos fundos — a coluna óbvia de barrar era uma, e a que
    teria vazado assim mesmo era a outra.
    """
    from portal_api.models import Conversation

    bind_admin_context(
        subject=world.acme.admin_subject,
        user_id=world.acme.admin_user_id,
        admin_organization_id=world.acme.organization_id,
    )

    with pytest.raises(ProgrammingError) as refused:
        admin_session.execute(select(Conversation.title)).all()

    assert "permission denied" in str(refused.value).lower()


def test_the_signal_of_another_organization_stays_invisible(
    world: World, admin_session: Session, bind_admin_context, recorded_turn: uuid.UUID
) -> None:
    """A policy nova é `TO portal_admin` e keyed na GUC de terceiro estágio,
    como todo o resto de `admin.py`: administrar a Globex não abre a Acme."""
    from portal_api.models import ConversationMessage

    bind_admin_context(
        subject=world.globex.admin_subject,
        user_id=world.globex.admin_user_id,
        admin_organization_id=world.globex.organization_id,
    )

    visible = admin_session.execute(select(ConversationMessage.id)).scalars().all()

    assert recorded_turn not in visible
