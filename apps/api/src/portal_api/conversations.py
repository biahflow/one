"""O único lugar onde uma conversa é escrita (ADR 0015).

Mesmo desenho de :mod:`portal_api.notifications`, e pela mesma razão: se
"quem grava um turno" estiver espalhado, a pergunta *o que o portal guarda do que
o cliente digita* deixa de ter uma resposta que se lê num arquivo. Aqui ela tem.

Duas funções e nada mais. :func:`append_turn` grava o par pergunta/resposta ao
fim da thread; :func:`record_feedback` carimba a avaliação. Não há função que
edite uma mensagem, e não é por esquecimento — o grant de coluna da migração 0012
não permitiria de qualquer forma.

**Nada daqui volta para a recuperação.** ``ai/retrieval.py`` não conhece este
módulo, e é esse fato — não um privilégio de banco — que impede uma frase
plantada num turno de virar citação no seguinte.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from portal_api.ai.service import ChatResult
from portal_api.models import (
    Conversation,
    ConversationMessage,
    ConversationRole,
    MessageConfidence,
    MessageFeedback,
    MessageResponder,
)
from portal_api.repositories import (
    ConversationMessageRepository,
    ConversationRepository,
    TenantContext,
)

#: Quantos turnos o histórico devolve. Corte pelo fim: uma conversa longa perde o
#: começo, não o que acabou de ser dito.
HISTORY_LIMIT = 50

#: O título é rótulo de lista, não resumo — resumir exigiria mandar a conversa ao
#: modelo outra vez, e a lista não vale uma chamada de inferência.
TITLE_LENGTH = 80


def _title_from(question: str) -> str:
    clean = " ".join(question.split())
    if len(clean) <= TITLE_LENGTH:
        return clean
    return clean[:TITLE_LENGTH].rstrip() + "…"


def _citations_of(result: ChatResult) -> list[dict] | None:
    """As citações como foram exibidas, mais o id da evidência que as gerou.

    O ``evidence_id`` (``chunk-<uuid>``, ``milestone-<uuid>``) é o que torna
    "quais trechos são citados de fato" respondível — o insumo para calibrar o
    corte de distância que a ADR 0014 deixou em aberto. ``source``/``location``
    são o rótulo que a pessoa viu, e continuam valendo mesmo que o documento
    mude de nome: o registro é do que foi mostrado.

    ``document_id`` (Fase 5, ADR 0017) é o que permite reabrir o arquivo a partir
    do histórico. Fica ausente quando a evidência veio do read model, e continua
    sendo só um ponteiro: se o documento for apagado depois, o rótulo gravado
    segue contando o que a resposta mostrou, e é o link que deixa de abrir.

    ``dated_at`` (ADR 0038) é a data **daquela** versão da fonte, e é o campo que
    torna o parágrafo acima verificável em vez de só verdadeiro. O ponteiro abre o
    documento de hoje, e o sync do Drive reindexa a mesma linha quando o arquivo
    muda: sem a data, uma resposta de março e o arquivo de agosto usam rótulo
    idêntico. Ausente para quem não tem data de fonte, pela mesma razão de
    :class:`~portal_api.ai.retrieval.Evidence`.
    """
    if not result.cited:
        return None
    return [
        {
            "evidence_id": evidence.id,
            "source": evidence.source,
            "location": evidence.location,
            **({"document_id": evidence.document_id} if evidence.document_id else {}),
            **({"dated_at": evidence.dated_at.isoformat()} if evidence.dated_at else {}),
        }
        for evidence in result.cited
    ]


def append_turn(
    session: Session,
    ctx: TenantContext,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    question: str,
    result: ChatResult,
) -> tuple[Conversation, ConversationMessage]:
    """Grava a pergunta e a resposta ao fim da thread, abrindo-a se preciso.

    ``conversation_id`` desconhecido — ou de outra pessoa — **abre uma conversa
    nova** em vez de responder 404: o turno já foi respondido quando chegamos
    aqui, e derrubar a requisição por causa de um id velho no cliente perderia a
    resposta para punir o cliente por um estado obsoleto. É a mesma escolha de
    degradar em vez de derrubar que ``queue_*`` faz com o broker morto.
    """
    conversations = ConversationRepository(session, ctx)
    messages = ConversationMessageRepository(session, ctx)
    now = datetime.now(timezone.utc)

    conversation = (
        conversations.get_for_user(conversation_id, user_id)
        if conversation_id is not None
        else None
    )
    if conversation is None:
        conversation = conversations.add(
            Conversation(
                user_id=user_id,
                title=_title_from(question),
                last_message_at=now,
            )
        )

    ordinal = messages.next_ordinal(conversation.id)
    messages.add(
        ConversationMessage(
            conversation_id=conversation.id,
            user_id=user_id,
            ordinal=ordinal,
            role=ConversationRole.user,
            text=question,
        )
    )
    answer = messages.add(
        ConversationMessage(
            conversation_id=conversation.id,
            user_id=user_id,
            ordinal=ordinal + 1,
            role=ConversationRole.assistant,
            text=result.answer,
            confidence=MessageConfidence(result.confidence),
            citations=_citations_of(result),
            pending_item_id=result.pending_id,
            # Quem produziu a resposta, junto dela (ADR 0021). Só na mensagem do
            # assistente: a pergunta é da pessoa e nenhum prompt a produziu.
            prompt_version=result.prompt_version,
            responder=MessageResponder(result.responder),
            model=result.model,
        )
    )
    conversation.last_message_at = now
    session.flush()
    return conversation, answer


def record_feedback(
    session: Session,
    ctx: TenantContext,
    *,
    user_id: uuid.UUID,
    message_id: uuid.UUID,
    helpful: bool,
    comment: str | None = None,
) -> ConversationMessage | None:
    """Carimba a avaliação da própria pessoa. ``None`` quando a mensagem não é dela.

    Reenviar sobrescreve o voto anterior: o polegar é o estado atual da opinião,
    não um evento — não há o que deduplicar.
    """
    messages = ConversationMessageRepository(session, ctx)
    message = messages.get_for_user(message_id, user_id)
    if message is None or message.role is not ConversationRole.assistant:
        # Avaliar a própria pergunta não é opinião sobre nada, e a resposta é a
        # mesma de uma mensagem inexistente: quem chama não descobre a diferença.
        return None
    return messages.set_feedback(
        message,
        MessageFeedback.helpful if helpful else MessageFeedback.not_helpful,
        comment,
    )
