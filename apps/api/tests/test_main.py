from fastapi.testclient import TestClient

from portal_api.main import app

client = TestClient(app)
PROJECT_ID = "019f881c-4613-79a2-a277-062ebe43f70e"


def test_health_is_available() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "portal-api"}


def test_demo_dashboard_has_expected_project_metrics() -> None:
    response = client.get("/api/v1/dashboard/demo")

    assert response.status_code == 200
    body = response.json()
    assert body["completion"] == 68
    assert body["roi_percent"] == 142
    assert body["hours_saved"] == 328


def test_chat_requires_client_identity() -> None:
    # Sem X-Portal-User o chat não é autorizado (escopo por tenant, ADR 0002/0007).
    response = client.post(
        "/api/v1/chat",
        json={"question": "Qual é a política de retenção?"},
    )
    assert response.status_code == 401


def test_agent_event_rejects_invalid_metrics() -> None:
    response = client.post(
        "/api/v1/agent-events",
        json={
            "event_id": "019f881c-4613-79a2-a277-062ebe43f70e",
            "project_id": PROJECT_ID,
            "occurred_at": "2026-08-03",
            "agent_key": "finance-agent",
            "time_saved_seconds": -1,
            "avoided_cost_cents": 0,
            "run_reference": "run-001",
        },
    )

    assert response.status_code == 422
