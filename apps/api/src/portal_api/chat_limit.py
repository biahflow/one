"""Com que ritmo uma pessoa pode perguntar (Fase 5, ADR 0021).

Módulo próprio pela mesma razão que ``agent_auth.py`` não mora em ``auth.py``:
uma pergunta, um arquivo. E deliberadamente **não** unificado com o
``_check_window`` daquele módulo, embora os dois sejam janelas deslizantes em
Postgres — chaveiam coisas diferentes (uma credencial contra uma pessoa), vivem
em transações diferentes por razões diferentes, e fundi-los faria "o que
autentica um agente" deixar de caber num arquivo. Vinte e cinco linhas
duplicadas são o erro mais barato.

**Por que Postgres e não Redis.** A ADR 0013 já decidiu isto para a API de
eventos e o argumento é mais forte aqui: a API sobe sem broker, e
``queue_pending_notification`` já engole um broker morto de propósito. Pôr uma
dependência dura de Redis no caminho de requisição deixaria o chat *menos*
disponível que a notificação que ele dispara.

**Por que em transação própria e anterior.** O ``consume`` roda antes de a
transação do chat abrir. Se o contador vivesse dentro dela, o lock da linha
atravessaria a chamada ao modelo, e um chat revertido devolveria cota de uma
requisição que já custou. O preço declarado: quem tem token válido e nenhum
projeto vê 429 antes de 404 — o que não vaza nada sobre projeto nenhum, só que
a pessoa está autenticada, o que ela já sabe.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from portal_api.config import Settings, get_settings
from portal_api.db.session import DbRole, get_session
from portal_api.models import ChatRateWindow

logger = logging.getLogger(__name__)

WINDOW = timedelta(minutes=1)


class ChatRateLimited(HTTPException):
    """429 com ``Retry-After``, na forma do ``RateLimited`` da API de eventos.

    Não é opaco, e é a única recusa do chat que não é: quem pergunta precisa
    distinguir "seu ritmo" de "sua permissão" para saber se vale tentar de novo.
    """

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many questions; retry later",
            headers={"Retry-After": str(retry_after)},
        )


def consume(subject: str, settings: Settings | None = None) -> None:
    """Gasta uma pergunta da janela da pessoa, ou levanta ``ChatRateLimited``.

    Roda sob ``portal_system``: não há tenant a ligar aqui — o limite é da
    pessoa, não do projeto — e a tabela não tem policy para o papel de
    requisição. Mesma honestidade do ``agent_auth._check_window``: sob
    concorrência alta o contador **subconta**, o que é aceitável para um limite
    de abuso e seria inaceitável para um contador de faturamento.
    """
    settings = settings or get_settings()
    limit = settings.chat_rate_limit
    now = datetime.now(timezone.utc)

    with get_session(role=DbRole.system) as session:
        # A linha é garantida antes de ser lida, e não criada quando falta: duas
        # primeiras perguntas simultâneas da mesma pessoa colidiriam no índice
        # único e uma delas viraria 500 — um erro de servidor causado pelo próprio
        # controle de abuso. `DO NOTHING` faz a segunda simplesmente encontrar a
        # linha da primeira. Nasce com contador zero para o incremento abaixo ser
        # o mesmo em todo caminho.
        session.execute(
            pg_insert(ChatRateWindow.__table__)
            .values(subject=subject, window_started_at=now, window_count=0)
            .on_conflict_do_nothing(index_elements=["subject"])
        )
        window = session.execute(
            select(ChatRateWindow).where(ChatRateWindow.subject == subject)
        ).scalar_one()

        started = window.window_started_at
        if started is None or now - started >= WINDOW:
            window.window_started_at = now
            window.window_count = 1
            return

        if window.window_count >= limit:
            retry_after = max(1, int((started + WINDOW - now).total_seconds()))
            # O prefixo, e não o `sub` inteiro: o bastante para saber *quem* está
            # em laço, sem o log virar um rastro estável por pessoa. Mesmo
            # tratamento que o `key_prefix` recebe na API de eventos.
            logger.warning(
                "chat.rate_limited",
                extra={"subject_prefix": subject[:8], "limit": limit},
            )
            raise ChatRateLimited(retry_after)

        window.window_count += 1
