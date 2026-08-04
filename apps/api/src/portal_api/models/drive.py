"""Conexão de uma pasta do Google Drive a um projeto (ADR 0016).

Uma linha por projeto — a unicidade é da tabela e não uma esperança do código,
porque "uma pasta permitida por projeto" (FDD 003) é a fronteira em que todo o
resto se apoia: se houvesse duas, "a pasta autorizada" deixaria de ser uma
pergunta com resposta.

O que a linha guarda de sensível é um só campo, ``refresh_token_sealed``, e ele é
o primeiro segredo do repositório que precisa **voltar em claro**
(:mod:`portal_api.crypto`). O access token não mora aqui: vale uma hora, é pedido
a cada sincronização e vive em memória. Guardar o de vida curta seria aumentar a
superfície para poupar uma chamada.

Desconectar **revoga**, não apaga: limpa o segredo e carimba ``disconnected_at``,
como ``AgentApiKey`` faz — a linha é o rastro de que a pasta esteve conectada, e
de quando deixou de estar.

``enabled`` existe para o runbook ter o que executar. "Pausar a pasta afetada"
(``docs/runbooks/drive-sync-failure.md``) precisa ser uma coluna: sem ela, a única
forma de parar um sync que está falhando seria desconectar, o que jogaria fora o
consentimento junto com o problema.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin
from portal_api.models.project import _ProjectChildMixin

#: O único escopo pedido, e ele é somente leitura. O threat model cobra isto
#: nominalmente ("OAuth Drive excessivo | escopo readonly e folder allowlist"), e
#: o conector recusa a conexão quando o Google concede um conjunto diferente —
#: consentir mais do que se pediu é um estado que não deve virar rotina.
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class DriveSyncState(str, enum.Enum):
    """Onde a sincronização está — e é também a guarda de sobreposição.

    ``running`` é reivindicado por um ``UPDATE`` condicional, não lido e depois
    escrito: dois ticks do beat chegando juntos precisam que exatamente um ganhe,
    e é o banco quem decide isso. Mesma escolha da janela de rate limit da
    ADR 0013 — o estado mora na própria linha, sem trazer o Redis para o meio.
    """

    idle = "idle"
    running = "running"
    failed = "failed"


class ProjectDriveConnection(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "project_drive_connection"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_drive_connection_project_id"),
    )

    # --- A pasta autorizada -------------------------------------------------
    #: Id da pasta no Drive. Null entre pedir o consentimento e escolher a pasta:
    #: são dois passos, porque só depois de conectar dá para listar as pastas da
    #: conta e deixar a pessoa escolher sem embutir o Picker do Google.
    folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Nome exibido na tela. É rótulo: quem manda é o id.
    folder_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- A credencial -------------------------------------------------------
    #: Conta que consentiu, para a tela dizer *de quem* é o acesso. Rótulo, não
    #: usuário do portal — a conta do Google não tem relação com a `user`.
    google_account_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    #: Refresh token selado (`crypto.seal`), amarrado a organização e projeto pelo
    #: AAD. Null quando a conexão nunca foi concluída ou foi revogada.
    refresh_token_sealed: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: O escopo que o Google **concedeu**, que não é necessariamente o que foi
    #: pedido. Guardado para a recusa ser auditável depois do fato.
    granted_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    connected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Pausa sem perder o consentimento. É o que o runbook chama de "pausar a
    #: pasta afetada".
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # --- O fluxo do OAuth, enquanto ele está aberto -------------------------
    #: SHA-256 do `state`. Guardado como hash pelo mesmo motivo da chave de
    #: agente: o valor em claro não precisa existir no banco para ser conferido.
    oauth_state_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    oauth_state_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Verificador do PKCE. Um `code` interceptado sozinho não vira token.
    oauth_code_verifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Quem pediu o consentimento. O callback recusa se voltar em outra sessão —
    #: o `state` prova que o fluxo é o mesmo, isto prova que a pessoa é a mesma.
    oauth_requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    # --- A sincronização ----------------------------------------------------
    sync_state: Mapped[DriveSyncState] = mapped_column(
        Enum(DriveSyncState, name="drive_sync_state"),
        nullable=False,
        default=DriveSyncState.idle,
        server_default=DriveSyncState.idle.value,
    )
    #: Quando o `running` atual foi reivindicado. É o que permite recuperar uma
    #: conexão cujo worker morreu no meio, em vez de deixá-la travada para sempre.
    sync_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Só a mensagem do erro — nunca nome de arquivo completo nem conteúdo
    #: (docs/data-classification.md).
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `{added, updated, removed, skipped, rejected}`. Em JSONB pelo mesmo motivo
    #: das citações da ADR 0015: só faz sentido junto da linha que o produziu, e
    #: o produto nunca consulta essas contagens sozinhas.
    last_sync_stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
