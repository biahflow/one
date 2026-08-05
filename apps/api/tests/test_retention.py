"""Prazo dos dados e expurgo por organização (Fase 5, ADR 0017).

O que estes testes precisam provar não é "o DELETE funciona" — é que ele **não**
alcança o que não devia: o dado dentro da janela, o documento (que é evidência de
citação e não sai por idade) e, acima de tudo, a outra organização.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from portal_api import retention
from portal_api.config import Settings
from portal_api.models import (
    Conversation,
    Document,
    DocumentOrigin,
    DocumentSource,
    MemberRole,
    Membership,
    Notification,
    NotificationKind,
    Organization,
    OrganizationRetentionPolicy,
    Project,
    ProjectStatus,
    User,
)

# --- a política (sem banco) ------------------------------------------------


def test_a_missing_policy_means_the_default_and_not_forever() -> None:
    """A afirmação que o resto do módulo depende de ser verdade.

    Um contrato que não fala de retenção não é um contrato de retenção infinita.
    Se a ausência de linha significasse "guarda para sempre", a poda só valeria
    para quem já tivesse sido configurado — ou seja, para ninguém no dia um.
    """
    limits = retention.windows_for(None, Settings())

    assert limits.notification_days == Settings().retention_notification_days
    assert limits.conversation_days == Settings().retention_conversation_days


def test_a_null_column_falls_back_column_by_column() -> None:
    """Definir um prazo não obriga a definir os três."""
    policy = OrganizationRetentionPolicy(
        organization_id=uuid.uuid4(), notification_days=30
    )

    limits = retention.windows_for(policy, Settings())

    assert limits.notification_days == 30
    assert limits.agent_event_days == Settings().retention_agent_event_days


# --- a poda e o expurgo (com banco) ----------------------------------------


@pytest.fixture
def tenants(migrated_engine: Engine) -> Iterator[dict[str, uuid.UUID]]:
    """Duas organizações, porque a afirmação que interessa é sobre a fronteira.

    Cada uma com uma pessoa, porque ``notification`` é a tabela cuja linha
    pertence a alguém (ADR 0012) e ``user_id`` não é anulável.
    """
    tag = uuid.uuid4().hex[:8]
    ids: dict[str, uuid.UUID] = {}
    with Session(migrated_engine) as session:
        for label in ("acme", "globex"):
            organization = Organization(name=label.title(), slug=f"{label}-ret-{tag}")
            session.add(organization)
            session.flush()
            project = Project(
                organization_id=organization.id,
                name=f"Projeto {label}",
                slug=f"{label}-ret-project-{tag}",
                status=ProjectStatus.in_implementation,
            )
            session.add(project)
            session.flush()
            user = User(
                email=f"cliente-{label}-{tag}@example.com",
                full_name=f"Cliente {label.title()}",
                external_subject=f"sub-ret-{label}-{tag}",
            )
            session.add(user)
            session.flush()
            ids[f"{label}_org"] = organization.id
            ids[f"{label}_project"] = project.id
            ids[f"{label}_user"] = user.id
        session.commit()
    yield ids


def _notification(session: Session, ids: dict, label: str, *, age_days: int) -> uuid.UUID:
    when = datetime.now(timezone.utc) - timedelta(days=age_days)
    record = Notification(
        organization_id=ids[f"{label}_org"],
        project_id=ids[f"{label}_project"],
        user_id=ids[f"{label}_user"],
        kind=NotificationKind.milestone_done,
        title="Marco concluído",
        dedupe_key=f"{label}-{uuid.uuid4().hex}",
        occurred_at=when,
    )
    session.add(record)
    session.flush()
    # `created_at` tem server_default; a idade é imposta depois de a linha existir.
    record.created_at = when
    session.flush()
    return record.id


@pytest.mark.integration
def test_the_window_removes_the_expired_and_keeps_the_rest(
    migrated_engine: Engine, tenants: dict[str, uuid.UUID]
) -> None:
    settings = Settings(retention_notification_days=90)
    with Session(migrated_engine) as session:
        old = _notification(session, tenants, "acme", age_days=200)
        recent = _notification(session, tenants, "acme", age_days=10)
        session.commit()

    with Session(migrated_engine) as session:
        outcome = retention.purge_expired(session, tenants["acme_org"], settings)
        session.commit()

    assert outcome.removed["notification"] == 1
    with Session(migrated_engine) as session:
        assert session.get(Notification, old) is None
        assert session.get(Notification, recent) is not None


@pytest.mark.integration
def test_the_purge_never_crosses_into_another_organization(
    migrated_engine: Engine, tenants: dict[str, uuid.UUID]
) -> None:
    """A afirmação que sustenta todas as outras.

    Um expurgo que vaza de tenant é pior do que não expurgar: apaga dado de quem
    não pediu, e não há de onde trazer de volta.
    """
    settings = Settings(retention_notification_days=90)
    with Session(migrated_engine) as session:
        mine = _notification(session, tenants, "acme", age_days=200)
        theirs = _notification(session, tenants, "globex", age_days=200)
        session.commit()

    with Session(migrated_engine) as session:
        retention.purge_expired(session, tenants["acme_org"], settings)
        session.commit()

    with Session(migrated_engine) as session:
        assert session.get(Notification, mine) is None
        assert session.get(Notification, theirs) is not None


@pytest.mark.integration
def test_the_organization_window_beats_the_default(
    migrated_engine: Engine, tenants: dict[str, uuid.UUID]
) -> None:
    settings = Settings(retention_notification_days=365)
    with Session(migrated_engine) as session:
        session.add(
            OrganizationRetentionPolicy(
                organization_id=tenants["acme_org"], notification_days=30
            )
        )
        record = _notification(session, tenants, "acme", age_days=60)
        session.commit()

    with Session(migrated_engine) as session:
        retention.purge_expired(session, tenants["acme_org"], settings)
        session.commit()

    # 60 dias sobrevive ao padrão de 365 e não sobrevive aos 30 da organização.
    with Session(migrated_engine) as session:
        assert session.get(Notification, record) is None


def _conversation(
    session: Session,
    ids: dict,
    *,
    created_days_ago: int,
    last_message_days_ago: int,
    touched_days_ago: int | None = None,
) -> uuid.UUID:
    record = Conversation(
        organization_id=ids["acme_org"],
        project_id=ids["acme_project"],
        user_id=ids["acme_user"],
        title="Sobre o contrato",
        last_message_at=datetime.now(timezone.utc)
        - timedelta(days=last_message_days_ago),
    )
    session.add(record)
    session.flush()
    record.created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    if touched_days_ago is not None:
        record.updated_at = datetime.now(timezone.utc) - timedelta(days=touched_days_ago)
    session.flush()
    return record.id


@pytest.mark.integration
def test_a_conversation_still_in_use_is_not_pruned_by_its_birthday(
    migrated_engine: Engine, tenants: dict[str, uuid.UUID]
) -> None:
    """Uma thread aberta há um ano e respondida ontem é a conversa de alguém.

    Podá-la por `created_at` apagaria o histórico debaixo de quem está usando.
    """
    settings = Settings(retention_conversation_days=180)
    with Session(migrated_engine) as session:
        conversation_id = _conversation(
            session, tenants, created_days_ago=400, last_message_days_ago=1
        )
        session.commit()

    with Session(migrated_engine) as session:
        outcome = retention.purge_expired(session, tenants["acme_org"], settings)
        session.commit()

    assert outcome.removed["conversation"] == 0
    with Session(migrated_engine) as session:
        assert session.get(Conversation, conversation_id) is not None


@pytest.mark.integration
def test_a_thumb_on_a_dead_conversation_does_not_keep_it_alive(
    migrated_engine: Engine, tenants: dict[str, uuid.UUID]
) -> None:
    """O erro oposto, e o mais fácil de cometer: podar por `updated_at`.

    A ADR 0015 separou `last_message_at` de `updated_at` porque "marcar um
    feedback não é conversar". Se a poda olhasse `updated_at`, um polegar dado
    hoje numa conversa de dois anos atrás a preservaria para sempre — e a
    retenção deixaria de significar alguma coisa exatamente nas threads mais
    antigas.
    """
    settings = Settings(retention_conversation_days=180)
    with Session(migrated_engine) as session:
        conversation_id = _conversation(
            session,
            tenants,
            created_days_ago=700,
            last_message_days_ago=700,
            touched_days_ago=0,  # avaliada hoje
        )
        session.commit()

    with Session(migrated_engine) as session:
        outcome = retention.purge_expired(session, tenants["acme_org"], settings)
        session.commit()

    assert outcome.removed["conversation"] == 1
    with Session(migrated_engine) as session:
        assert session.get(Conversation, conversation_id) is None


@pytest.mark.integration
def test_the_purge_never_touches_a_document(
    migrated_engine: Engine, tenants: dict[str, uuid.UUID]
) -> None:
    """Documento é a evidência que sustenta uma citação já dada.

    Apagá-lo por aniversário tornaria uma resposta antiga impossível de conferir,
    que é o avesso da regra 3 do `AGENTS.md`. Ele sai pelo expurgo, que é decisão
    de alguém, ou pela tela — nunca pelo calendário.
    """
    with Session(migrated_engine) as session:
        record = Document(
            organization_id=tenants["acme_org"],
            project_id=tenants["acme_project"],
            title="Contrato antigo",
            source=DocumentSource.upload,
            origin=DocumentOrigin.portal,
            mime_type="text/plain",
        )
        session.add(record)
        session.flush()
        record.created_at = datetime.now(timezone.utc) - timedelta(days=5000)
        session.commit()
        document_id = record.id

    with Session(migrated_engine) as session:
        outcome = retention.purge_expired(session, tenants["acme_org"], Settings())
        session.commit()

    assert "document" not in outcome.removed
    with Session(migrated_engine) as session:
        assert session.get(Document, document_id) is not None


@pytest.mark.integration
def test_the_erasure_removes_the_content_and_leaves_the_organization(
    migrated_engine: Engine, tenants: dict[str, uuid.UUID]
) -> None:
    with Session(migrated_engine) as session:
        session.add(
            Document(
                organization_id=tenants["acme_org"],
                project_id=tenants["acme_project"],
                title="Contrato",
                source=DocumentSource.upload,
                origin=DocumentOrigin.portal,
                mime_type="text/plain",
            )
        )
        _notification(session, tenants, "acme", age_days=1)
        session.commit()

    with Session(migrated_engine) as session:
        outcome = retention.run_erasure(session, tenants["acme_org"])
        session.commit()

    assert outcome.removed["document"] == 1
    assert outcome.removed["project"] == 1
    with Session(migrated_engine) as session:
        assert session.get(Project, tenants["acme_project"]) is None
        assert (
            session.execute(
                select(Document).where(Document.organization_id == tenants["acme_org"])
            ).first()
            is None
        )
        # A âncora do tenant fica: é o que segura o registro do próprio expurgo.
        assert session.get(Organization, tenants["acme_org"]) is not None


@pytest.mark.integration
def test_the_erasure_removes_the_organization_wide_membership_too(
    migrated_engine: Engine, tenants: dict[str, uuid.UUID]
) -> None:
    """O vínculo de `project_id` nulo é a única exclusão escrita à mão.

    Ele não vem no CASCADE do projeto justamente por não apontar para projeto
    nenhum — e é o vínculo da equipe interna, que sem isto continuaria ligada a
    uma organização já apagada.
    """
    with Session(migrated_engine) as session:
        user = User(
            email=f"interno-{uuid.uuid4().hex[:8]}@portal.test",
            full_name="Interno",
            external_subject=str(uuid.uuid4()),
        )
        session.add(user)
        session.flush()
        session.add(
            Membership(
                organization_id=tenants["acme_org"],
                project_id=None,
                user_id=user.id,
                role=MemberRole.internal_admin,
            )
        )
        session.commit()
        user_id = user.id

    with Session(migrated_engine) as session:
        outcome = retention.run_erasure(session, tenants["acme_org"])
        session.commit()

    assert outcome.removed["membership"] == 1
    with Session(migrated_engine) as session:
        assert (
            session.execute(
                select(Membership).where(
                    Membership.organization_id == tenants["acme_org"]
                )
            ).first()
            is None
        )
        # A pessoa fica: a identidade é do realm, e ela pode pertencer a outra
        # organização. O que se desfez foi o vínculo.
        assert session.get(User, user_id) is not None


@pytest.mark.integration
def test_the_erasure_of_one_organization_leaves_the_other_intact(
    migrated_engine: Engine, tenants: dict[str, uuid.UUID]
) -> None:
    with Session(migrated_engine) as session:
        session.add(
            Document(
                organization_id=tenants["globex_org"],
                project_id=tenants["globex_project"],
                title="Contrato da Globex",
                source=DocumentSource.upload,
                origin=DocumentOrigin.portal,
                mime_type="text/plain",
            )
        )
        session.commit()

    with Session(migrated_engine) as session:
        retention.run_erasure(session, tenants["acme_org"])
        session.commit()

    with Session(migrated_engine) as session:
        assert session.get(Project, tenants["globex_project"]) is not None
        assert (
            session.execute(
                select(Document).where(
                    Document.organization_id == tenants["globex_org"]
                )
            ).first()
            is not None
        )


def test_the_storage_prefix_cannot_match_a_neighbouring_organization() -> None:
    """A barra final não é cosmética: o S3 compara texto, não caminho."""
    prefix = retention.storage_prefix(uuid.UUID("11111111-1111-1111-1111-111111111111"))

    assert prefix.endswith("/")
    assert prefix == "org/11111111-1111-1111-1111-111111111111/"
