"""Tenant isolation at the database level (ADR 0010).

Every other permission test in this suite goes through a repository or through
``access.py``. These go around both: they run raw ``select()`` under the
``portal_app`` credential, which is exactly what ``biahflow.build_dashboard``
does. If a policy is missing or wrong, only this file notices.

The rows are committed by a ``portal_system`` session, because ``rls_session``
is a different connection and would not see an open transaction's writes.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy import Engine, delete, insert, select, text, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from portal_api.db.session import DbRole, bind_admin_org, get_session
from portal_api.models import (
    DRIVE_READONLY_SCOPE,
    EMBEDDING_DIMENSIONS,
    Conversation,
    ConversationMessage,
    ConversationRole,
    Document,
    DocumentChunk,
    DocumentOrigin,
    DocumentSource,
    MemberRole,
    Membership,
    MessageConfidence,
    Milestone,
    Notification,
    NotificationKind,
    Organization,
    PendingItem,
    PendingState,
    Project,
    ProjectDriveConnection,
    ProjectStatus,
    User,
)
from portal_api.principal import Principal

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Tenant:
    organization_id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    subject: str
    email: str
    milestone_id: uuid.UUID
    notification_id: uuid.UUID


@pytest.fixture(scope="session")
def tenants(migrated_engine: Engine) -> Iterator[tuple[Tenant, Tenant]]:
    """Two fully-populated tenants, committed so another connection sees them.

    Session-scoped because the teardown deletes committed rows from a *different*
    connection: a function-scoped fixture would be finalized before
    ``rls_session``, and the DELETE would then wait forever on the still-open
    transaction of the test that attempted a rejected INSERT (the aborted write
    leaves its xid in progress). Session scope puts the cleanup after every
    function-scoped connection is closed. The tests only read, or attempt writes
    that are rejected or rolled back, so sharing the rows is safe.
    """
    tag = uuid.uuid4().hex[:8]
    built: list[Tenant] = []

    with Session(migrated_engine) as session:
        for name in ("acme", "globex"):
            org = Organization(name=name.title(), slug=f"{name}-{tag}")
            session.add(org)
            session.flush()

            project = Project(
                organization_id=org.id,
                name=f"{name.title()} Project",
                slug=f"{name}-project-{tag}",
                status=ProjectStatus.in_implementation,
            )
            session.add(project)
            session.flush()

            user = User(
                email=f"{name}-{tag}@example.com",
                full_name=f"{name.title()} Client",
                external_subject=f"sub-{name}-{tag}",
            )
            session.add(user)
            session.flush()

            session.add(
                Membership(
                    organization_id=org.id,
                    project_id=project.id,
                    user_id=user.id,
                    role=MemberRole.client_member,
                )
            )
            milestone = Milestone(
                organization_id=org.id,
                project_id=project.id,
                title=f"Kickoff {name}",
            )
            session.add(milestone)
            session.flush()

            # A única tabela cuja linha tem dono (ADR 0012): a policy soma
            # `user_id` ao tenant, e é isso que os testes abaixo cobram.
            notification = Notification(
                organization_id=org.id,
                project_id=project.id,
                user_id=user.id,
                kind=NotificationKind.milestone_done,
                title="Marco concluído",
                detail=f"Kickoff {name}",
                occurred_at=datetime.now(timezone.utc),
                dedupe_key=f"milestone:kickoff-{name}-{tag}:done",
            )
            session.add(notification)
            session.flush()

            built.append(
                Tenant(
                    organization_id=org.id,
                    project_id=project.id,
                    user_id=user.id,
                    subject=user.external_subject or "",
                    email=user.email,
                    milestone_id=milestone.id,
                    notification_id=notification.id,
                )
            )
        session.commit()

    yield built[0], built[1]

    with Session(migrated_engine) as session:
        session.execute(
            delete(Organization).where(
                Organization.id.in_([t.organization_id for t in built])
            )
        )
        session.execute(delete(User).where(User.id.in_([t.user_id for t in built])))
        session.commit()


def _bind_full(bind_context, tenant: Tenant) -> None:
    bind_context(
        subject=tenant.subject,
        email=tenant.email,
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        project_id=tenant.project_id,
    )


# 1 — the invariant everything else rests on ------------------------------------


def test_the_app_role_is_neither_superuser_nor_bypassrls(rls_session: Session) -> None:
    """Guard against a misconfigured DATABASE_URL silently disabling RLS.

    A superuser ignores policies unconditionally, so pointing DATABASE_URL at
    ``portal`` would make every other test here pass while proving nothing.
    """
    row = rls_session.execute(
        text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
    ).one()

    assert row.rolsuper is False
    assert row.rolbypassrls is False


def test_reads_without_any_context_return_nothing(
    rls_session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    """Fail-closed: an unset GUC is NULL, the predicate is not TRUE, no rows."""
    assert rls_session.execute(select(Milestone)).scalars().all() == []
    assert rls_session.execute(select(Project)).scalars().all() == []
    assert rls_session.execute(select(Organization)).scalars().all() == []
    assert rls_session.execute(select(Membership)).scalars().all() == []
    assert rls_session.execute(select(PendingItem)).scalars().all() == []


# 2 — scoping --------------------------------------------------------------------


def test_context_scopes_reads_to_one_tenant(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant_a, tenant_b = tenants
    _bind_full(bind_context, tenant_a)

    milestones = rls_session.execute(select(Milestone)).scalars().all()

    assert [m.id for m in milestones] == [tenant_a.milestone_id]
    assert tenant_b.milestone_id not in {m.id for m in milestones}


def test_another_tenants_row_is_unreachable_even_by_primary_key(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """Holding the UUID is not authorization — the IDOR case from the threat model."""
    tenant_a, tenant_b = tenants
    _bind_full(bind_context, tenant_a)

    assert rls_session.get(Milestone, tenant_b.milestone_id) is None
    assert rls_session.get(Project, tenant_b.project_id) is None
    assert rls_session.get(Organization, tenant_b.organization_id) is None


def test_project_and_organization_follow_membership(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """This is what preserves "404, never 403": a non-member resolves to None."""
    tenant_a, _ = tenants
    # Only stage 1 — the project policy must work before the org is known.
    bind_context(subject=tenant_a.subject, email=tenant_a.email, user_id=tenant_a.user_id)

    projects = rls_session.execute(select(Project)).scalars().all()
    organizations = rls_session.execute(select(Organization)).scalars().all()

    assert [p.id for p in projects] == [tenant_a.project_id]
    assert [o.id for o in organizations] == [tenant_a.organization_id]


def test_membership_is_visible_only_to_its_own_user(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant_a, tenant_b = tenants
    bind_context(subject=tenant_a.subject, email=tenant_a.email, user_id=tenant_a.user_id)

    memberships = rls_session.execute(select(Membership)).scalars().all()

    assert {m.user_id for m in memberships} == {tenant_a.user_id}
    assert tenant_b.user_id not in {m.user_id for m in memberships}


# 3 — writes ----------------------------------------------------------------------


def test_insert_into_another_tenant_is_rejected(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant_a, tenant_b = tenants
    _bind_full(bind_context, tenant_a)

    rls_session.add(
        PendingItem(
            organization_id=tenant_b.organization_id,
            project_id=tenant_b.project_id,
            title="Smuggled",
            state=PendingState.open,
        )
    )

    with pytest.raises(ProgrammingError, match="row-level security"):
        rls_session.flush()


def test_the_read_model_is_not_writable_by_the_app_role(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """Biahflow is the source of truth (ADR 0006/0008), enforced in the database."""
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(
            text("UPDATE milestone SET title = 'tampered' WHERE id = :id"),
            {"id": tenant_a.milestone_id},
        )


def test_a_user_cannot_provision_a_row_for_another_subject(
    rls_session: Session, bind_context
) -> None:
    tag = uuid.uuid4().hex[:8]
    bind_context(subject=f"sub-honest-{tag}", email=f"honest-{tag}@example.com")

    rls_session.add(
        User(
            email=f"honest-{tag}@example.com",
            full_name="Impersonator",
            external_subject=f"sub-someone-else-{tag}",
        )
    )

    with pytest.raises(ProgrammingError, match="row-level security"):
        rls_session.flush()


def test_a_user_row_belonging_to_someone_else_is_invisible(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant_a, tenant_b = tenants
    bind_context(subject=tenant_a.subject, email=tenant_a.email, user_id=tenant_a.user_id)

    users = rls_session.execute(select(User)).scalars().all()

    assert [u.id for u in users] == [tenant_a.user_id]
    assert rls_session.get(User, tenant_b.user_id) is None


# 3b — the one table with an owner (ADR 0012) -------------------------------------


def test_a_notification_addressed_to_someone_else_is_invisible(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """Mesmo tenant não basta: a notificação é de uma pessoa.

    Os dois tenants aqui são organizações diferentes, então este teste sozinho
    passaria só com o predicado de tenant — o de baixo é que separa as duas
    condições.
    """
    tenant_a, tenant_b = tenants
    _bind_full(bind_context, tenant_a)

    visible = {n.id for n in rls_session.execute(select(Notification)).scalars()}

    assert visible == {tenant_a.notification_id}
    assert rls_session.get(Notification, tenant_b.notification_id) is None


def test_a_colleague_in_the_same_project_does_not_see_your_notifications(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """O contexto certo, o usuário errado: zero linhas."""
    tenant_a, _ = tenants
    bind_context(
        subject=tenant_a.subject,
        email=tenant_a.email,
        user_id=uuid.uuid4(),  # colega do mesmo projeto
        organization_id=tenant_a.organization_id,
        project_id=tenant_a.project_id,
    )

    assert rls_session.execute(select(Notification)).scalars().all() == []


def test_marking_read_is_allowed_but_rewriting_the_notice_is_not(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """O grant é de coluna: ``read_at`` sim, ``title`` não.

    A policy decide *quais linhas*, nunca *quais colunas* — sem o
    ``GRANT UPDATE (read_at, updated_at)`` da migração 0009, "marcar como lida"
    seria licença para reescrever o aviso.
    """
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    rls_session.execute(
        text("UPDATE notification SET read_at = now() WHERE id = :id"),
        {"id": tenant_a.notification_id},
    )

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(
            text("UPDATE notification SET title = 'tampered' WHERE id = :id"),
            {"id": tenant_a.notification_id},
        )


def test_the_app_role_cannot_create_a_notification(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """Quem emite é o sync, sob ``portal_system``. O caminho de requisição não origina."""
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(
            text(
                "INSERT INTO notification"
                " (id, organization_id, project_id, user_id, kind, title,"
                "  occurred_at, dedupe_key)"
                " VALUES (gen_random_uuid(), :org, :project, :user,"
                "         'milestone_done', 'forjada', now(), 'forjada')"
            ),
            {
                "org": tenant_a.organization_id,
                "project": tenant_a.project_id,
                "user": tenant_a.user_id,
            },
        )


# 3c — o índice dos documentos (Fase 4, ADR 0014) ---------------------------------


@pytest.fixture(scope="session")
def indexed_documents(
    migrated_engine: Engine, tenants: tuple[Tenant, Tenant]
) -> Iterator[dict[uuid.UUID, uuid.UUID]]:
    """Um documento indexado por tenant. Escopo de sessão pelo mesmo motivo do
    ``tenants``: o teardown apaga linhas comitadas de outra conexão."""
    chunks: dict[uuid.UUID, uuid.UUID] = {}
    with Session(migrated_engine) as session:
        for tenant in tenants:
            document = Document(
                organization_id=tenant.organization_id,
                project_id=tenant.project_id,
                title="Contrato",
                source=DocumentSource.upload,
                origin=DocumentOrigin.portal,
            )
            session.add(document)
            session.flush()
            chunk = DocumentChunk(
                organization_id=tenant.organization_id,
                project_id=tenant.project_id,
                document_id=document.id,
                ordinal=0,
                text="O contrato prevê suporte por 12 meses.",
                location="página 1",
                char_count=38,
                embedding=[0.0] * EMBEDDING_DIMENSIONS,
                embedding_model="offline-hashing-v1-1024",
                content_hash=f"hash-{tenant.organization_id}",
            )
            session.add(chunk)
            session.flush()
            chunks[tenant.organization_id] = chunk.id
        session.commit()

    yield chunks

    with Session(migrated_engine) as session:
        session.execute(delete(DocumentChunk).where(DocumentChunk.id.in_(chunks.values())))
        session.commit()


def test_another_tenants_document_chunk_is_invisible(
    rls_session: Session,
    bind_context,
    tenants: tuple[Tenant, Tenant],
    indexed_documents: dict[uuid.UUID, uuid.UUID],
) -> None:
    """A recuperação do chat lê por aqui: sem esta policy, uma pergunta bem
    escolhida devolveria o contrato do vizinho como citação."""
    tenant_a, tenant_b = tenants
    _bind_full(bind_context, tenant_a)

    visible = {c.id for c in rls_session.execute(select(DocumentChunk)).scalars().all()}

    assert indexed_documents[tenant_a.organization_id] in visible
    assert indexed_documents[tenant_b.organization_id] not in visible


def test_the_app_role_cannot_write_the_index(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """Quem escreve o índice é o worker sob ``portal_system``.

    O caminho de requisição só lê conhecimento — se ele pudesse gravar um trecho,
    poderia gravar a "evidência" que quisesse ver citada.
    """
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(
            text(
                "INSERT INTO document_chunk"
                " (id, organization_id, project_id, document_id, ordinal, text,"
                "  location, char_count, content_hash)"
                " VALUES (gen_random_uuid(), :org, :project, gen_random_uuid(), 0,"
                "         'forjado', '', 7, 'x')"
            ),
            {"org": tenant_a.organization_id, "project": tenant_a.project_id},
        )


def test_the_app_role_cannot_rewrite_an_indexed_excerpt(
    rls_session: Session,
    bind_context,
    tenants: tuple[Tenant, Tenant],
    indexed_documents: dict[uuid.UUID, uuid.UUID],
) -> None:
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(
            text("UPDATE document_chunk SET text = 'adulterado' WHERE id = :id"),
            {"id": indexed_documents[tenant_a.organization_id]},
        )


# 3d — as conversas do chat (Fase 4, ADR 0015) -----------------------------------


@pytest.fixture(scope="session")
def recorded_conversations(
    migrated_engine: Engine, tenants: tuple[Tenant, Tenant]
) -> Iterator[dict[uuid.UUID, uuid.UUID]]:
    """Um turno respondido por tenant, com a citação que ele mostrou.

    Escopo de sessão pelo mesmo motivo do ``tenants`` e do ``indexed_documents``:
    o teardown apaga linhas comitadas de outra conexão.
    """
    answers: dict[uuid.UUID, uuid.UUID] = {}
    with Session(migrated_engine) as session:
        for tenant in tenants:
            conversation = Conversation(
                organization_id=tenant.organization_id,
                project_id=tenant.project_id,
                user_id=tenant.user_id,
                title="Qual é o status?",
                last_message_at=datetime.now(timezone.utc),
            )
            session.add(conversation)
            session.flush()
            answer = ConversationMessage(
                organization_id=tenant.organization_id,
                project_id=tenant.project_id,
                conversation_id=conversation.id,
                user_id=tenant.user_id,
                ordinal=0,
                role=ConversationRole.assistant,
                text="O projeto está em implementação.",
                confidence=MessageConfidence.grounded,
                citations=[
                    {"evidence_id": "project", "source": "Status do projeto", "location": "40%"}
                ],
            )
            session.add(answer)
            session.flush()
            answers[tenant.organization_id] = answer.id
        session.commit()

    yield answers

    with Session(migrated_engine) as session:
        session.execute(
            delete(Conversation).where(
                Conversation.project_id.in_([t.project_id for t in tenants])
            )
        )
        session.commit()


def test_another_tenants_conversation_is_invisible(
    rls_session: Session,
    bind_context,
    tenants: tuple[Tenant, Tenant],
    recorded_conversations: dict[uuid.UUID, uuid.UUID],
) -> None:
    tenant_a, tenant_b = tenants
    _bind_full(bind_context, tenant_a)

    visible = {m.id for m in rls_session.execute(select(ConversationMessage)).scalars()}

    assert recorded_conversations[tenant_a.organization_id] in visible
    assert recorded_conversations[tenant_b.organization_id] not in visible


def test_a_colleague_in_the_same_project_does_not_see_your_conversation(
    rls_session: Session,
    bind_context,
    tenants: tuple[Tenant, Tenant],
    recorded_conversations: dict[uuid.UUID, uuid.UUID],
) -> None:
    """Como a notificação, e por isso mesmo: a linha pertence a uma pessoa.

    O tenant certo, o usuário errado — o predicado de tenant sozinho deixaria o
    colega ler a conversa inteira do vizinho de projeto.
    """
    tenant_a, _ = tenants
    bind_context(
        subject=tenant_a.subject,
        email=tenant_a.email,
        user_id=uuid.uuid4(),  # colega do mesmo projeto
        organization_id=tenant_a.organization_id,
        project_id=tenant_a.project_id,
    )

    assert rls_session.execute(select(Conversation)).scalars().all() == []
    assert rls_session.execute(select(ConversationMessage)).scalars().all() == []


def test_rating_an_answer_is_allowed_but_rewriting_it_is_not(
    rls_session: Session,
    bind_context,
    tenants: tuple[Tenant, Tenant],
    recorded_conversations: dict[uuid.UUID, uuid.UUID],
) -> None:
    """O grant de coluna é o que separa registrar de reescrever (ADR 0015).

    Sem ele, "achei ruim" seria licença para trocar a resposta e as fontes que
    ela mostrou — e o histórico deixaria de valer como registro do que o portal
    de fato respondeu.
    """
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)
    answer_id = recorded_conversations[tenant_a.organization_id]

    rls_session.execute(
        text(
            "UPDATE conversation_message"
            " SET feedback = 'not_helpful', feedback_at = now() WHERE id = :id"
        ),
        {"id": answer_id},
    )

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(
            text("UPDATE conversation_message SET text = 'adulterado' WHERE id = :id"),
            {"id": answer_id},
        )


def test_the_app_role_cannot_rewrite_the_citations_it_was_shown(
    rls_session: Session,
    bind_context,
    tenants: tuple[Tenant, Tenant],
    recorded_conversations: dict[uuid.UUID, uuid.UUID],
) -> None:
    """A citação gravada é o registro do que a pessoa viu, não um campo editável."""
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(
            text("UPDATE conversation_message SET citations = '[]'::jsonb WHERE id = :id"),
            {"id": recorded_conversations[tenant_a.organization_id]},
        )


def test_writing_a_conversation_into_someone_elses_name_is_rejected(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """``portal_app`` insere aqui — é a única tabela em que ele origina o dado.

    O que a policy de INSERT garante é que ele só a origina *para si*: um
    ``user_id`` de outra pessoa não passa pelo ``WITH CHECK``.
    """
    tenant_a, tenant_b = tenants
    _bind_full(bind_context, tenant_a)

    with pytest.raises(ProgrammingError, match="row-level security"):
        rls_session.execute(
            text(
                "INSERT INTO conversation"
                " (id, organization_id, project_id, user_id, title, last_message_at)"
                " VALUES (gen_random_uuid(), :org, :project, :other, 'forjada', now())"
            ),
            {
                "org": tenant_a.organization_id,
                "project": tenant_a.project_id,
                "other": tenant_b.user_id,
            },
        )


def test_the_app_role_cannot_delete_a_conversation(
    rls_session: Session,
    bind_context,
    tenants: tuple[Tenant, Tenant],
    recorded_conversations: dict[uuid.UUID, uuid.UUID],
) -> None:
    """Apagar por organização é retenção (Fase 5), e não será o caminho de requisição."""
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(text("DELETE FROM conversation"))


# 3e — a conexão do Drive (Fase 4, ADR 0016) -------------------------------------


@pytest.fixture(scope="session")
def drive_connections(
    migrated_engine: Engine, tenants: tuple[Tenant, Tenant]
) -> Iterator[dict[uuid.UUID, uuid.UUID]]:
    """Uma pasta conectada por tenant. Escopo de sessão pelo mesmo motivo dos
    demais: o teardown apaga linhas comitadas de outra conexão."""
    connections: dict[uuid.UUID, uuid.UUID] = {}
    with Session(migrated_engine) as session:
        for tenant in tenants:
            connection = ProjectDriveConnection(
                organization_id=tenant.organization_id,
                project_id=tenant.project_id,
                folder_id=f"folder-{tenant.organization_id}",
                folder_name="Contratos",
                google_account_email="interno@portallabs.local",
                refresh_token_sealed="v1.deadbeef.bm9uY2U.Y2lwaGVy",
                granted_scope=DRIVE_READONLY_SCOPE,
            )
            session.add(connection)
            session.flush()
            connections[tenant.organization_id] = connection.id
        session.commit()

    yield connections

    with Session(migrated_engine) as session:
        session.execute(
            delete(ProjectDriveConnection).where(
                ProjectDriveConnection.id.in_(connections.values())
            )
        )
        session.commit()


def test_the_app_role_cannot_read_a_drive_connection(
    rls_session: Session,
    bind_context,
    tenants: tuple[Tenant, Tenant],
    drive_connections: dict[uuid.UUID, uuid.UUID],
) -> None:
    """Nem a do próprio projeto — mesmo desenho de ``agent_api_key``.

    O papel herda o SELECT do ``ALTER DEFAULT PRIVILEGES``, mas nenhuma policy é
    ``TO portal_app``, então a leitura volta vazia. É a diferença entre "você não
    tem permissão" e "a regra não é sobre você", e é o que guarda o refresh token
    do caminho de requisição: o cliente pergunta ao chat, nunca lê a credencial
    que abasteceu o índice.
    """
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    visible = rls_session.execute(select(ProjectDriveConnection)).scalars().all()

    assert visible == []


def test_the_app_role_cannot_write_a_drive_connection(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """Sem GRANT: quem escreve a conexão é ``portal_admin``, e só pela tela."""
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(
            text(
                "INSERT INTO project_drive_connection"
                " (id, organization_id, project_id, folder_id, enabled, sync_state)"
                " VALUES (gen_random_uuid(), :org, :project, 'forjada', true, 'idle')"
            ),
            {"org": tenant_a.organization_id, "project": tenant_a.project_id},
        )


def test_another_tenants_drive_connection_is_invisible_to_the_admin(
    tenants: tuple[Tenant, Tenant],
    drive_connections: dict[uuid.UUID, uuid.UUID],
) -> None:
    """A GUC de terceiro estágio recorta a administração por organização.

    Sem isto, um ``internal_admin`` de uma organização enxergaria a pasta — e o
    endereço da pasta — de outra.
    """
    tenant_a, tenant_b = tenants

    with get_session(role=DbRole.admin) as session:
        bind_admin_org(session, tenant_a.organization_id)
        visible = {
            c.id for c in session.execute(select(ProjectDriveConnection)).scalars().all()
        }

    assert drive_connections[tenant_a.organization_id] in visible
    assert drive_connections[tenant_b.organization_id] not in visible


# 4 — the system path -------------------------------------------------------------


def test_the_system_role_bypasses_the_policies(
    db_session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    """Without this the Biahflow webhook could not create a tenant at all."""
    tenant_a, tenant_b = tenants

    visible = {m.id for m in db_session.execute(select(Milestone)).scalars().all()}

    assert {tenant_a.milestone_id, tenant_b.milestone_id} <= visible


# 5 — the pooled connection -------------------------------------------------------


def test_context_does_not_leak_into_the_next_transaction(
    tenants: tuple[Tenant, Tenant],
) -> None:
    """``set_config(..., true)`` is transaction-local; a bare SET would leak.

    Uses ``get_session`` rather than the fixtures so the connection really is
    returned to the pool and picked up again.
    """
    tenant_a, _ = tenants
    principal = Principal(
        subject=tenant_a.subject, email=tenant_a.email, full_name="Acme Client"
    )

    with get_session(principal) as session:
        assert session.execute(
            text("SELECT current_setting('portal.subject', true)")
        ).scalar() == tenant_a.subject

    with get_session() as session:
        leaked = session.execute(
            text(
                "SELECT nullif(current_setting('portal.subject', true), '') AS subject,"
                "       nullif(current_setting('portal.organization_id', true), '') AS organization_id"
            )
        ).one()

    assert leaked.subject is None
    assert leaked.organization_id is None


def test_a_principal_cannot_run_under_the_system_role() -> None:
    principal = Principal(subject="sub-x", email="x@example.com", full_name="X")

    with pytest.raises(ValueError, match="system role"):
        with get_session(principal, role=DbRole.system):
            pass  # pragma: no cover - the context manager raises on entry


# 6 — the guard that protects future phases ---------------------------------------


def test_every_tenant_table_has_rls_enabled_and_a_policy(db_session: Session) -> None:
    """A table added in a later phase without a policy fails CI on its own.

    This is the piece that keeps the control from eroding: the Fase 4 knowledge
    tables will carry ``organization_id`` too, and forgetting the policy there
    would silently reopen cross-tenant reads.
    """
    unprotected = db_session.execute(
        text(
            """
            SELECT c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_attribute a ON a.attrelid = c.oid
             WHERE n.nspname = 'portal'
               AND c.relkind = 'r'
               AND a.attname = 'organization_id'
               AND NOT a.attisdropped
               AND (NOT c.relrowsecurity
                    OR NOT EXISTS (SELECT 1 FROM pg_policies p
                                    WHERE p.schemaname = n.nspname
                                      AND p.tablename = c.relname))
            """
        )
    ).scalars().all()

    assert unprotected == [], f"tables with organization_id but no RLS: {unprotected}"


# 6 — retenção e expurgo (Fase 5, ADR 0017) --------------------------------------
#
# Mesmo desenho de `agent_api_key` e `project_drive_connection`: policies
# `TO portal_admin` e nenhuma `TO portal_app`. Aqui isso guarda uma coisa
# específica — a data em que os dados do cliente serão apagados não deve vazar
# por uma tela que não foi feita para dizê-la.


@pytest.fixture
def retention_policies(
    migrated_engine: Engine, tenants: tuple[Tenant, Tenant]
) -> Iterator[dict[uuid.UUID, uuid.UUID]]:
    from portal_api.models import OrganizationRetentionPolicy

    tenant_a, tenant_b = tenants
    ids: dict[uuid.UUID, uuid.UUID] = {}
    with Session(migrated_engine) as session:
        for tenant in (tenant_a, tenant_b):
            record = OrganizationRetentionPolicy(
                organization_id=tenant.organization_id, notification_days=30
            )
            session.add(record)
            session.flush()
            ids[tenant.organization_id] = record.id
        session.commit()
    yield ids
    with Session(migrated_engine) as session:
        session.execute(
            delete(OrganizationRetentionPolicy).where(
                OrganizationRetentionPolicy.id.in_(ids.values())
            )
        )
        session.commit()


def test_the_app_role_cannot_read_a_retention_policy(
    rls_session: Session,
    bind_context,
    tenants: tuple[Tenant, Tenant],
    retention_policies: dict[uuid.UUID, uuid.UUID],
) -> None:
    """Nem a da própria organização.

    "Suas conversas serão apagadas em 30 dias" é uma frase que precisa ser dita
    por uma tela que a explique, não descoberta por quem alcançar a tabela.
    """
    from portal_api.models import OrganizationRetentionPolicy

    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    visible = rls_session.execute(select(OrganizationRetentionPolicy)).scalars().all()

    assert visible == []


def test_the_app_role_cannot_request_an_erasure(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """Sem GRANT: o pedido nasce sob ``portal_admin``, pela tela de administração.

    Um caminho de requisição capaz de gravar esta linha seria um caminho de
    requisição capaz de apagar a organização inteira — em diferido, mas apagar.
    """
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(
            text(
                "INSERT INTO data_erasure_request (id, organization_id, state)"
                " VALUES (gen_random_uuid(), :org, 'pending')"
            ),
            {"org": tenant_a.organization_id},
        )


def test_another_tenants_retention_policy_is_invisible_to_the_admin(
    tenants: tuple[Tenant, Tenant],
    retention_policies: dict[uuid.UUID, uuid.UUID],
) -> None:
    from portal_api.models import OrganizationRetentionPolicy

    tenant_a, tenant_b = tenants

    with get_session(role=DbRole.admin) as session:
        bind_admin_org(session, tenant_a.organization_id)
        visible = {
            row.id
            for row in session.execute(select(OrganizationRetentionPolicy)).scalars().all()
        }

    assert retention_policies[tenant_a.organization_id] in visible
    assert retention_policies[tenant_b.organization_id] not in visible


def test_the_admin_cannot_rewrite_the_record_of_an_erasure(
    tenants: tuple[Tenant, Tenant],
) -> None:
    """``portal_admin`` insere o pedido e não o edita — só SELECT e INSERT.

    Mesma razão do GRANT de coluna da `notification` (ADR 0012): o registro do
    que aconteceu não pertence a quem o provocou. Quem carimba o resultado é o
    worker sob ``portal_system``, que foi quem fez o trabalho.
    """
    tenant_a, _ = tenants

    with get_session(role=DbRole.admin) as session:
        bind_admin_org(session, tenant_a.organization_id)
        with pytest.raises(ProgrammingError, match="permission denied"):
            session.execute(
                text("UPDATE data_erasure_request SET state = 'completed'")
            )


# 7 — comentários na pendência (Fase 2, ADR 0032) --------------------------------
#
# A tabela inverte o escopo das outras duas que o caminho de requisição origina:
# `conversation` e `conversation_message` são de **pessoa**, e a ADR 0030 chegou a
# revogar privilégio para manter isso. O comentário é do **projeto**, porque
# existe para ser lido pelo outro lado — então o que estes testes precisam provar
# é o par oposto: o colega de projeto **vê**, e o vizinho de tenant **não**.


@pytest.fixture
def a_comment(migrated_engine: Engine, tenants: tuple[Tenant, Tenant]):
    """Um comentário em cada tenant, escrito pelo papel de sistema e commitado."""
    from portal_api.models import PendingItem, PendingItemComment, PendingOrigin

    created: dict[uuid.UUID, uuid.UUID] = {}
    with Session(migrated_engine) as session:
        for tenant in tenants:
            pending = PendingItem(
                organization_id=tenant.organization_id,
                project_id=tenant.project_id,
                title="Enviar a planilha",
                origin=PendingOrigin.biahflow,
            )
            session.add(pending)
            session.flush()
            comment = PendingItemComment(
                organization_id=tenant.organization_id,
                project_id=tenant.project_id,
                pending_item_id=pending.id,
                author_user_id=tenant.user_id,
                author_label="Cliente",
                author_is_internal=False,
                body="Já enviei ontem.",
            )
            session.add(comment)
            session.flush()
            created[tenant.organization_id] = comment.id
        session.commit()

    yield created

    with Session(migrated_engine) as session:
        from portal_api.models import PendingItemComment as _Comment

        session.execute(delete(_Comment).where(_Comment.id.in_(list(created.values()))))
        session.commit()


def test_a_comment_from_another_tenant_is_invisible(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant], a_comment
) -> None:
    from portal_api.models import PendingItemComment

    tenant_a, tenant_b = tenants
    _bind_full(bind_context, tenant_a)

    visible = {
        row for row in rls_session.execute(select(PendingItemComment.id)).scalars()
    }

    assert a_comment[tenant_a.organization_id] in visible
    assert a_comment[tenant_b.organization_id] not in visible


def test_a_colleague_in_the_same_project_does_see_the_comment(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant], a_comment
) -> None:
    """O oposto de `test_a_colleague_in_the_same_project_does_not_see_your_conversation`.

    Mesma dupla de tabelas originadas no caminho de requisição, escopos opostos —
    e é o teste que prova que a inversão da ADR 0032 é intencional e não um
    predicado esquecido. Um comentário que só o autor lê não serviria para nada.
    """
    from portal_api.models import PendingItemComment

    tenant_a, _ = tenants
    bind_context(
        subject=tenant_a.subject,
        email=tenant_a.email,
        user_id=uuid.uuid4(),  # colega do mesmo projeto, outra pessoa
        organization_id=tenant_a.organization_id,
        project_id=tenant_a.project_id,
    )

    visible = list(rls_session.execute(select(PendingItemComment.id)).scalars())

    assert a_comment[tenant_a.organization_id] in visible


def test_the_app_role_writes_a_comment_but_cannot_rewrite_it(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant], a_comment
) -> None:
    """Escrever sim, reescrever não — o argumento da ADR 0015 outra vez.

    O `SELECT` vem do default privilege do `roles.sql` e o `INSERT` da migração
    0021; `UPDATE` e `DELETE` **não foram concedidos**, e é o controle inteiro.
    """
    from portal_api.models import PendingItem, PendingItemComment

    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)
    pending_id = rls_session.execute(
        select(PendingItem.id).where(PendingItem.project_id == tenant_a.project_id)
    ).scalars().first()

    rls_session.execute(
        insert(PendingItemComment).values(
            id=uuid.uuid4(),
            organization_id=tenant_a.organization_id,
            project_id=tenant_a.project_id,
            pending_item_id=pending_id,
            author_user_id=tenant_a.user_id,
            author_label="Cliente",
            author_is_internal=False,
            body="Escrito pelo caminho de requisição.",
        )
    )

    mine = a_comment[tenant_a.organization_id]
    with pytest.raises(ProgrammingError) as no_update:
        rls_session.execute(
            update(PendingItemComment)
            .where(PendingItemComment.id == mine)
            .values(body="reescrito")
        )
    assert "permission denied" in str(no_update.value).lower()
    rls_session.rollback()

    _bind_full(bind_context, tenant_a)
    with pytest.raises(ProgrammingError) as no_delete:
        rls_session.execute(
            delete(PendingItemComment).where(PendingItemComment.id == mine)
        )
    assert "permission denied" in str(no_delete.value).lower()


# 8 — o funil de onboarding (Fase 7, RFC 001, ADR 0039) --------------------------
#
# Mesmo desenho de `agent_api_key` e `project_drive_connection`: nenhuma policy
# `TO portal_app`. Aqui isso guarda uma coisa específica — **um caminho de
# requisição capaz de escrever o próprio degrau é um caminho capaz de falsear o
# próprio engajamento**, e o funil é a métrica que decide quem recebe telefonema.


@pytest.fixture
def onboarding_steps(
    migrated_engine: Engine, tenants: tuple[Tenant, Tenant]
) -> Iterator[dict[uuid.UUID, uuid.UUID]]:
    from portal_api.models import OnboardingStep, OnboardingStepName

    tenant_a, tenant_b = tenants
    ids: dict[uuid.UUID, uuid.UUID] = {}
    with Session(migrated_engine) as session:
        for tenant in (tenant_a, tenant_b):
            record = OnboardingStep(
                organization_id=tenant.organization_id,
                step=OnboardingStepName.first_login,
                reached_at=datetime.now(timezone.utc),
            )
            session.add(record)
            session.flush()
            ids[tenant.organization_id] = record.id
        session.commit()
    yield ids
    with Session(migrated_engine) as session:
        session.execute(delete(OnboardingStep).where(OnboardingStep.id.in_(ids.values())))
        session.commit()


def test_the_app_role_never_reads_the_funnel(
    rls_session: Session,
    bind_context,
    tenants: tuple[Tenant, Tenant],
    onboarding_steps: dict[uuid.UUID, uuid.UUID],
) -> None:
    """Nem o da própria organização: a regra não é sobre o papel de requisição.

    O cliente não deve saber que está sendo medido em funil, e não há nada que ele
    possa fazer com essa informação — a FDD 020 diz isso na seção de jornada. A
    leitura volta vazia porque nenhuma policy é ``TO portal_app``, e não porque
    alguém lembrou de filtrar.
    """
    from portal_api.models import OnboardingStep

    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    assert rls_session.execute(select(OnboardingStep)).scalars().all() == []


def test_the_app_role_cannot_stamp_its_own_step(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """Sem GRANT de INSERT: quem carimba é o sistema, em transação própria.

    É a diferença entre medir engajamento e deixar o medido escrever a medição.
    """
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(
            text(
                "INSERT INTO onboarding_step"
                " (id, organization_id, step, reached_at)"
                " VALUES (gen_random_uuid(), :org, 'first_login', now())"
            ),
            {"org": tenant_a.organization_id},
        )


# 9 — o teto de frequência de contato (Fase 7, FDD 021/022, ADR 0042) ------------
#
# Mesmo desfecho das tabelas acima e por um caminho diferente, que é o que estes
# dois testes existem para fixar. As anteriores negam o papel de requisição
# **omitindo** a policy; esta o nega com uma que diz `USING (false)`, porque a
# omissão custaria reprovar o meta-teste (a tabela tem `organization_id`) e a saída
# fácil — conceder leitura a uma tela que não existe — é o defeito da ADR 0033
# escrito ao contrário. Se alguém trocar a regra por uma escopada ao ligar a tela da
# FDD 022, é aqui que a troca aparece.


@pytest.fixture
def contact_events(
    migrated_engine: Engine, tenants: tuple[Tenant, Tenant]
) -> Iterator[dict[uuid.UUID, uuid.UUID]]:
    from portal_api.models import ContactEvent, ContactKind

    ids: dict[uuid.UUID, uuid.UUID] = {}
    with Session(migrated_engine) as session:
        for tenant in tenants:
            record = ContactEvent(
                organization_id=tenant.organization_id,
                user_id=tenant.user_id,
                kind=ContactKind.whatsapp_notice,
                dedupe_key=f"aviso:{tenant.organization_id}",
            )
            session.add(record)
            session.flush()
            ids[tenant.organization_id] = record.id
        session.commit()
    yield ids
    with Session(migrated_engine) as session:
        from portal_api.models import ContactEvent as _Contact

        session.execute(delete(_Contact).where(_Contact.id.in_(list(ids.values()))))
        session.commit()


def test_the_app_role_never_reads_its_own_contact_history(
    rls_session: Session,
    bind_context,
    tenants: tuple[Tenant, Tenant],
    contact_events: dict[uuid.UUID, uuid.UUID],
) -> None:
    """Nem a linha que é sobre a própria pessoa autenticada.

    Não é privacidade do cliente contra ele mesmo — é que não há leitor: nenhuma
    tela mostra histórico de contato, e uma leitura aberta "por precaução" seria o
    campo publicado sem consumidor da ADR 0033.
    """
    from portal_api.models import ContactEvent

    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    assert rls_session.execute(select(ContactEvent)).scalars().all() == []


def test_the_app_role_cannot_spend_or_forge_its_own_budget(
    rls_session: Session, bind_context, tenants: tuple[Tenant, Tenant]
) -> None:
    """Escrever o próprio contato seria gastar — ou zerar — o próprio teto.

    A simetria com o funil é exata: lá um caminho de requisição capaz de escrever o
    degrau falseia o próprio engajamento; aqui um capaz de escrever o contato decide
    quantas mensagens recebe. Quem escreve é o sistema, na transação do envio.
    """
    tenant_a, _ = tenants
    _bind_full(bind_context, tenant_a)

    with pytest.raises(ProgrammingError, match="permission denied"):
        rls_session.execute(
            text(
                "INSERT INTO contact_event"
                " (id, organization_id, user_id, kind, dedupe_key)"
                " VALUES (gen_random_uuid(), :org, :user, 'whatsapp_notice', 'forjado')"
            ),
            {"org": tenant_a.organization_id, "user": tenant_a.user_id},
        )
