"""O `trace_id` e o log estruturado (Fase 5, ADR 0018).

Unitário e sem banco: o que se prova aqui é que o identificador atravessa as
bordas (HTTP e fila) e que os campos chegam ao stdout. O primeiro teste do
arquivo é uma **regressão**, não um recurso novo — `auth.rejected` já logava
`reason` desde a ADR 0010 e o runbook de eventos já mandava lê-lo, mas sem
formatter configurado o campo nunca era impresso.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import portal_api
from celery import Celery
from celery.signals import before_task_publish
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Importado pelo efeito colateral: é o `import` que conecta os sinais que ligam
# o `trace_id` à fila. Sem ele, o teste da fila provaria apenas que o Celery
# publica mensagens.
from conftest import captured
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




def test_access_log_carries_the_route_template_and_not_the_url() -> None:
    """O path traz id de projeto e de documento; a rota responde "que endpoint
    está lento" sem eles, e sem deixar um terceiro escrever no log."""
    seen: list[str] = []
    client = TestClient(_app_that_logs(seen))

    with captured("portal_api.telemetry") as records:
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

    with captured("portal_api.telemetry") as records:
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


# --------------------------------------------------------------------------- #
# Os campos do chat (Fase 5, ADR 0021)
# --------------------------------------------------------------------------- #


def test_the_chat_stamp_fields_survive_the_formatter() -> None:
    """Nenhum dos campos novos cai na heurística de segredo.

    A lista de `_SECRET_HINTS` casa por substring — `key` derruba `agent_key`,
    `monkey` e o que mais aparecer —, então acrescentar campo de log a este
    repositório pede conferir que ele sai. Sem isto, o `ai-provider-failure.md`
    voltaria a mandar ler um campo que não sai, que é a regressão que a ADR 0018
    existe para não repetir.

    *Que os eventos sejam de fato emitidos* é provado onde o cenário mora:
    `test_chat_ai.py` derruba o provedor e lê o log no mesmo teste em que afirma
    que a resposta virou lacuna.
    """
    payload = json.loads(
        JsonFormatter().format(
            _record(
                "chat.provider_unavailable",
                responder="anthropic",
                model="claude-opus-5",
                reason="ProviderRefused",
            )
        )
    )

    assert payload["event"] == "chat.provider_unavailable"
    assert payload["responder"] == "anthropic"
    assert payload["model"] == "claude-opus-5"
    assert payload["reason"] == "ProviderRefused"


def test_the_stuck_client_fields_survive_the_formatter() -> None:
    """O mesmo cuidado para o alerta do funil (ADR 0040), e ele tem armadilha própria.

    `alerts.md` promete que o limiar de `onboarding.client_stuck` é lido por
    `organization_id`, e que a linha diz o degrau e de quem é a vez. Nenhum desses nomes
    pode cair na redaction — e a tentação de chamar a memória do alerta de `dedupe_key` ou
    `alert_key` foi recusada justamente aqui: `key` é uma das substrings de `_SECRET_HINTS`,
    e o campo sairia `[redacted]` sem nada ficar vermelho.
    """
    payload = json.loads(
        JsonFormatter().format(
            _record(
                "onboarding.client_stuck",
                organization_id="0f6f0b4e-0000-4000-8000-000000000000",
                step="first_login",
                days_stuck=9,
                blocked_by="client",
                threshold_days=7,
            )
        )
    )

    assert payload["event"] == "onboarding.client_stuck"
    assert payload["organization_id"] == "0f6f0b4e-0000-4000-8000-000000000000"
    assert payload["step"] == "first_login"
    assert payload["days_stuck"] == 9
    assert payload["blocked_by"] == "client"
    assert payload["threshold_days"] == 7


def test_the_answered_event_carries_the_prompt_version() -> None:
    payload = json.loads(
        JsonFormatter().format(
            _record(
                "chat.answered",
                prompt_version="chat-2026-08-06",
                responder="offline",
                confidence="grounded",
                citations=2,
            )
        )
    )

    assert payload["prompt_version"] == "chat-2026-08-06"
    assert payload["confidence"] == "grounded"
    assert payload["citations"] == 2


def test_the_rate_limit_event_shows_only_the_prefix_of_the_subject() -> None:
    """O `sub` inteiro é identificador estável de pessoa; o log não precisa dele.

    Mesmo tratamento que o `key_prefix` recebe no runbook da API de eventos: o
    bastante para saber *quem* está em loop, sem virar um rastro por pessoa.
    """
    payload = json.loads(
        JsonFormatter().format(
            _record("chat.rate_limited", subject_prefix="a1b2c3d4", limit=20)
        )
    )

    assert payload["subject_prefix"] == "a1b2c3d4"
    assert payload["limit"] == 20


