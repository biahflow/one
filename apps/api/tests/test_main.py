from typing import Any

import pytest
from fastapi.testclient import TestClient

from portal_api import main
from portal_api.auth import bearer_principal
from portal_api.main import app
from portal_api.principal import Principal

client = TestClient(app)
PROJECT_ID = "019f881c-4613-79a2-a277-062ebe43f70e"


def _agent_event(**overrides: Any) -> dict[str, Any]:
    return {
        "event_id": "019f881c-4613-79a2-a277-062ebe43f70e",
        "project_id": PROJECT_ID,
        "occurred_at": "2026-08-03",
        "agent_key": "finance-agent",
        "time_saved_seconds": 120,
        "avoided_cost_cents": 0,
        "run_reference": "run-001",
        **overrides,
    }


def test_health_is_available() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "portal-api"}


def test_demo_dashboard_has_expected_project_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    # The gate is the point of the endpoint, so the test turns it on explicitly
    # instead of relying on DEMO_MODE being set in the environment.
    monkeypatch.setattr(main.settings, "demo_mode", True)

    response = client.get("/api/v1/dashboard/demo")

    assert response.status_code == 200
    body = response.json()
    assert body["completion"] == 68
    assert body["roi_percent"] == 142
    assert body["hours_saved"] == 328


def test_chat_requires_a_token() -> None:
    # Sem `Authorization: Bearer` não há principal (ADR 0002/0007/0010).
    response = client.post(
        "/api/v1/chat",
        json={"question": "Qual é a política de retenção?"},
    )
    assert response.status_code == 401


def test_agent_event_requires_a_token() -> None:
    """Era anônimo sob DEMO_MODE; agora exige token e papel interno (ADR 0010)."""
    response = client.post("/api/v1/agent-events", json=_agent_event())

    assert response.status_code == 401


def test_agent_event_rejects_invalid_metrics() -> None:
    # A validação do corpo só é alcançável depois do gate de autenticação, então
    # o principal é injetado para que o 422 continue sendo o que o teste observa.
    app.dependency_overrides[bearer_principal] = lambda: Principal(
        subject="sub-internal", email="ops@portal.test", full_name="Ops"
    )
    try:
        response = client.post(
            "/api/v1/agent-events", json=_agent_event(time_saved_seconds=-1)
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
