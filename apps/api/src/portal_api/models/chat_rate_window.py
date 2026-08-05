"""A janela deslizante do chat, por pessoa (Fase 5, ADR 0021).

O ``threat-model.md`` prometia "rate limit, quotas e auditoria" para abuso de
chat e nada disso existia. A ameaça não é a conta de token: **cada lacuna grava
uma pendência**, uma linha de auditoria e enfileira uma notificação, então um
laço de perguntas sem evidência vira enxurrada na caixa do time interno.

Tabela própria, e não colunas em ``user``, por duas razões — e a segunda decide:

1. Estender o GRANT de coluna que a 0009 deliberadamente estreitou daria a quem
   é limitado escrita sobre o estado do próprio limite.
2. ``identity.resolve_user`` roda **dentro** da transação do chat e, no primeiro
   login, escreve ``external_subject`` — lock na linha. Uma segunda transação
   mexendo na mesma linha esperaria o chat commitar, e o chat abrange a chamada
   ao modelo. Seria travamento no caminho de primeiro login, descoberto em
   produção e não no CI. O precedente do ``agent_api_key`` não transfere: lá a
   linha da chave é lida e incrementada numa transação só e nada mais a toca.

**Sem ``TenantMixin``, de propósito.** O limite é propriedade de uma pessoa, como
``user``, que também não carrega tenant. Por projeto seria pior que inútil:
deixaria alguém abrir N projetos de cota, que é o oposto do que o controle quer.
A consequência — o meta-teste de ``test_rls_isolation.py`` não cobra policy desta
tabela, porque ele cobra por ``organization_id`` — está registrada na migração
0017 para ninguém a ler como esquecimento.

A chave é o ``sub`` do OIDC e não o ``user.id``: é o que o token carrega, é o que
``portal.current_subject()`` já usa, e sem FK a linha existe desde a primeira
requisição — inclusive antes de a pessoa ter sido provisionada, que é
exatamente quando um laço automatizado começaria.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin


class ChatRateWindow(Base, TimestampMixin):
    __tablename__ = "chat_rate_window"

    subject: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