# --------------------------------------------------------------------------- #
# O evento é nomeado, e o runbook o conhece (ADR 0034)
# --------------------------------------------------------------------------- #
#
# As duas guardas desta seção existem porque a correção manual não segurou. A
# ADR 0028 já consertou o `alerts.md` à mão — ele citava `drive.rejected`, que o
# código nunca emitiu — e o arquivo voltou a divergir em dois dias, agora no
# sentido oposto: quatro eventos que o código emite e nenhum documento conhece,
# dois deles controles de segurança disparando.


#: Nome estável de evento: `familia.acontecimento`, minúsculo, sem interpolação.
EVENT_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

SOURCE_ROOT = Path(portal_api.__file__).parent
REPO_ROOT = Path(__file__).resolve().parents[3]
ALERTS = REPO_ROOT / "docs" / "runbooks" / "alerts.md"

#: O BFF tem logger estruturado próprio (`app/lib/log.ts`) e emite eventos que
#: chegam ao mesmo coletor. Até a ADR 0035 esta guarda parava na fronteira do
#: pacote Python, e os quatro eventos do lado web não tinham linha em runbook
#: nenhum — a mesma divergência que a ADR 0034 acabara de fechar do outro lado.
#:
#: A varredura é por expressão regular e não por AST porque é TypeScript, e mora
#: **aqui** em vez de num teste node ao lado: o `alerts.md` é um arquivo só, e
#: duas guardas sobre o mesmo arquivo divergem — que é literalmente o defeito
#: que esta seção existe para impedir. O precedente de teste Python lendo
#: artefato de fora do pacote é o `test_seed_matches_realm.py`.
_WEB_DIRECTORIES = ("app", "components")

#: `app/lib/log.ts` **define** `logInfo`/`logWarn`/`logError`; as ocorrências ali
#: são a assinatura das funções, não sítios de emissão.
_WEB_LOGGER_MODULE = "app/lib/log.ts"

_WEB_LOG_CALL = re.compile(r"\blog(?:Info|Warn|Error)\(\s*([^,)]+)")

#: Módulos cujo `logger` fala com **uma pessoa no terminal**, não com um
#: coletor: são comandos de operação (`python -m portal_api.seed`, o bootstrap
#: da ADR 0025, o `preflight` que recusa a subida, o backup). Ali a prosa é o
#: formato certo, e exigir `familia.acontecimento` tornaria a saída pior para
#: quem a lê. Todo o resto roda dentro de um processo que alguém consulta por
#: `grep '"event":"…"'`.
PROSE_IS_FINE = {
    "grant_access.py": "comando de bootstrap; a saída é lida por quem o executa (ADR 0025)",
    "seed.py": "comando de seed local; idem",
    "preflight.py": "recusa a subida do processo, e a mensagem é o motivo (ADR 0022)",
    "backup.py": "operação, não aplicação — como o `scripts/backup.sh` (ADR 0019)",
}

#: Eventos emitidos que **não** pertencem ao `alerts.md`, com o motivo. Não são
#: exceção à regra do nome: são eventos de curso normal, e o runbook é sobre o
#: que merece limiar. Uma linha aqui é uma afirmação de que ninguém precisa ser
#: avisado disso.
NOT_AN_ALERT = {
    "http.request": "uma linha por requisição; é o substrato, não um alerta",
    "task.started": "curso normal da fila; a **ausência** dele é que alerta, e essa linha existe",
    "task.finished": "idem",
    "chat.answered": "curso normal, e a fonte dos indicadores de IA (`observability.md`)",
    "search.performed": "curso normal da busca (ADR 0024)",
    "auth.rejected": "tem seção própria em `alerts.md`, sob 'não são alerta'",
    "identity.linked": "primeiro login de quem já tinha linha; curso normal",
    "identity.provisioned": "primeiro login de quem não tinha; curso normal",
    "identity.provision_race": (
        "as duas requisições paralelas do primeiro login chegaram juntas e uma releu — "
        "curso normal desde que o BFF busca `/me` e o dashboard ao mesmo tempo, e "
        "**esperado em todo primeiro login** (ADR 0052). Fica no log como evidência de "
        "que a recuperação rodou; alertar seria alertar sobre o desenho"
    ),
    "preflight.ok": "diz que a subida passou; o que interessa é a recusa, e ela impede o boot",
}


def _logger_calls() -> list[tuple[str, int, ast.expr]]:
    """Todo `logger.<nível>(…)` do pacote, com onde ele está."""
    calls: list[tuple[str, int, ast.expr]] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in {"debug", "info", "warning", "error", "exception"}:
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == "logger"):
                continue
            if node.args:
                calls.append((path.name, node.lineno, node.args[0]))
    return calls


