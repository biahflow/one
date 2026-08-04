"""Per-project API key for the agent events endpoint (ADR 0013).

An agent has no user session, so it cannot authenticate the way a person does.
What it gets instead is a key that belongs to **one project** — the tenant is a
property of the credential, never of the request body. That is what lets the
ingestion route accept a ``projectId`` from outside without trusting it: the key
already answers "which project", and a body that disagrees is a 404.

Only ``key_prefix`` survives in the clear, and only so the lookup is O(1). The
secret itself is never stored: what the row keeps is an HMAC-SHA256 of it under
a server-side pepper (:mod:`portal_api.agent_auth`), so a database leak alone
does not yield a usable key.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin
from portal_api.models.project import _ProjectChildMixin

#: The only scope there is today. Declared as data rather than assumed so that
#: adding a second one later is a row change, not a schema change.
SCOPE_EVENTS_WRITE = "events:write"


class AgentApiKey(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "agent_api_key"
    __table_args__ = (
        UniqueConstraint("key_prefix", name="uq_agent_api_key_key_prefix"),
    )

    #: Rótulo humano ("Agente Financeiro — produção"), só para a tela de admin.
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Trecho em claro que identifica a chave sem revelá-la. É por ele que se
    #: encontra a linha antes de comparar o hash.
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=f'["{SCOPE_EVENTS_WRITE}"]'
    )
    #: Expiração é obrigatória: uma credencial de máquina sem prazo é uma
    #: credencial que ninguém nunca troca.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Aponta para a chave que esta substituiu. É o que torna uma rotação
    #: reconstituível: dá para responder "de onde veio esta chave" meses depois.
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_api_key.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    # Janela deslizante do rate limit, guardada na própria linha da chave. Sem
    # Redis no caminho de requisição: a API sobe sem broker hoje e continua
    # subindo (ADR 0013).
    window_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    window_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
