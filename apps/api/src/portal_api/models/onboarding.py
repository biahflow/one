"""Os degraus de valor que o cliente alcançou, com a data da **primeira** vez (RFC 001).

Escopo de **organização**, não de projeto: a pergunta que a RFC faz é sobre a relação do
cliente com o produto, e um cliente pode ter mais de um projeto. É a forma de
``organization_retention_policy``, que também usa ``TenantMixin`` sem ``project_id``.

Só entra degrau em que o cliente **recebeu** alguma coisa. "Logou doze vezes" não é degrau —
pode ser um cliente perdido procurando o que deveria estar óbvio, e instrumentar esforço é
otimizar engajamento medindo ansiedade.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TenantMixin, TimestampMixin


class OnboardingStepName(str, enum.Enum):
    """Os degraus, na ordem em que a jornada os alcança.

    Cinco nascem aqui e dois nascem no Biahflow — e a diferença importa na hora de separar
    "travou no cliente" de "travou em nós" (RFC 001).

    *Até 07/08/2026 este docstring dizia que ``artifact_accepted`` **não** estava aqui de
    propósito, porque "o snapshot do Biahflow não carrega nada de artefato" e declarar um
    degrau que nada carimba seria o painel sem escritor da ADR 0033. A frase terminava com a
    condição — "ele entra quando o outro lado o afirmar" —, e o outro lado afirmou: a FDD 031
    de lá pôs ``artifact_accepted_at`` no snapshot, com emissor. O registro fica porque é ele
    que explica por que o degrau chegou último, e não por que faltava (ADR 0041).*
    """

    #: O cliente **aprovou** alguma coisa pela primeira vez — a jornada comercial saindo de
    #: ``sent`` para ``accepted`` no Biahflow. É o degrau que dá origem à régua: sem ele o
    #: portal contava o *time-to-first-value* a partir do convite, que é quando **ele** conheceu
    #: o cliente, e não a partir do ganho.
    artifact_accepted = "artifact_accepted"
    #: O convite virou conta: ``user.external_subject`` deixou de ser nulo.
    first_login = "first_login"
    #: O cliente abriu um documento pela primeira vez — recebeu conteúdo, não só navegou.
    first_document_opened = "first_document_opened"
    #: Respondeu uma pendência, que é o degrau em que ele passa a participar.
    first_pending_answered = "first_pending_answered"
    #: Perguntou ao assistente e recebeu resposta com evidência.
    first_chat_turn = "first_chat_turn"
    #: Viu ROI de verdade — dashboard servido **com** número, não com lacuna.
    first_roi_seen = "first_roi_seen"
    #: Primeiro entregável fora de ``pending``, afirmado pelo Biahflow no snapshot.
    first_deliverable_delivered = "first_deliverable_delivered"


class OnboardingStep(Base, TenantMixin, TimestampMixin):
    """Uma linha por organização e degrau, com o instante da primeira ocorrência.

    **O carimbo é imutável, e a `UniqueConstraint` é o que o garante**: a escrita é
    ``ON CONFLICT DO NOTHING``, não há ``UPDATE`` no contrato e nenhum papel recebe GRANT de
    ``UPDATE``. Primeira vez é primeira vez — reescrever destruiria a única métrica que
    interessa, que é o *time-to-first-value*.

    **Quem escreve é o sistema.** ``portal_app`` não tem policy nenhuma aqui, na forma de
    ``agent_api_key`` e ``project_drive_connection``: um caminho de requisição capaz de
    escrever o próprio degrau é um caminho capaz de falsear o próprio engajamento.
    """

    __tablename__ = "onboarding_step"
    __table_args__ = (
        UniqueConstraint("organization_id", "step", name="uq_onboarding_step_org_step"),
    )

    step: Mapped[OnboardingStepName] = mapped_column(
        Enum(OnboardingStepName, name="onboarding_step_name", native_enum=True),
        nullable=False,
    )
    #: Quando aconteceu pela primeira vez. Separado do ``created_at`` do mixin porque quem
    #: carimba pode não ser quem observou: o degrau do Biahflow chega pelo sync, e a data que
    #: interessa é a do fato, não a da linha.
    reached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Quem chegou primeiro, quando é uma pessoa que chega. Nulo para o degrau que vem do
    #: Biahflow — lá não há pessoa deste lado a nomear. ``SET NULL`` porque o apagamento de
    #: uma conta não pode apagar o fato de o degrau ter sido alcançado.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
