"""Conversation repositories (escopados por projeto **e** por dono).

Mesma disciplina do :mod:`~portal_api.repositories.notification`: o ``user_id``
entra em todo filtro além do tenant, ainda que a RLS repita a condição. As duas
barreiras da ADR 0002 existem separadas justamente para uma consulta que rodasse
sob o papel errado continuar correta.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from portal_api.models import Conversation, ConversationMessage, MessageFeedback
from portal_api.repositories.base import TenantScopedRepository


class ConversationRepository(TenantScopedRepository[Conversation]):
    model = Conversation

    def get_for_user(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> Conversation | None:
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            *self._tenant_filters(),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def latest_for_user(self, user_id: uuid.UUID) -> Conversation | None:
        """A thread corrente: a que recebeu mensagem por último.

        Ordena por ``last_message_at`` e não por ``updated_at`` porque marcar um
        feedback numa conversa antiga não a torna a corrente.
        """
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id, *self._tenant_filters())
            .order_by(Conversation.last_message_at.desc(), Conversation.created_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalars().first()


class ConversationMessageRepository(TenantScopedRepository[ConversationMessage]):
    model = ConversationMessage

    def list_for_conversation(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID, *, limit: int = 50
    ) -> list[ConversationMessage]:
        """Os últimos ``limit`` turnos, devolvidos em ordem cronológica.

        O corte é pelo fim — uma conversa longa perde o começo, não o que acabou
        de ser dito — e a reordenação acontece aqui, para quem chama não precisar
        saber que a consulta desceu para cortar.
        """
        stmt = (
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.user_id == user_id,
                *self._tenant_filters(),
            )
            .order_by(ConversationMessage.ordinal.desc())
            .limit(limit)
        )
        found = list(self.session.execute(stmt).scalars())
        return sorted(found, key=lambda message: message.ordinal)

    def next_ordinal(self, conversation_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(ConversationMessage.ordinal), -1)).where(
            ConversationMessage.conversation_id == conversation_id,
            *self._tenant_filters(),
        )
        return int(self.session.execute(stmt).scalar_one()) + 1

    def get_for_user(
        self, message_id: uuid.UUID, user_id: uuid.UUID
    ) -> ConversationMessage | None:
        stmt = select(ConversationMessage).where(
            ConversationMessage.id == message_id,
            ConversationMessage.user_id == user_id,
            *self._tenant_filters(),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def set_feedback(
        self,
        message: ConversationMessage,
        feedback: MessageFeedback,
        comment: str | None,
    ) -> ConversationMessage:
        """Escreve as três colunas que ``portal_app`` pode escrever, e só elas.

        Um UPDATE mais largo daqui não passaria despercebido: o grant de coluna
        da migração 0012 o faria falhar no banco.
        """
        message.feedback = feedback
        message.feedback_comment = comment
        message.feedback_at = datetime.now(timezone.utc)
        self.session.flush()
        return message
