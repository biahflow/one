"""O limite de taxa do chat, pelo stack HTTP real (Fase 5, ADR 0021).

O ``threat-model.md`` prometia "rate limit, quotas e auditoria" para abuso de
chat desde a Fase 1 e nada disso existia. O que estes testes fixam não é o
número: é a **razão** dele. Cada lacuna grava uma pendência, uma linha de
auditoria e enfileira uma notificação, então a ameaça é a enxurrada na caixa do
time interno, não a conta de token — e é por isso que o caso central aqui é o
segundo: a requisição recusada não pode deixar rastro nenhum.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from portal_api import chat_limit
from portal_api.auth import bearer_principal
from portal_api.config import get_settings
from portal_api.main import app
from portal_api.models import (
    ChatRateWindow,
    Conversation,
    ConversationMessage,
    MemberRole,
    Membership,
    Organization,
    PendingItem,
    Project,
    ProjectStatus,
    User,
)
from portal_api.principal import Principal

pytestmark = pytest.mark.integration

client = TestClient(app)

QUESTION = "Qual é o status do projeto?"


@dataclass(frozen=True)
class Asker:
    organization_id: uuid.UUID
    project_id: uuid.UUID
    subject: str
    email: str


@pytest.fixture
def asker(migrated_engine: Engine) -> Iterator[Asker]:
    tag = uuid.uuid4().hex[:8]
    subject = f"sub-limite-{tag}"
    email = f"limite-{tag}@example.com"
    with Session(migrated_engine) as session:
        organization = Organization(name="Acme Limite", slug=f"limite-{tag}")
        session.add(organization)
        session.flush()
        project = Project(
            organization_id=organization.id,
            name="Automação",
            slug=f"limite-project-{tag}",
            status=ProjectStatus.in_implementation,
            completion_percent=50,
        )
        session.add(project)
        user = User(email=email, full_name="Quem Pergunta", external_subject=subject)
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
        session.commit()
        made = Asker(organization.id, project.id, subject, email)

    app.dependency_overrides[bearer_principal] = lambda: Principal(
        subject=subject,
        email=email,
        full_name="Quem Pergunta",
        realm_roles=frozenset({"client_member"}),
    )
    try:
        yield made
    finally:
        app.dependency_overrides.clear()
        with Session(migrated_engine) as cleanup:
            cleanup.execute(delete(ChatRateWindow).where(ChatRateWindow.subject == subject))
            cleanup.execute(delete(Conversation).where(Conversation.project_id == made.project_id))
            cleanup.execute(delete(PendingItem).where(PendingItem.project_id == made.project_id))
            cleanup.commit()


@pytest.fixture
def limit_of(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], None]:
    """Baixa o limite no singleton já cacheado, como faz o teste da API de eventos."""

    def _set(value: int) -> None:
        monkeypatch.setattr(get_settings(), "chat_rate_limit", value)

    return _set


def _ask() -> int:
    return client.post("/api/v1/chat", json={"question": QUESTION}).status_code


def _counts(engine: Engine, project_id: uuid.UUID) -> tuple[int, int]:
    with Session(engine) as check:
        pendings = check.execute(
            select(func.count()).select_from(PendingItem).where(
                PendingItem.project_id == project_id
            )
        ).scalar_one()
        messages = check.execute(
            select(func.count()).select_from(ConversationMessage).where(
                ConversationMessage.project_id == project_id
            )
        ).scalar_one()
    return pendings, messages


def test_the_chat_answers_429_past_the_window_limit(asker: Asker, limit_of) -> None:
    limit_of(2)

    assert _ask() == 200
    assert _ask() == 200
    assert _ask() == 429


def test_a_refused_turn_writes_no_pendencia_and_no_message(
    asker: Asker, limit_of, migrated_engine: Engine
) -> None:
    """A propriedade que importa, e a razão de o limite existir.

    Um 429 que ainda gravasse pendência teria fechado o buraco errado: a ameaça
    é a enxurrada na caixa do time interno, não a conta de token.
    """
    limit_of(1)
    assert _ask() == 200
    before = _counts(migrated_engine, asker.project_id)

    assert _ask() == 429

    assert _counts(migrated_engine, asker.project_id) == before


def test_the_429_carries_retry_after(asker: Asker, limit_of) -> None:
    """Não é opaco de propósito: ritmo e permissão são recusas diferentes."""
    limit_of(1)
    _ask()

    response = client.post("/api/v1/chat", json={"question": QUESTION})

    assert response.status_code == 429
    retry_after = int(response.headers["Retry-After"])
    assert 1 <= retry_after <= int(chat_limit.WINDOW.total_seconds())


def test_the_window_rolls_over(asker: Asker, limit_of, migrated_engine: Engine) -> None:
    """Envelhecer a linha em vez de dormir — como o teste da API de eventos."""
    limit_of(1)
    assert _ask() == 200
    assert _ask() == 429

    with Session(migrated_engine) as aged:
        window = aged.execute(
            select(ChatRateWindow).where(ChatRateWindow.subject == asker.subject)
        ).scalar_one()
        window.window_started_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        aged.commit()

    assert _ask() == 200


def test_the_window_belongs_to_the_person_and_not_to_the_project(
    asker: Asker, limit_of, migrated_engine: Engine
) -> None:
    """Uma linha por `sub`, sem tenant — senão N projetos seriam N cotas."""
    limit_of(5)
    _ask()

    with Session(migrated_engine) as check:
        rows = list(
            check.execute(
                select(ChatRateWindow).where(ChatRateWindow.subject == asker.subject)
            ).scalars()
        )

    assert len(rows) == 1
    assert not hasattr(rows[0], "project_id")
    assert not hasattr(rows[0], "organization_id")


def test_the_request_path_cannot_read_the_window(
    asker: Asker, limit_of, rls_session: Session
) -> None:
    """RLS ligada e nenhuma policy `TO portal_app`: a regra não é sobre você.

    Mesma forma de `agent_api_key` e `project_drive_connection` — o papel de
    requisição herda o SELECT das default privileges e mesmo assim lê zero
    linhas, porque nenhuma policy se aplica a ele.
    """
    limit_of(5)
    _ask()

    visible = rls_session.execute(
        select(func.count()).select_from(ChatRateWindow)
    ).scalar_one()

    assert visible == 0
