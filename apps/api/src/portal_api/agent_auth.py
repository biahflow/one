"""Autenticação da API de eventos por chave de projeto (ADR 0013).

Um agente não tem sessão de usuário, então não pode se autenticar como uma
pessoa. O que ele tem é uma chave que pertence a **um projeto**: o tenant é
propriedade da credencial, nunca do corpo da requisição. É isso que permite à
rota de ingestão aceitar um ``projectId`` vindo de fora sem confiar nele — a
chave já respondeu "qual projeto", e um corpo que discorde é 404.

Em módulo próprio pelo mesmo motivo que ``admin.py`` é separado: a resposta a
"o que autentica um agente" precisa caber em um arquivo.

O header é ``X-Agent-Key``, e não ``Authorization: Bearer``. Segue o precedente
do ``X-Biahflow-Signature`` e evita dois esquemas disputando o mesmo header —
um Bearer humano nesta rota deve falhar, não ser tentado como chave.

**Toda recusa é o mesmo 401 opaco**, com o motivo só no log estruturado, pela
razão já escrita em ``docs/security.md``: resposta diferenciada vira oráculo de
sondagem ("esta chave existe mas expirou" é informação). A única exceção é a
janela de rate limit, que responde **429** — aí o produtor precisa saber que o
problema é ritmo e não credencial, senão fica retentando para sempre.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api.config import Settings, get_settings
from portal_api.db.session import DbRole, get_session
from portal_api.models import SCOPE_EVENTS_WRITE, AgentApiKey

logger = logging.getLogger(__name__)

HEADER = "X-Agent-Key"
#: Como ``auth._bearer_scheme``, existe só para o esquema (ADR 0020) — mas aqui
#: ele é o que faz o OpenAPI dizer o que `docs/api-contracts.md` já dizia em
#: prosa: esta é a **única** rota autenticada por chave, e ela não aceita o
#: `Authorization: Bearer` humano. Mora neste arquivo pelo mesmo motivo que o
#: resto: "o que autentica um agente" cabe num lugar só.
#: ``scheme_name`` explícito porque o padrão é o nome da classe, e duas
#: ``APIKeyHeader`` diferentes colapsariam numa entrada só do esquema — a chave
#: do agente e a assinatura do webhook viram a mesma coisa, que é exatamente a
#: confusão que esta fatia existe para desfazer.
SCHEME = APIKeyHeader(
    name=HEADER,
    scheme_name="AgentKey",
    auto_error=False,
    description="Chave do agente, emitida por projeto em /api/v1/admin.",
)
#: Prefixo do formato, para uma chave ser reconhecível num log ou num alerta de
#: segredo vazado sem precisar de contexto.
KEY_PREFIX = "plk"
#: Tamanho do trecho em claro guardado na linha. Inclui o `plk_`, então é o
#: bastante para localizar a chave e insuficiente para reconstruí-la.
PREFIX_LENGTH = 12
WINDOW = timedelta(minutes=1)
#: Hash de comprimento correto para comparar quando o prefixo não existe.
_ABSENT_DIGEST = "0" * 64


@dataclass(frozen=True)
class AgentIdentity:
    """A quem a chave dá acesso — resolvido no servidor, nunca pedido ao cliente."""

    key_id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID


class RateLimited(HTTPException):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many events; retry later",
            headers={"Retry-After": str(retry_after)},
        )


def _unauthorized(reason: str, **context: object) -> HTTPException:
    logger.warning("agent_key.rejected", extra={"reason": reason, **context})
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": HEADER},
    )


def generate_key() -> tuple[str, str]:
    """Devolve ``(chave em claro, prefixo)``.

    32 bytes de ``secrets.token_urlsafe`` — é a entropia da chave, e não a
    lentidão do hash, que sustenta a segurança aqui.
    """
    secret = secrets.token_urlsafe(32)
    key = f"{KEY_PREFIX}_{secret}"
    return key, key[:PREFIX_LENGTH]


def hash_key(key: str, settings: Settings | None = None) -> str:
    """HMAC-SHA256 da chave sob o pepper do servidor.

    HMAC com pepper, e não bcrypt/argon2, porque isto roda a cada evento
    ingerido: um hash deliberadamente lento aqui seria um limitador de vazão
    autoinfligido. O que um KDF lento defende é segredo de baixa entropia
    (senha), que não é o caso — o que precisamos é que o conteúdo do banco,
    sozinho, não valha nada, e é exatamente o que o pepper dá.
    """
    settings = settings or get_settings()
    if not settings.agent_key_pepper:
        # Falha fechada: sem pepper configurado nenhuma chave autentica, em vez
        # de um ambiente mal configurado abrir a rota com hash previsível.
        raise RuntimeError("AGENT_KEY_PEPPER is not configured")
    return hmac.new(
        settings.agent_key_pepper.encode(), key.encode(), hashlib.sha256
    ).hexdigest()


def _presented_key(request: Request) -> str:
    key = request.headers.get(HEADER, "").strip()
    if not key or not key.startswith(f"{KEY_PREFIX}_"):
        raise _unauthorized("missing_agent_key")
    return key


def _check_window(session: Session, record: AgentApiKey, limit: int, now: datetime) -> None:
    """Janela deslizante de um minuto, guardada na própria linha da chave.

    Em Postgres e não em Redis de propósito: a API sobe hoje sem broker, e uma
    dependência dura nova no caminho de requisição custaria mais do que a
    precisão que ela compraria (ADR 0013). Sob concorrência alta o contador
    subconta — aceitável para um limite de abuso, que não é um contador de
    faturamento.
    """
    started = record.window_started_at
    if started is None or now - started >= WINDOW:
        record.window_started_at = now
        record.window_count = 1
        return
    if record.window_count >= limit:
        retry_after = max(1, int((started + WINDOW - now).total_seconds()))
        logger.warning(
            "agent_key.rate_limited",
            extra={"key_prefix": record.key_prefix, "limit": limit},
        )
        raise RateLimited(retry_after)
    record.window_count += 1


def authenticate(request: Request, settings: Settings | None = None) -> AgentIdentity:
    """Resolve a chave apresentada, ou levanta 401/429.

    Roda sob ``portal_system``: a busca acontece **antes** de haver tenant para
    ligar — é justamente da chave que o tenant sai — então não existe contexto
    de RLS a publicar aqui. É a mesma razão pela qual o webhook do Biahflow roda
    sob esse papel. O acesso é uma linha, endereçada pelo prefixo, e a escrita é
    só o contador e o carimbo de uso.

    A ingestão em si acontece depois, em outra transação, sob ``portal_app`` com
    o tenant ligado — para o banco continuar sendo a segunda barreira na rota
    que recebe identificador de fora.
    """
    settings = settings or get_settings()
    key = _presented_key(request)
    prefix = key[:PREFIX_LENGTH]
    digest = hash_key(key, settings)
    now = datetime.now(timezone.utc)

    with get_session(role=DbRole.system) as session:
        record = session.execute(
            select(AgentApiKey).where(AgentApiKey.key_prefix == prefix)
        ).scalar_one_or_none()

        # Compara mesmo quando não há linha, contra um hash falso do **mesmo
        # tamanho**: `compare_digest` sai cedo em comprimentos diferentes, então
        # um `""` aqui faria o tempo de resposta dizer se o prefixo existe.
        expected = record.key_hash if record is not None else _ABSENT_DIGEST
        matches = hmac.compare_digest(expected, digest)
        if record is None or not matches:
            raise _unauthorized("unknown_agent_key", key_prefix=prefix)
        if record.revoked_at is not None:
            raise _unauthorized("revoked_agent_key", key_prefix=prefix)
        if record.expires_at <= now:
            raise _unauthorized("expired_agent_key", key_prefix=prefix)
        if SCOPE_EVENTS_WRITE not in (record.scopes or []):
            raise _unauthorized("missing_scope", key_prefix=prefix)

        _check_window(session, record, settings.agent_events_rate_limit, now)
        record.last_used_at = now

        return AgentIdentity(
            key_id=record.id,
            organization_id=record.organization_id,
            project_id=record.project_id,
        )
