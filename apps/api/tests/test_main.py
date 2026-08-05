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


def test_readiness_answers_ready_or_down_and_nothing_else() -> None:
    """A prontidão é pública de propósito, então o corpo é sim/não (ADR 0018).

    O caso negativo da regra 6 do `AGENTS.md` para esta rota não é "quem pode
    chamá-la" — qualquer um pode, é uma sonda — e sim **o que ela conta**. Sem
    versão, sem hostname, sem DSN, sem o nome da dependência que caiu e sem a
    mensagem do driver: um `down` é indistinguível de outro, como o 401 opaco
    da `auth.py`. Vale com banco no ar (200) e sem (503), por isso o teste
    aceita os dois status e olha só o conteúdo.
    """
    response = client.get("/health/ready")

    assert response.status_code in (200, 503)
    body = response.json()
    assert set(body) == {"status"}
    assert body["status"] in ("ready", "down")

    raw = response.text.lower()
    for leak in ("postgres", "psycopg", "redis://", "password", "5432", "traceback"):
        assert leak not in raw


def test_every_response_carries_a_trace_id() -> None:
    """O eco do header é o que permite a quem chamou citar o id ao suporte."""
    response = client.get("/health")

    assert response.headers["X-Request-ID"]


def test_an_inbound_trace_id_is_preserved_end_to_end() -> None:
    response = client.get("/health", headers={"X-Request-ID": "vindo-do-bff"})

    assert response.headers["X-Request-ID"] == "vindo-do-bff"


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


def test_a_422_says_what_is_wrong_without_echoing_what_was_sent() -> None:
    """Nenhum 422 devolve o corpo da requisição (ADR 0023).

    A propriedade é de toda a aplicação — o handler é registrado no ``app``, não
    numa rota — e a de eventos é só o lugar mais barato de observá-la, porque um
    `Principal` injetado já chega à validação do corpo. Quem torna a propriedade
    necessária é outra rota: `DriveCallbackIn` carrega o authorization code do
    Google no corpo, e o FastAPI 0.141 passou a ecoar o corpo inteiro em
    ``input``.

    O teste afirma os dois lados. Só "o segredo não sai" deixaria passar um
    handler que devolvesse ``{"detail": []}`` — que não vaza nada e também não
    diz a ninguém o que consertar.
    """
    app.dependency_overrides[bearer_principal] = lambda: Principal(
        subject="sub-internal", email="ops@portal.test", full_name="Ops"
    )
    try:
        response = client.post(
            "/api/v1/agent-events",
            json=_agent_event(run_reference="conteudo-que-nao-deveria-voltar", time_saved_seconds=-1),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "nao-deveria-voltar" not in response.text
    detail = response.json()["detail"]
    assert detail, "um 422 sem nenhum item não diz o que está errado"
    for item in detail:
        assert set(item) == {"type", "loc", "msg"}
    assert any("time_saved_seconds" in item["loc"] for item in detail)
