"""O que a IA consumiu, o teto de cada organização e o preço do modelo (Fase 5, ADR 0022).

Três tabelas com papéis deliberadamente diferentes — **razão**, **política** e
**preço** —, e a divisão entre elas é a decisão que carrega o desenho:

``ai_usage_event`` guarda **tokens, nunca dinheiro**. O custo nasce na leitura,
pelo preço vigente **no dia da chamada**. É literalmente ``results.py``, e pelo
motivo dele: mudar o preço do modelo hoje não pode reprecificar março. Uma coluna
``cost_cents`` gravada na ingestão seria mais barata de somar e passaria a mentir
no primeiro reajuste — sem que nada no sistema notasse, porque o número já estaria
lá.

E o inverso também vale, que é o que torna a divisão segura: um preço **que falta**
é recuperável, porque o fato (os tokens) está gravado; um chat recusado porque o
preço faltava não é. Daí ``ai/quota.py`` deixar o turno passar e declarar a
lacuna, em vez de falhar fechado como o resto do repositório costuma fazer.

**Por que não incrementar um contador.** O ``chat_limit.py`` diz de si mesmo que
"sob concorrência alta o contador subconta, o que é aceitável para um limite de
abuso e seria **inaceitável para um contador de faturamento**". Este é o contador
de faturamento. Um ``UPDATE ... SET total = total + n`` é leitura-modificação-
escrita e disputa; um ``INSERT`` por chamada não disputa com nada, e a soma vira
um ``SUM`` na leitura. O preço é uma linha por turno, que é barato, e uma agregação
por requisição, que é indexada.

**``ai_model_price`` não tem tenant, e a ausência é decisão.** Preço de modelo é
fato do mundo, igual para toda organização — dar-lhe ``organization_id`` sugeriria
que se negocia por cliente, que não é o caso. A consequência a registrar, porque
quem ler depois vai procurá-la: o meta-teste de ``test_rls_isolation.py`` não cobra
policy desta tabela, e não é esquecimento — ele cobra de toda tabela com
``organization_id``, e esta não tem uma. Mesma forma de ``chat_rate_window``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TenantMixin, TimestampMixin


class AiUsageEvent(Base, TenantMixin, TimestampMixin):
    """Uma linha por chamada ao modelo. O fato, sem interpretação.

    Escrita na **mesma transação do turno** (``ai/quota.py``), e não numa
    anterior como a janela de taxa: um turno revertido não deve cobrar, e a
    ordem inversa — cobrar antes e reverter depois — deixaria a cota consumida
    por uma resposta que ninguém recebeu.

    O preço declarado desse desenho, que a ADR 0022 registra: se a transação
    reverter **depois** de o provedor ter respondido, o dinheiro foi gasto e a
    linha não existe. É subcontagem, e a direção insegura para um teto — por isso
    o mesmo número sai no evento ``chat.answered``, que o log guarda
    independentemente da transação. O razão responde "quanto neste mês"; o log
    responde "quanto de fato saiu", e os dois se reconciliam.
    """

    __tablename__ = "ai_usage_event"
    __table_args__ = (
        # A consulta que existe é sempre a mesma: soma da organização no período
        # corrente. Sem este índice ela é um scan que cresce com o histórico, e
        # ela roda no caminho de **toda** pergunta.
        Index("ix_ai_usage_event_org_occurred", "organization_id", "occurred_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Quando a chamada aconteceu — e não quando a linha foi gravada. É por esta
    #: data que o preço vigente é escolhido, como o evento de agente escolhe a
    #: premissa financeira (ADR 0013).
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    #: ``None`` no caminho offline, onde o "modelo" é este código e não há custo.
    #: A linha ainda é gravada: "esta pergunta não custou nada porque o provedor
    #: estava fora" é informação, e apagá-la faria o mês parecer mais barato do
    #: que o serviço foi.
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: ``offline`` | ``anthropic`` | ``offline_fallback``, o mesmo trio de
    #: ``conversation_message`` (ADR 0021).
    responder: Mapped[str] = mapped_column(String(32), nullable=False)
    #: `BigInteger` porque a soma de um mês passa de dois bilhões sem esforço.
    input_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )


class OrganizationAiQuota(Base, TenantMixin, TimestampMixin):
    """O teto mensal de gasto de IA desta organização.

    Uma linha por organização, na forma exata de ``OrganizationRetentionPolicy``
    (ADR 0017) e pelas mesmas duas razões: coluna nula significa **"usa o padrão
    de ``config.py``"** e nunca "sem teto", porque um contrato que não fala de
    limite não é um contrato de limite infinito; e é tabela e não coluna em
    ``organization``, porque aquela linha vem do snapshot do Biahflow e o
    ``sync_snapshot`` faz upsert nela — um teto guardado ali seria sobrescrito
    pelo primeiro webhook que não soubesse dele.

    **Por organização e não por projeto**, pela razão que a ADR 0021 já usou para
    recusar cota por projeto: deixaria uma pessoa multiplicar a cota abrindo
    projetos. Aqui vale ainda mais, porque quem paga a conta é a organização.
    """

    __tablename__ = "organization_ai_quota"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", name="uq_organization_ai_quota_organization_id"
        ),
    )

    monthly_limit_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: Quem definiu o teto. Registro de decisão, não de acesso — por isso na linha
    #: e não só no `audit_log`, como o `updated_by_user_id` da retenção.
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )


class AiModelPrice(Base, TimestampMixin):
    """Quanto custa um modelo, com vigência.

    Mesma forma de ``ProjectFinancialAssumption`` (ADR 0013): preço não se edita
    no lugar — fecha-se uma vigência e abre-se outra —, e a migração declara um
    ``EXCLUDE USING gist`` para que duas vigências do mesmo modelo não se
    sobreponham. Sem isso, "qual era o preço em março" teria duas respostas e o
    banco não teria opinião sobre qual.

    Centavos por **milhão** de tokens, que é a unidade em que os provedores
    publicam; converter na leitura evita guardar fração de centavo por token, que
    seria zero em inteiro.
    """

    __tablename__ = "ai_model_price"

    model: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    #: Aberta significa vigente. Fechar é o que se faz ao abrir a seguinte.
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    input_cents_per_mtok: Mapped[int] = mapped_column(Integer, nullable=False)
    output_cents_per_mtok: Mapped[int] = mapped_column(Integer, nullable=False)
