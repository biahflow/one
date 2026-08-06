"""O `trace_id` e o log estruturado (Fase 5, ADR 0018).

O único lugar onde o identificador nasce, é lido e é formatado — mesma forma de
`notifications.py`, `conversations.py` e `retention.py`, e pelo mesmo motivo: se
"como se segue uma requisição" estiver espalhado, a pergunta deixa de ter
resposta que caiba num arquivo.

**O formatter é a parte que conserta uma regressão, não a que inventa um
recurso.** O repositório já tinha a convenção de logar nome de evento com campos
em ``extra`` — ``auth.rejected`` com ``reason``, ``agent_key.rejected`` com
``key_prefix``, ``keycloak.failed`` com ``what`` —, e o
``docs/runbooks/agent-events-failure.md`` manda ler esses campos. Só que sem
handler configurado o ``logging`` usa o formato padrão, que imprime
``record.getMessage()`` e **descarta todo o resto**: os campos existiam no código,
nunca no stdout. Aqui eles passam a sair.

Nada de ``structlog`` nem OpenTelemetry: a biblioteca padrão resolve, e é o mesmo
instinto que mantém o e-mail em SMTP puro em vez de um SDK de provedor. Métrica e
exporter pertencem ao item de homologação, que é quando existirá para onde
mandá-las.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any

#: O header por onde o id entra e sai. Já estava na allowlist de CORS da API
#: (`main.py`) antes de existir quem o lesse — esta é a outra ponta.
TRACE_HEADER = "X-Request-ID"

#: Vazio, e não ``None``, para o formatter nunca precisar de um ramo: uma linha
#: fora de qualquer requisição (import, comando de CLI) sai com ``trace_id: ""``,
#: que se lê como "não veio de requisição nenhuma".
_trace_id: ContextVar[str] = ContextVar("portal_trace_id", default="")


def current_trace_id() -> str:
    """O id da requisição (ou da task) em curso; vazio fora de uma."""
    return _trace_id.get()


def bind_trace_id(trace_id: str | None) -> str:
    """Publica o id no contexto e devolve o que ficou valendo.

    Recebe ``None`` de propósito: quem chama costuma ter em mãos um header que
    pode não ter vindo, e cunhar aqui evita repetir o ``or uuid4()`` em cada
    borda.
    """
    resolved = trace_id or new_trace_id()
    _trace_id.set(resolved)
    return resolved


def clear_trace_id() -> None:
    """Volta ao estado "fora de qualquer requisição".

    Existe porque ``bind_trace_id`` cunha quando recebe vazio — o que é o certo
    numa borda e o errado num teste que precisa observar o caso sem id.
    """
    _trace_id.set("")


def new_trace_id() -> str:
    return uuid.uuid4().hex


# --------------------------------------------------------------------------- #
# Formatter
# --------------------------------------------------------------------------- #

#: Atributos que o ``logging`` põe em todo ``LogRecord``. O que sobrar do
#: ``__dict__`` depois de tirar estes é exatamente o que veio em ``extra`` — é
#: essa diferença que faz os campos aparecerem sem obrigar cada call site a
#: mudar de forma.
_STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}

#: Fragmentos que denunciam um valor que não pode ser impresso. Cumpre a regra 5
#: do `AGENTS.md` ("não inclua segredos em ... logs") no código, e não só na
#: prosa: quem escrever `extra={"access_token": ...}` amanhã não vaza nada.
_SECRET_HINTS = ("token", "secret", "password", "passwd", "authorization", "cookie", "key")

#: A exceção da regra acima, e ela é obrigatória: o runbook da API de eventos
#: manda ler o `key_prefix` para saber *qual* chave foi recusada. O prefixo é a
#: parte pública da credencial — é justamente o que fica em claro no banco.
#:
#: `input_tokens`/`output_tokens` entraram na ADR 0022 e são a mesma família de
#: engano, uma casa adiante: eles contêm "token" e **não são um token** — são a
#: contagem que o provedor devolve em `usage`. Sem esta linha, o indicador de
#: custo de IA que `docs/observability.md` promete sairia `[redacted]` em toda
#: linha de log, e o defeito só apareceria a quem fosse ler o log meses depois.
_SECRET_ALLOWLIST = frozenset(
    {"key_prefix", "public_key", "key_id", "input_tokens", "output_tokens"}
)

_REDACTED = "[redacted]"


def _redact(key: str, value: Any) -> Any:
    if key in _SECRET_ALLOWLIST:
        return value
    lowered = key.lower()
    if any(hint in lowered for hint in _SECRET_HINTS):
        return _REDACTED
    return value


class JsonFormatter(logging.Formatter):
    """Uma linha JSON por registro, com os campos de ``extra`` promovidos.

    ``event`` é a mensagem, e por isso **a mensagem tem de ser um nome estável**
    (``auth.rejected``), com o detalhe em ``extra``. Não são dois campos para "o
    que aconteceu" justamente para não criar a dúvida de qual ler.

    A frase que estava aqui até a ADR 0034 dizia que a mensagem servia "também
    quando é prosa, porque quem consome filtra por ``event`` de qualquer jeito",
    e ela era falsa no ponto que importa: o que entra em ``event`` é
    ``getMessage()``, ou seja, a mensagem **já interpolada**. Um
    ``logger.warning("Objeto %s não removido", key)`` produz um ``event``
    diferente a cada chave — inconsultável, e o limiar que o ``alerts.md``
    promete para cada evento deixa de ser aplicável. Dez sítios viviam assim, e
    um deles era o único sinal de que o antivírus havia caído.
    ``test_telemetry.py`` varre o AST e reprova a volta.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "") or current_trace_id(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key in payload or key.startswith("_"):
                continue
            payload[key] = _redact(key, value)
        if record.exc_info:
            # A stack inteira numa string, e não um campo por quadro: o objetivo
            # é grep, não árvore.
            payload["exception"] = self.formatException(record.exc_info)
        # `default=str` porque UUID e datetime chegam por `extra` o tempo todo e
        # um log que estoura ao serializar é pior que um log impreciso.
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """O formato legível do dia a dia, com os mesmos campos no fim da linha.

    Existe para o ``docker compose logs`` de quem está desenvolvendo não virar
    uma parede de JSON. O que ele **não** faz é descartar os campos de ``extra``
    — era esse o defeito do formato padrão.
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            key: _redact(key, value)
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
        }
        trace_id = current_trace_id()
        if trace_id:
            extras.setdefault("trace_id", trace_id)
        if not extras:
            return base
        rendered = " ".join(f"{key}={value}" for key, value in extras.items())
        return f"{base} {rendered}"


def build_formatter(log_format: str) -> logging.Formatter:
    if log_format == "text":
        return TextFormatter("%(levelname)s %(name)s %(message)s")
    return JsonFormatter()


def configure_logging(level: str | None = None, log_format: str | None = None) -> None:
    """Instala o handler único da raiz. Idempotente: chamar duas vezes não duplica linha.

    Os loggers do uvicorn perdem o handler próprio e passam a **propagar**. Sem
    isso sairiam duas linhas por requisição em dois formatos diferentes, e a que
    tem o ``trace_id`` seria a segunda — o que faz um `grep` encontrar a linha
    errada.
    """
    from portal_api.config import get_settings

    settings = get_settings()
    resolved_level = (level or settings.log_level).upper()
    formatter = build_formatter(log_format or settings.log_format)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(resolved_level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery", "celery.app.trace"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

logger = logging.getLogger(__name__)


class TraceMiddleware:
    """Liga o ``trace_id`` na borda HTTP e devolve-o no header.

    Aceita o id de quem chamou: o BFF cunha um por requisição do navegador
    (`app/lib/trace.ts`), e é isso que faz a linha do `web` e a do `api`
    contarem a mesma história. Ausente, cunha aqui — nenhuma requisição fica sem.

    É ASGI puro, e não um ``BaseHTTPMiddleware``, por dois motivos: aquele
    executa o resto da aplicação dentro de um task group do anyio, o que põe uma
    camada entre onde a ``ContextVar`` é escrita e onde ela é lida; e importá-lo
    exigiria depender do ``starlette`` pelo nome, que é justamente o trânsito de
    biblioteca que o `requirements.txt` evita desde a ADR 0016.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        trace_id = bind_trace_id(_header_of(scope, TRACE_HEADER))
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((TRACE_HEADER.lower().encode(), trace_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception(
                "http.failed",
                extra={
                    "method": scope.get("method", ""),
                    "route": _route_of(scope),
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise
        logger.info(
            "http.request",
            extra={
                "method": scope.get("method", ""),
                # A **rota**, não a URL: o path traz id de projeto e de documento,
                # e um log de acesso não precisa deles para responder "que
                # endpoint está lento". A query string nunca entra.
                "route": _route_of(scope),
                "status": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )


def _header_of(scope, name: str) -> str | None:
    wanted = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == wanted:
            return value.decode("latin-1")
    return None


def _route_of(scope) -> str:
    """O template da rota (`/api/v1/projects/{project_id}/results`) quando há uma.

    Fora de uma rota conhecida (404, arquivo estático) devolve ``"unmatched"`` em
    vez do path: um caminho inexistente é escolhido por quem chama, e ecoá-lo no
    log é deixar um terceiro escrever nele. O roteador do FastAPI só põe ``route``
    no escopo depois de casar, então esta função é chamada **depois** da
    aplicação, nunca antes.
    """
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


# --------------------------------------------------------------------------- #
# Auditoria
# --------------------------------------------------------------------------- #


def audit_data(**fields: Any) -> dict[str, Any]:
    """O JSONB de um ``AuditLog`` com o ``trace_id`` carimbado.

    É o que torna verdadeira a primeira linha do runbook de incidente
    ("preservar `trace_id`/auditoria"): da linha de auditoria se chega ao log e
    do log se volta à linha. Existe como função — em vez de cada call site
    escrever a chave — para um `AuditLog` novo não conseguir esquecer.

    Sem migração: ``audit_log.data`` já é JSONB.
    """
    trace_id = current_trace_id()
    if trace_id:
        # Do lado de fora, para um campo de negócio chamado `trace_id` (não há
        # nenhum hoje) não ser silenciosamente sobrescrito sem ninguém notar.
        return {**fields, "trace_id": trace_id}
    return dict(fields)
