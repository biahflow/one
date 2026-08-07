"""Prazo dos dados e o pedido de apagamento (Fase 5, ADR 0017).

Duas tabelas, e as duas existem porque a dívida estava declarada e não escrita:
`docs/data-classification.md` promete que o conteúdo é "removível por
organização", e ADR 0012, 0014, 0015 e 0016 adiaram cada uma a sua parte para a
Fase 5 com o mesmo parágrafo.

**Por que uma tabela e não colunas em ``organization``.** A organização vem do
snapshot do Biahflow, e ``sync_snapshot`` faz upsert nela a cada webhook — um
prazo guardado ali seria sobrescrito pelo primeiro sync que não soubesse dele.
É a mesma lição que criou ``document.origin`` e ``pending_item.origin``: dado
que o portal origina não mora em linha que o Biahflow reescreve.

**Por que o expurgo é um pedido e não uma rota que apaga.** A ADR 0015 já tinha
decidido: "quando o expurgo chegar, não será o caminho de requisição a fazê-lo".
Uma requisição HTTP que apaga a organização inteira é uma transação longa cujo
timeout deixa o trabalho pela metade, e é um botão cujo efeito não tem como ser
conferido antes de acontecer. Aqui a administração **grava a intenção** sob
``portal_admin``, e quem executa é o worker sob ``portal_system`` — que é o único
papel que alcança todas as tabelas envolvidas.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TenantMixin, TimestampMixin


class OrganizationRetentionPolicy(Base, TenantMixin, TimestampMixin):
    """Por quanto tempo cada família de dado fica, nesta organização.

    Uma linha por organização. Coluna nula significa "usa o padrão de
    ``config.py``" e não "guarda para sempre": um contrato que não fala de
    retenção não é um contrato de retenção infinita, e deixar o padrão explícito
    num só lugar é o que permite mudá-lo sem visitar cada organização.

    As três famílias são as que crescem sem teto e cujas ADRs pediram poda pelo
    nome: aviso (0012), evento de agente (0013) e conversa (0015). Documento
    fica **de fora de propósito** — ele é a evidência que sustenta a citação, e
    apagá-lo por idade tornaria uma resposta antiga impossível de conferir. O
    documento sai pelo pedido de apagamento, que é uma decisão de alguém, ou pela
    tela de administração, que é a mesma coisa.
    """

    __tablename__ = "organization_retention_policy"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", name="uq_organization_retention_policy_organization_id"
        ),
    )

    notification_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_event_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversation_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Comportamento de pessoa identificada (RFC 001, ADR 0039). Entra aqui porque é a
    #: classe de dado que mais custa guardar em risco — e não porque cresce sem teto, que
    #: é o argumento das três acima: são no máximo seis linhas por organização.
    onboarding_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Quem definiu o prazo. É registro de decisão, não de acesso — por isso na
    #: linha e não só no `audit_log`.
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )


class ErasureState(str, enum.Enum):
    """Onde o pedido está.

    ``running`` é reivindicado por ``UPDATE`` condicional, como o sync do Drive
    (ADR 0016): dois workers pegando o mesmo pedido precisam que exatamente um
    ganhe, e quem decide isso é o banco.
    """

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class DataErasureRequest(Base, TenantMixin, TimestampMixin):
    """Um pedido de apagamento dos dados de uma organização.

    A linha **sobrevive ao próprio expurgo**, e é o ponto: apagar tudo sem deixar
    registro de que se apagou tornaria "o que aconteceu com aquela organização"
    impossível de responder — exatamente a pergunta que alguém faz depois. Por
    isso o pedido guarda o que removeu (``removed``, por tabela) e não o que
    removeu de conteúdo.

    ``requested_reason`` é texto da equipe interna, não do cliente, e entra no
    registro porque um apagamento sem motivo declarado é indistinguível de um
    acidente.
    """

    __tablename__ = "data_erasure_request"

    state: Mapped[ErasureState] = mapped_column(
        Enum(ErasureState, name="erasure_state"),
        nullable=False,
        default=ErasureState.pending,
        server_default=ErasureState.pending.value,
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    requested_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Contagem por tabela do que saiu. Nunca amostra do que saiu.
    removed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
