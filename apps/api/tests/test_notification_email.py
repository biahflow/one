"""O resumo por e-mail das notificações (Fase 2, ADR 0012).

A task roda fora do pedido e abre a própria sessão sob ``portal_system``, então
os dados aqui entram por uma sessão comitada, como no ``world`` de
``test_authorization``. O SMTP é substituído: o que se prova é a regra — um
e-mail por lote, ``emailed_at`` como trava de reenvio, e a preferência do
destinatário respeitada —, não que o ``smtplib`` funciona.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from email.message import EmailMessage

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from portal_api import mailer, worker
from portal_api.models import (
    MemberRole,
    Membership,
    Notification,
    NotificationKind,
    Organization,
    Project,
    ProjectStatus,
    User,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    sent: list[EmailMessage] = []

    def _send(settings, message: EmailMessage) -> None:
        sent.append(message)

    monkeypatch.setattr(mailer, "send", _send)
    return sent


@pytest.fixture
def project_with_two_notices(migrated_engine: Engine):
    """Um projeto, um cliente, dois avisos não enviados."""
    tag = uuid.uuid4().hex[:8]
    with Session(migrated_engine) as session:
        organization = Organization(name="Acme", slug=f"acme-mail-{tag}")
        session.add(organization)
        session.flush()
        project = Project(
            organization_id=organization.id,
            name="Automação Financeira",
            slug=f"acme-mail-project-{tag}",
            status=ProjectStatus.in_implementation,
        )
        session.add(project)
        session.flush()
        user = User(
            email=f"cliente-mail-{tag}@example.com",
            full_name="Cliente",
            external_subject=f"sub-mail-{tag}",
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
        for index, title in enumerate(("Marco concluído", "Novo documento no projeto")):
            session.add(
                Notification(
                    organization_id=organization.id,
                    project_id=project.id,
                    user_id=user.id,
                    kind=NotificationKind.milestone_done,
                    title=title,
                    detail=f"detalhe {index}",
                    occurred_at=datetime.now(timezone.utc),
                    dedupe_key=f"{tag}-{index}",
                )
            )
        session.commit()
        ids = (organization.id, project.id, user.id)

    yield ids

    with Session(migrated_engine) as cleanup:
        cleanup.execute(delete(Organization).where(Organization.id == ids[0]))
        cleanup.execute(delete(User).where(User.id == ids[2]))
        cleanup.commit()


def test_one_email_per_batch_not_one_per_notification(
    project_with_two_notices, outbox: list[EmailMessage], migrated_engine: Engine
) -> None:
    _, project_id, _ = project_with_two_notices

    result = worker.send_project_digests(str(project_id))

    assert result == {"sent": 1, "notifications": 2}
    assert len(outbox) == 1
    assert outbox[0]["Subject"] == "2 atualizações em Automação Financeira"
    body = outbox[0].get_content()
    assert "Marco concluído" in body and "Novo documento no projeto" in body


def test_running_twice_does_not_send_twice(
    project_with_two_notices, outbox: list[EmailMessage], migrated_engine: Engine
) -> None:
    """``emailed_at`` é a trava: a fila pode reentregar a task."""
    _, project_id, _ = project_with_two_notices

    worker.send_project_digests(str(project_id))
    second = worker.send_project_digests(str(project_id))

    assert second == {"sent": 0, "notifications": 0}
    assert len(outbox) == 1

    with Session(migrated_engine) as session:
        stamped = session.execute(
            select(Notification).where(Notification.project_id == project_id)
        ).scalars().all()
        assert all(item.emailed_at is not None for item in stamped)


def test_a_user_who_turned_email_off_gets_nothing(
    project_with_two_notices, outbox: list[EmailMessage], migrated_engine: Engine
) -> None:
    """E o aviso não fica represado: religar a preferência não abre a comporta."""
    _, project_id, user_id = project_with_two_notices
    with Session(migrated_engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        user.notify_by_email = False
        session.commit()

    result = worker.send_project_digests(str(project_id))

    assert result == {"sent": 0, "notifications": 2}
    assert outbox == []
    with Session(migrated_engine) as session:
        stamped = session.execute(
            select(Notification).where(Notification.project_id == project_id)
        ).scalars().all()
        assert all(item.emailed_at is not None for item in stamped)


def test_a_single_change_names_itself_in_the_subject(
    project_with_two_notices, outbox: list[EmailMessage], migrated_engine: Engine
) -> None:
    _, project_id, _ = project_with_two_notices
    with Session(migrated_engine) as session:
        extra = session.execute(
            select(Notification)
            .where(Notification.project_id == project_id)
            .order_by(Notification.occurred_at)
        ).scalars().all()
        extra[0].emailed_at = datetime.now(timezone.utc)
        session.commit()

    worker.send_project_digests(str(project_id))

    assert outbox[0]["Subject"] == "Novo documento no projeto — Automação Financeira"


def test_the_smtp_being_off_is_not_an_error(
    project_with_two_notices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem SMTP configurado o portal segue funcionando — o aviso já está lá dentro."""
    _, project_id, _ = project_with_two_notices

    def _disabled(settings, message: EmailMessage) -> None:
        raise mailer.MailerDisabled("desligado")

    monkeypatch.setattr(mailer, "send", _disabled)

    assert worker.send_project_digests(str(project_id)) == {"sent": 0, "notifications": 2}
