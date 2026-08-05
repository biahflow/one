"""O `trace_id` e o log estruturado (Fase 5, ADR 0018).

Unitário e sem banco: o que se prova aqui é que o identificador atravessa as
bordas (HTTP e fila) e que os campos chegam ao stdout. O primeiro teste do
arquivo é uma **regressão**, não um recurso novo — `auth.rejected` já logava
`reason` desde a ADR 0010 e o runbook de eventos já mandava lê-lo, mas sem
formatter configurado o campo nunca era impresso.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from celery import Celery
from celery.signals import before_task_publish
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Importado pelo efeito colateral: é o `import` que conecta os sinais que ligam
# o `trace_id` à fila. Sem ele, o teste da fila provaria apenas que o Celery
# publica mensagens.
from portal_api.worker import _publish_trace_id  # noqa: F401
from portal_api.telemetry import (
    TRACE_HEADER,
    JsonFormatter,
    TextFormatter,
    TraceMiddleware,
    audit_data,
    bind_trace_id,
    clear_trace_id,
    current_trace_id,
)


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("portal_api.test", logging.WARNING, __file__, 1, msg, None, None)
    record.__dict__.update(extra)
    return record


# --------------------------------------------------------------------------- #
# Formatter
# --------------------------------------------------------------------------- #


def test_extra_fields_reach_the_line() -> None:
    """A regressão que motivou a ADR 0018.

    `docs/runbooks/agent-events-failure.md` manda ler `reason` e `key_prefix` de
    um `agent_key.rejected`. Com o formato padrão do `logging` a linha saía com
    o nome do evento e nada mais.
    """
    payload = json.loads(
        JsonFormatter().format(_record("agent_key.rejected", reason="revoked", key_prefix="pk_ab12"))
    )

    assert payload["event"] == "agent_key.rejected"
    assert payload["reason"] == "revoked"
    assert payload["key_prefix"] == "pk_ab12"
    assert payload["level"] == "WARNING"


def test_secret_looking_fields_are_redacted() -> None:
    """Regra 5 do `AGENTS.md` cumprida no código, e não só na prosa."""
    payload = json.loads(
        JsonFormatter().format(
            _record(
                "keycloak.failed",
                access_token="ey.real.secret",
                refresh_token="1//real",
                client_secret="s3cr3t",
                password="hunter2",
                what="find_by_email",
            )
        )
    )

    assert payload["access_token"] == "[redacted]"
    assert payload["refresh_token"] == "[redacted]"
    assert payload["client_secret"] == "[redacted]"
    assert payload["password"] == "[redacted]"
    # O que não é segredo continua legível, senão a redação teria comido o log.
    assert payload["what"] == "find_by_email"


def test_key_prefix_survives_the_redaction() -> None:
    """A allowlist é obrigatória, não uma conveniência.

    O prefixo é a parte pública da credencial — é justamente o que fica em claro
    no banco — e o runbook depende dele para dizer *qual* chave foi recusada.
    Sem a exceção, "key" no nome apagaria o campo e o runbook voltaria a
    descrever algo que não existe.
    """
    payload = json.loads(JsonFormatter().format(_record("agent_key.rejected", key_prefix="pk_ab12")))

    assert payload["key_prefix"] == "pk_ab12"


def test_text_format_also_keeps_the_fields() -> None:
    """O formato legível é outro formato, não outro conteúdo."""
    line = TextFormatter("%(levelname)s %(name)s %(message)s").format(
        _record("auth.rejected", reason="expired", access_token="ey.real")
    )

    assert "auth.rejected" in line
    assert "reason=expired" in line
    assert "ey.real" not in line
    assert "access_token=[redacted]" in line


def test_trace_id_of_the_context_lands_on_the_line() -> None:
    bind_trace_id("abc123")
    try:
        payload = json.loads(JsonFormatter().format(_record("http.request")))
    finally:
        clear_trace_id()

    assert payload["trace_id"] == "abc123"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


def _app_that_logs(seen: list[str]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceMiddleware)

    @app.get("/thing/{thing_id}")
    def thing(thing_id: str) -> dict[str, str]:
        # O ponto do teste: um handler qualquer enxerga o id sem recebê-lo.
        seen.append(current_trace_id())
        return {"id": thing_id}

    return app


def test_inbound_trace_id_is_honoured_and_echoed() -> None:
    """O id do BFF é o que vale — é o que faz a linha do `web` e a do `api`
    contarem a mesma história."""
    seen: list[str] = []
    client = TestClient(_app_that_logs(seen))

    response = client.get("/thing/42", headers={TRACE_HEADER: "from-the-bff"})

    assert response.status_code == 200
    assert response.headers[TRACE_HEADER] == "from-the-bff"
    assert seen == ["from-the-bff"]


def test_a_request_without_the_header_still_gets_an_id() -> None:
    seen: list[str] = []
    client = TestClient(_app_that_logs(seen))

    response = client.get("/thing/42")

    assert response.headers[TRACE_HEADER]
    assert seen[0] == response.headers[TRACE_HEADER]


def test_two_requests_do_not_share_an_id() -> None:
    """A ``ContextVar`` é por requisição; uma variável de módulo daria o mesmo id
    a pessoas diferentes no mesmo processo."""
    seen: list[str] = []
    client = TestClient(_app_that_logs(seen))

    client.get("/thing/1")
    client.get("/thing/2")

    assert seen[0] != seen[1]


@contextmanager
def captured(name: str = "portal_api.telemetry") -> Iterator[list[logging.LogRecord]]:
    """Escuta um logger sem depender do estado global do ``logging``.

    O ``caplog`` do pytest e o nível herdado da raiz não servem aqui: rodar a
    suíte inteira faz o Celery reconfigurar o logging da raiz ao executar uma
    task, e os dois testes abaixo passavam sozinhos e falhavam em conjunto. Um
    handler próprio, com nível fixado e restaurado no fim, torna a asserção
    independente de quem rodou antes.
    """
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger = logging.getLogger(name)
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def test_access_log_carries_the_route_template_and_not_the_url() -> None:
    """O path traz id de projeto e de documento; a rota responde "que endpoint
    está lento" sem eles, e sem deixar um terceiro escrever no log."""
    seen: list[str] = []
    client = TestClient(_app_that_logs(seen))

    with captured() as records:
        client.get("/thing/019f881c-4613-79a2-a277-062ebe43f70e?secret=shhh")

    lines = [r for r in records if r.getMessage() == "http.request"]
    assert len(lines) == 1
    assert lines[0].route == "/thing/{thing_id}"
    assert "019f881c" not in lines[0].route
    assert "shhh" not in lines[0].route
    assert lines[0].status == 200


