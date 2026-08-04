"""A rota de eventos dos agentes, ponta a ponta (Fase 3, ADR 0013).

Só o banco é real aqui — não há principal a forjar, porque a rota não usa
sessão de usuário. O que autentica é a chave, e é ela que os testes exercitam:
ausente, desconhecida, revogada, expirada, sem escopo, de outro projeto, e no
ritmo errado.

As recusas de credencial são todas o **mesmo 401**, e é isso que os testes
afirmam: uma resposta que distinguisse "expirada" de "inexistente" seria um
oráculo para quem estivesse sondando.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from portal_api.main import app
from portal_api.models import AgentEvent, AgentEventOutcome, AuditLog, Organization, Project

pytestmark = pytest.mark.integration

client = TestClient(app)


@dataclass(frozen=True)
class Tenant:
    organization_id: uuid.UUID
    project_id: uuid.UUID


@pytest.fixture
def tenant(migrated_engine: Engine) -> Iterator[Tenant]:
    tag = uuid.uuid4().hex[:8]
    with Session(migrated_engine) as session:
        organization = Organization(name="Events", slug=f"events-{tag}")
        session.add(organization)
        session.flush()
        project = Project(
            organization_id=organization.id, name="Automação", slug=f"auto-{tag}"
        )
        session.add(project)
        session.commit()
        created = Tenant(organization.id, project.id)

    yield created

    with Session(migrated_engine) as session:
        # CASCADE na organização leva projeto, eventos, chaves e auditoria junto.
        session.delete(session.get(Organization, created.organization_id))
        session.commit()


def _body(tenant: Tenant, **overrides) -> dict:
    body = {
        "event_id": str(uuid.uuid4()),
        "project_id": str(tenant.project_id),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "agent_key": "finance-agent",
        "time_saved_seconds": 1_800,
        "avoided_cost_cents": 2_500,
        "run_reference": "run-042",
    }
    body.update(overrides)
    return body


def _post(body: dict, key: str | None = None):
    headers = {"X-Agent-Key": key} if key else {}
    return client.post("/api/v1/agent-events", json=body, headers=headers)


# --- idempotência ----------------------------------------------------------


def test_the_same_event_resent_does_not_duplicate(
    tenant: Tenant, agent_key, migrated_engine: Engine
) -> None:
    """O aceite da fase: reenvio não duplica resultado."""
    key = agent_key(tenant)
    body = _body(tenant)

    first = _post(body, key)
    again = _post(body, key)

    assert (first.status_code, again.status_code) == (202, 202)
    assert first.json()["status"] == "accepted"
    # O produtor precisa saber qual das duas coisas aconteceu para depurar o
    # pipeline dele, sem que a segunda tenha efeito nenhum.
    assert again.json()["status"] == "duplicate"

    with Session(migrated_engine) as session:
        stored = session.execute(
            select(AgentEvent).where(AgentEvent.project_id == tenant.project_id)
        ).scalars().all()
    assert len(stored) == 1
    assert stored[0].time_saved_seconds == 1_800
    assert stored[0].avoided_cost_cents == 2_500


def test_the_event_is_stored_exactly_as_reported(
    tenant: Tenant, agent_key, migrated_engine: Engine
) -> None:
    key = agent_key(tenant)

    _post(
        _body(tenant, outcome="exception_handled", human_intervention=True),
        key,
    )

    with Session(migrated_engine) as session:
        stored = session.execute(
            select(AgentEvent).where(AgentEvent.project_id == tenant.project_id)
        ).scalars().one()
    assert stored.outcome is AgentEventOutcome.exception_handled
    assert stored.human_intervention is True
    assert stored.agent_key == "finance-agent"
    assert stored.run_reference == "run-042"


# --- a credencial ----------------------------------------------------------


def test_without_a_key_the_route_is_shut(tenant: Tenant) -> None:
    assert _post(_body(tenant)).status_code == 401


def test_an_unknown_key_is_rejected(tenant: Tenant, agent_pepper: str) -> None:
    assert _post(_body(tenant), "plk_nao-existe-nenhuma-chave-assim").status_code == 401


def test_a_revoked_key_is_rejected(tenant: Tenant, agent_key) -> None:
    key = agent_key(tenant, revoked=True)
    assert _post(_body(tenant), key).status_code == 401


def test_an_expired_key_is_rejected(tenant: Tenant, agent_key) -> None:
    key = agent_key(tenant, expires_in_days=-1)
    assert _post(_body(tenant), key).status_code == 401


def test_a_key_without_the_scope_is_rejected(tenant: Tenant, agent_key) -> None:
    key = agent_key(tenant, scopes=["results:read"])
    assert _post(_body(tenant), key).status_code == 401


def test_every_refusal_looks_the_same(tenant: Tenant, agent_key) -> None:
    """Recusar de formas distinguíveis transformaria a rota em oráculo.

    "Esta chave existiu e expirou" é informação para quem está sondando; o
    motivo real vive no log estruturado, não na resposta.
    """
    bodies = [
        _post(_body(tenant), agent_key(tenant, revoked=True)),
        _post(_body(tenant), agent_key(tenant, expires_in_days=-1)),
        _post(_body(tenant), agent_key(tenant, scopes=[])),
        _post(_body(tenant), "plk_desconhecida-de-todo"),
    ]

    assert {response.status_code for response in bodies} == {401}
    assert {response.json()["detail"] for response in bodies} == {"Not authenticated"}


def test_a_key_cannot_publish_into_another_project(
    tenant: Tenant, agent_key, migrated_engine: Engine
) -> None:
    """Quem responde "qual projeto" é a chave, não o corpo — e discordar é 404."""
    key = agent_key(tenant)

    response = _post(_body(tenant, project_id=str(uuid.uuid4())), key)

    assert response.status_code == 404
    with Session(migrated_engine) as session:
        assert session.execute(select(AgentEvent)).scalars().all() == []


# --- ritmo -----------------------------------------------------------------


def test_going_over_the_window_answers_429(
    tenant: Tenant, agent_key, monkeypatch: pytest.MonkeyPatch
) -> None:
    """429 e não 401: o produtor precisa distinguir ritmo de credencial."""
    from portal_api.config import get_settings

    monkeypatch.setattr(get_settings(), "agent_events_rate_limit", 2)
    key = agent_key(tenant)

    accepted = [_post(_body(tenant), key) for _ in range(2)]
    limited = _post(_body(tenant), key)

    assert [response.status_code for response in accepted] == [202, 202]
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]


def test_a_new_window_lets_the_producer_through_again(
    tenant: Tenant, agent_key, monkeypatch: pytest.MonkeyPatch, migrated_engine: Engine
) -> None:
    from portal_api.config import get_settings
    from portal_api.models import AgentApiKey

    monkeypatch.setattr(get_settings(), "agent_events_rate_limit", 1)
    key = agent_key(tenant)

    assert _post(_body(tenant), key).status_code == 202
    assert _post(_body(tenant), key).status_code == 429

    # Envelhece a janela em vez de dormir um minuto no teste.
    with Session(migrated_engine) as session:
        record = session.execute(select(AgentApiKey)).scalars().one()
        record.window_started_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        session.commit()

    assert _post(_body(tenant), key).status_code == 202


# --- rastro ----------------------------------------------------------------


def test_the_audit_entry_carries_no_secret(
    tenant: Tenant, agent_key, migrated_engine: Engine
) -> None:
    """`docs/data-classification.md` proíbe segredo no log de auditoria."""
    key = agent_key(tenant)

    _post(_body(tenant), key)

    with Session(migrated_engine) as session:
        entry = session.execute(
            select(AuditLog).where(AuditLog.project_id == tenant.project_id)
        ).scalars().one()
    assert entry.action == "agent_event.ingested"
    serialized = f"{entry.data}"
    assert key not in serialized
    assert "plk_" not in serialized


def test_a_duplicate_does_not_write_a_second_audit_entry(
    tenant: Tenant, agent_key, migrated_engine: Engine
) -> None:
    key = agent_key(tenant)
    body = _body(tenant)

    _post(body, key)
    _post(body, key)

    with Session(migrated_engine) as session:
        entries = session.execute(
            select(AuditLog).where(AuditLog.project_id == tenant.project_id)
        ).scalars().all()
    assert len(entries) == 1


def test_using_a_key_stamps_last_used(
    tenant: Tenant, agent_key, migrated_engine: Engine
) -> None:
    from portal_api.models import AgentApiKey

    key = agent_key(tenant)
    _post(_body(tenant), key)

    with Session(migrated_engine) as session:
        record = session.execute(select(AgentApiKey)).scalars().one()
    assert record.last_used_at is not None
