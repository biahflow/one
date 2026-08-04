"""Conversation domain — o que foi perguntado, o que foi respondido e com que fontes.

Duas tabelas do mesmo agregado: ``conversation`` é a thread de uma pessoa dentro
de um projeto, e ``conversation_message`` é cada turno dela. A mensagem some
junto com a conversa, por CASCADE.

**A mensagem nunca é fonte de recuperação** (ADR 0015). É o invariante que
sustenta o desenho: aqui, ao contrário de ``document_chunk`` e ``notification``,
o caminho de requisição *escreve* — a pergunta é do usuário, e negar-lhe o INSERT
exigiria um worker para gravar o que a própria requisição acabou de saber. O que
impede alguém de plantar uma frase num turno e vê-la citada no seguinte não é um
privilégio, é o fato de ``ai/retrieval.py`` não ler esta tabela.

O feedback é a única coluna que muda depois de escrita, e é GRANT de coluna
(``0012_conversations``), como ``notification.read_at``: a pessoa avalia a
resposta, nunca reescreve a resposta nem as citações que ela mostrou. É o que faz
disto um registro e não uma alegação editável.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin
from portal_api.models.project import _ProjectChildMixin


class ConversationRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class MessageConfidence(str, enum.Enum):
    """O mesmo par que ``ChatResult.confidence`` devolve (ADR 0007).

    Guardado por mensagem para "esta resposta foi fundamentada ou declarou
    lacuna?" continuar respondível depois — é metade do sinal que calibra o corte
    de distância da recuperação; a outra metade é o feedback.
    """

    grounded = "grounded"
    insufficient_context = "insufficient_context"


class MessageFeedback(str, enum.Enum):
    helpful = "helpful"
    not_helpful = "not_helpful"


class Conversation(Base, _ProjectChildMixin, TimestampMixin):
    """Uma thread de chat, de uma pessoa, dentro de um projeto.

    Tem dono, como ``notification``: a policy soma ``user_id`` ao predicado de
    tenant, e dois clientes do mesmo projeto não leem a conversa um do outro.
    """

    __tablename__ = "conversation"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: As primeiras palavras da primeira pergunta. Rótulo de lista, não resumo:
    #: resumir exigiria mandar a conversa ao modelo de novo.
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    #: Ordena a lista e responde "qual é a thread corrente". Separado de
    #: ``updated_at`` porque marcar um feedback não é conversar.
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ConversationMessage(Base, _ProjectChildMixin, TimestampMixin):
    __tablename__ = "conversation_message"
    __table_args__ = (
        # Um turno ocupa uma posição só. É o que deixa o histórico ser ordenado
        # sem depender do relógio — dois inserts na mesma transação compartilham
        # o `now()`.
        UniqueConstraint("conversation_id", "ordinal", name="uq_conversation_message_conversation_id"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Denormalizado da conversa pelo mesmo motivo que ``project_id`` é
    #: denormalizado nas tabelas-filhas (``db/base.TenantMixin``): a policy vira
    #: uma comparação de coluna em vez de um EXISTS na conversa, avaliado linha a
    #: linha. O dono da mensagem é sempre o dono da thread.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[ConversationRole] = mapped_column(
        Enum(ConversationRole, name="conversation_role"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # --- só na mensagem do assistente ---------------------------------------
    confidence: Mapped[MessageConfidence | None] = mapped_column(
        Enum(MessageConfidence, name="message_confidence"), nullable=True
    )
    #: As citações **como foram exibidas**, em JSONB, no padrão de
    #: ``audit_log.data``. Não é uma terceira tabela porque uma citação só faz
    #: sentido dentro da mensagem que a mostrou, e o produto nunca a consulta
    #: sozinha. Cada item é ``{evidence_id, source, location}``: o ``evidence_id``
    #: (``chunk-<uuid>``, ``milestone-<uuid>``) é o que torna "quais trechos são
    #: citados de fato" respondível; ``source``/``location`` são o rótulo que a
    #: pessoa viu, e continuam valendo mesmo que o documento seja renomeado
    #: depois — o registro é do que foi mostrado, não do que virou.
    citations: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    #: A pendência que a lacuna abriu, quando abriu (ADR 0007).
    pending_item_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pending_item.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- avaliação da pessoa que perguntou -----------------------------------
    feedback: Mapped[MessageFeedback | None] = mapped_column(
        Enum(MessageFeedback, name="message_feedback"), nullable=True
    )
    #: Opcional, e por isso mesmo o campo mais informativo do conjunto: o polegar
    #: diz que errou, o comentário diz o quê.
    feedback_comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