def test_an_unmatched_path_is_never_echoed() -> None:
    """404 é o caminho onde quem chama escolhe a string. Ele não entra no log."""
    seen: list[str] = []
    client = TestClient(_app_that_logs(seen))

    with captured() as records:
        client.get("/nao-existe/<script>")

    routes = [r.route for r in records if r.getMessage() == "http.request"]
    assert routes == ["unmatched"]


# --------------------------------------------------------------------------- #
# Fila
# --------------------------------------------------------------------------- #


def test_the_trace_id_crosses_the_queue_as_a_message_header() -> None:
    """Em header, nunca em argumento (ADR 0018).

    Prova as duas pontas do par de sinais: quem publica carimba o id da
    requisição em curso, e quem consome o encontra em ``request.headers`` —
    sem que a assinatura da task mude.
    """
    published: list[dict] = []

    app = Celery("test_telemetry", broker="memory://", backend="cache+memory://")

    @app.task(name="test_telemetry.noop")
    def noop() -> str:  # pragma: no cover - o corpo não importa aqui
        return "ok"

    def capture(headers=None, **_kwargs) -> None:
        # O handler do worker roda primeiro (o `import` do módulo o conectou);
        # aqui só observamos o resultado.
        published.append(dict(headers or {}))

    before_task_publish.connect(capture, weak=False)
    bind_trace_id("trace-da-requisicao")
    try:
        noop.apply_async()
    finally:
        before_task_publish.disconnect(capture)
        clear_trace_id()

    assert published, "o sinal de publicação não disparou"
    assert published[0][TRACE_HEADER] == "trace-da-requisicao"


def test_a_publication_outside_a_request_stamps_nothing() -> None:
    """Sem pai, o consumidor cunha o próprio — carimbar aqui daria dois ids
    para a mesma execução."""
    headers: dict = {}
    clear_trace_id()

    assert current_trace_id() == ""

    _publish_trace_id(headers=headers)

    assert TRACE_HEADER not in headers


# --------------------------------------------------------------------------- #
# Auditoria
# --------------------------------------------------------------------------- #


def test_audit_data_stamps_the_trace_id() -> None:
    """O que torna verdadeira a primeira linha do runbook de incidente."""
    bind_trace_id("trace-da-acao")
    try:
        data = audit_data(reason="insufficient_context")
    finally:
        clear_trace_id()

    assert data == {"reason": "insufficient_context", "trace_id": "trace-da-acao"}


def test_audit_data_outside_a_request_omits_the_field() -> None:
    """Ausente é melhor que vazio: uma linha antiga e uma linha de fora de
    requisição ficam iguais, em vez de a segunda alegar um id que não existe."""
    clear_trace_id()

    assert audit_data(reason="x") == {"reason": "x"}
