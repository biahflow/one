"""Chat orchestration: retrieve evidence → answer → cite, or declare the gap + pendência.

Enforces the contract regardless of the responder: a factual answer must carry citations to
real evidence; otherwise the turn is a gap that creates a pendência (never an invented fact).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from portal_api.ai import quota
from portal_api.ai.prompt import PROMPT_VERSION
from portal_api.ai.responder import GAP_MESSAGE, get_responder
from portal_api.ai.retrieval import Evidence, collect_document_evidence, collect_evidence
from portal_api.config import Settings
from portal_api.models import AuditLog, PendingItem, PendingPriority, Project
from portal_api.repositories import (
    AuditLogRepository,
    PendingItemRepository,
    TenantContext,
)
from portal_api.telemetry import audit_data

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatResult:
    answer: str
    sources: list[str]
    confidence: str  # "grounded" | "insufficient_context"
    pending_created: bool
    #: Id da pendência aberta, para o endpoint avisar o time interno (ADR 0012).
    #: A notificação não nasce aqui porque o chat roda sob `portal_app`, que não
    #: escreve em `notification` — quem escreve é o worker, sob `portal_system`.
    pending_id: uuid.UUID | None = None
    #: As evidências citadas, inteiras. ``sources`` continua sendo a projeção de
    #: exibição; quem grava a conversa (ADR 0015) precisa do ``id`` da evidência,
    #: e recuperá-lo a partir do rótulo seria adivinhar.
    cited: tuple[Evidence, ...] = ()
    #: Quem produziu esta resposta, para a linha guardar (ADR 0021). Sem isto,
    #: "esta resposta ruim veio de qual prompt?" e "quais turnos são comparáveis
    #: nesta eval?" não têm resposta seis semanas depois — e o log, que teria a
    #: outra metade, já rodou.
    prompt_version: str = PROMPT_VERSION
    #: ``offline`` | ``anthropic`` | ``offline_fallback``. São três fatos
    #: distintos, não dois: o terceiro é o que faz "por que as respostas pioraram
    #: na terça?" ser respondível pela **linha**.
    responder: str = "offline"
    #: ``None`` nos caminhos offline, onde o "modelo" é este código e quem o
    #: versiona é o git.
    model: str | None = None


def _create_pendencia(
    session: Session,
    ctx: TenantContext,
    question: str,
    actor_user_id: uuid.UUID | None,
) -> uuid.UUID:
    pending = PendingItemRepository(session, ctx).add(
        PendingItem(
            title=f"Responder dúvida do cliente: {question[:160]}",
            description="Pergunta sem evidência suficiente no contexto do projeto (chat).",
            owner_label="Portal Labs",
            priority=PendingPriority.medium,
        )
    )
    # Who asked, not what was asked: the question is customer content and does
    # not belong in the audit log (docs/data-classification.md).
    AuditLogRepository(session, ctx).add(
        AuditLog(
            actor_user_id=actor_user_id,
            action="chat.pending_created",
            entity_type="pending_item",
            entity_id=pending.id,
            data=audit_data(reason="insufficient_context"),
        )
    )
    return pending.id


def answer_question(
    session: Session,
    ctx: TenantContext,
    project: Project,
    question: str,
    settings: Settings,
    *,
    actor_user_id: uuid.UUID | None = None,
) -> ChatResult:
    # Read model estruturado + trechos dos documentos indexados (ADR 0014). As
    # duas fontes entram na mesma lista porque a política de citação vale igual
    # para as duas: o que não estiver aqui não pode ser afirmado.
    evidence = collect_evidence(session, ctx, project) + collect_document_evidence(
        session, ctx, question, settings
    )
    by_id: dict[str, Evidence] = {item.id: item for item in evidence}

    responder = get_responder(settings)
    responder_name, responder_model = responder.name, responder.model
    try:
        result = responder.answer(evidence, question)
    except Exception as exc:  # provider failure → deterministic offline fallback (runbook)
        # A mensagem **é** o nome do evento e o detalhe vai em `extra` (ADR 0018).
        # Até a Fase 5 isto era um `logger.warning` com interpolação e sem nome, e
        # como a exceção é engolida aqui o `http.failed` do `TraceMiddleware` nunca
        # dispara — de modo que o `ai-provider-failure.md` mandava procurar um
        # evento que não existia, e uma queda do provedor degradava em silêncio.
        logger.warning(
            "chat.provider_unavailable",
            extra={
                "responder": responder_name,
                "model": responder_model,
                "reason": type(exc).__name__,
            },
        )
        from portal_api.ai.responder import OfflineResponder

        result = OfflineResponder().answer(evidence, question)
        responder_name, responder_model = "offline_fallback", None

    # Only citations that point at real evidence count — no fabricated sources.
    cited = [by_id[sid] for sid in result.source_ids if sid in by_id]

    # O consumo entra no razão **antes** do desfecho do turno, e de propósito: a
    # chamada custou tanto tendo respondido quanto tendo virado lacuna, e cobrar
    # só a resposta útil ensinaria que perguntas ruins são de graça (ADR 0022). A
    # linha é escrita nesta transação, então um turno revertido não cobra.
    quota.record(
        session,
        ctx,
        responder=responder_name,
        model=responder_model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )

    stamp = {
        "prompt_version": PROMPT_VERSION,
        "responder": responder_name,
        "model": responder_model,
    }
    # Os mesmos números no log, e não por redundância: o razão vive na transação
    # do turno e some com a retenção; o log fica fora dos dois. É o par que torna
    # "quanto de fato saiu" reconciliável com "quanto está contabilizado", e é de
    # onde `docs/observability.md` passa a tirar o indicador de custo de IA que
    # já listava sem que nada o medisse.
    usage = {
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }

    # Cite-or-gap: a factual answer without a real citation is treated as a gap.
    if not result.sufficient or not cited:
        pending_id = _create_pendencia(session, ctx, question, actor_user_id)
        logger.info(
            "chat.answered",
            extra={**stamp, **usage, "confidence": "insufficient_context", "citations": 0},
        )
        return ChatResult(
            answer=result.answer if not result.sufficient else GAP_MESSAGE,
            sources=[],
            confidence="insufficient_context",
            pending_created=True,
            pending_id=pending_id,
            **stamp,
        )

    logger.info(
        "chat.answered",
        extra={**stamp, **usage, "confidence": "grounded", "citations": len(cited)},
    )
    return ChatResult(
        answer=result.answer,
        sources=[item.citation for item in cited],
        confidence="grounded",
        pending_created=False,
        cited=tuple(cited),
        **stamp,
    )