def _web_sources() -> list[Path]:
    """Os fontes do BFF: os `.ts` da raiz (`instrumentation.ts`) e `app/`+`components/`."""
    files = [path for path in sorted(REPO_ROOT.glob("*.ts")) if path.is_file()]
    for directory in _WEB_DIRECTORIES:
        root = REPO_ROOT / directory
        if root.is_dir():
            files += sorted(root.rglob("*.ts")) + sorted(root.rglob("*.tsx"))
    return [
        path
        for path in files
        if path.relative_to(REPO_ROOT).as_posix() != _WEB_LOGGER_MODULE
    ]


def _web_log_calls() -> list[tuple[str, int, str]]:
    """Todo `logInfo`/`logWarn`/`logError` do BFF, com o primeiro argumento cru."""
    calls: list[tuple[str, int, str]] = []
    for path in _web_sources():
        relative = path.relative_to(REPO_ROOT).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in _WEB_LOG_CALL.finditer(line):
                calls.append((relative, number, match.group(1).strip()))
    return calls


def _web_event_name(argument: str) -> str | None:
    """O nome, quando o argumento é um literal — `None` quando é template ou variável."""
    if len(argument) >= 2 and argument[0] == '"' and argument[-1] == '"':
        return argument[1:-1]
    return None


def emitted_events() -> set[str]:
    """Os eventos nomeados dos **dois** deployables que falam com o coletor."""
    names = set()
    for _, _, first in _logger_calls():
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            if EVENT_NAME.match(first.value):
                names.add(first.value)
    for _, _, argument in _web_log_calls():
        candidate = _web_event_name(argument)
        if candidate and EVENT_NAME.match(candidate):
            names.add(candidate)
    return names


def test_every_web_log_line_is_a_named_event() -> None:
    """A mesma regra do lado do BFF, e pelo mesmo motivo (ADR 0035).

    `app/lib/log.ts` escreve uma linha JSON com o campo `event`, exatamente como
    o `JsonFormatter`. Um `logWarn(\\`api falhou: ${erro}\\`)` produziria ali o
    mesmo valor irrepetível que os dez sítios em prosa que a ADR 0034 corrigiu no
    Python — e nada impedia, porque a guarda parava na fronteira do pacote.
    """
    offenders = [
        f"{name}:{line}"
        for name, line, argument in _web_log_calls()
        if not (
            (candidate := _web_event_name(argument)) and EVENT_NAME.match(candidate)
        )
    ]

    assert offenders == [], (
        "estas chamadas de log do BFF não usam um nome de evento estável: "
        + ", ".join(offenders)
        + ". A mensagem é o nome (`familia.acontecimento`) e o detalhe vai nos"
        " campos — senão o `event` muda a cada ocorrência (ADR 0018/0034/0035)."
    )


def test_every_log_line_is_a_named_event() -> None:
    """A mensagem **é** o nome do evento; o detalhe vai em `extra`.

    `JsonFormatter` põe `record.getMessage()` — a mensagem já **interpolada** —
    no campo `event`, e o `alerts.md` abre dizendo que "cada linha é um evento
    nomeado (…) a regra é sempre a mesma consulta: filtrar por `event` e contar
    dentro de uma janela". Uma mensagem em prosa com `%s` produz um `event`
    diferente a cada ocorrência: inconsultável, e o limiar do runbook não tem
    como ser aplicado.

    Nasceu vermelha com dez sítios. O mais caro era `scanner.py`, que é o
    **único** sinal de que o antivírus caiu — e é justamente o que o
    `alerts.md` mandava vigiar pelo caminho errado.
    """
    offenders = [
        f"{name}:{line}"
        for name, line, first in _logger_calls()
        if name not in PROSE_IS_FINE
        and not (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and EVENT_NAME.match(first.value)
        )
    ]

    assert offenders == [], (
        "estas chamadas de log não usam um nome de evento estável: "
        + ", ".join(offenders)
        + ". A mensagem é o nome (`familia.acontecimento`) e o detalhe vai em `extra` —"
        " senão o `event` muda a cada ocorrência e o limiar do `alerts.md` não se"
        " aplica (ADR 0018/0034)."
    )


#: Extensões que fazem um nome parecer evento sem ser: `observability.md` casa
#: `familia.acontecimento` perfeitamente. Medido — foi o primeiro falso positivo
#: desta guarda.
_FILE_SUFFIXES = (".md", ".py", ".ts", ".tsx", ".mjs", ".json", ".sh", ".yml", ".sql", ".css")

#: O outro jeito de um identificador pontuado não ser evento, também medido: o
#: runbook cita o **escopo OAuth** que o conector exige, e `drive.readonly` casa
#: o formato tão bem quanto `drive.sync_failed`. Uma linha aqui é a afirmação de
#: que aquele nome não descreve algo que acontece.
_NOT_EVENT_NAMES = {
    "drive.readonly": "escopo do consentimento do Google, não um evento (ADR 0016)",
}

#: A nota histórica do repositório, que esta guarda **não** pode ler como
#: instrução. Não é estilo e foi medido: o `alerts.md` cita `drive.rejected`
#: dentro da própria nota que registra a correção da ADR 0028 ("esta linha dizia
#: `drive.rejected`, que o código **nunca emitiu**"). Uma guarda ingênua sobre o
#: arquivo cobraria que o repositório apagasse o registro do próprio erro —
#: exatamente a memória que faz estas ADRs valerem alguma coisa.
#:
#: A marcação já existia como convenção de escrita; aqui ela vira executável.
_HISTORICAL_NOTE = re.compile(r"\*(Corrigido|Acrescentado) em [\s\S]*?\*(?!\*)")


def _events_named_in_the_runbook() -> set[str]:
    """Os eventos que o `alerts.md` manda vigiar hoje.

    Tabelas **e** a seção "não são alerta", que é lista — e cuja inclusão é o
    ponto: é lá que moram `auth.rejected` e a fronteira do Drive, que são
    instrução viva tanto quanto uma linha de tabela.
    """
    text = _HISTORICAL_NOTE.sub("", ALERTS.read_text(encoding="utf-8"))
    return {
        candidate
        for candidate in re.findall(r"`([a-z][a-z0-9_.]+)`", text)
        if EVENT_NAME.match(candidate)
        and not candidate.endswith(_FILE_SUFFIXES)
        and candidate not in _NOT_EVENT_NAMES
    }


def test_every_named_event_has_a_line_in_the_runbook() -> None:
    """O código não emite evento que o runbook desconheça.

    Esta é a direção que divergiu **depois** de a ADR 0028 consertar a outra à
    mão, e os dois piores casos eram controles de segurança disparando:
    `drive.scope_refused` (o Google concedeu escopo diferente de
    `drive.readonly` e a conexão foi recusada) e `document.infected_object_kept`
    (malware confirmado que **não saiu do bucket** — estritamente pior que o
    `document.infected` que já acorda alguém, e anônimo).
    """
    documented = _events_named_in_the_runbook()
    orphans = sorted(e for e in emitted_events() if e not in documented and e not in NOT_AN_ALERT)

    assert orphans == [], (
        "estes eventos são emitidos e não têm linha em `docs/runbooks/alerts.md`: "
        + ", ".join(orphans)
        + ". Dê limiar e destino a cada um, ou declare em NOT_AN_ALERT por que ninguém"
        " precisa ser avisado (ADR 0034)."
    )


def test_every_event_the_runbook_names_is_emitted() -> None:
    """E o runbook não manda vigiar evento que não existe.

    É exatamente o defeito que a ADR 0028 encontrou e consertou à mão. Sem esta
    asserção, o conserto vale até o próximo alguém — que foi o que aconteceu.
    """
    emitted = emitted_events()
    # Até a ADR 0035 havia aqui um `elsewhere = {"web.request_error"}`: o evento
    # era emitido pelo BFF, que esta guarda não enxergava. Agora enxerga, e a
    # exceção saiu — a assimetria era o defeito, como no `health.broker_unavailable`.
    ghosts = sorted(e for e in _events_named_in_the_runbook() if e not in emitted)

    assert ghosts == [], (
        "o `alerts.md` manda vigiar estes eventos e nenhum código os emite: "
        + ", ".join(ghosts)
        + ". Emita-os, ou tire a linha — um limiar sobre um contador pinado em zero"
        " é pior que nenhum, porque parece cobertura (ADR 0028/0034)."
    )


def test_the_allowlists_do_not_keep_a_line_that_stopped_being_needed() -> None:
    """As duas listas vencem, como a do `advisories.json` (ADR 0023)."""
    emitted = emitted_events()
    stale_modules = sorted(
        name for name in PROSE_IS_FINE if not (SOURCE_ROOT / name).exists()
    )
    stale_events = sorted(e for e in NOT_AN_ALERT if e not in emitted)

    assert stale_modules == [], f"PROSE_IS_FINE cita módulos que não existem: {stale_modules}"
    assert stale_events == [], f"NOT_AN_ALERT cita eventos que ninguém emite: {stale_events}"
