"""Chat orchestration: retrieve evidence → answer → cite, or declare the gap + pendência.

Enforces the contract regardless of the responder: a factual answer must carry citations to
real evidence; otherwise the turn is a gap that creates a pendência (never an invented fact).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from portal_api.ai.responder import GAP_MESSAGE, get_responder
from portal_api.ai.retrieval import Evidence, collect_document_evidence, collect_evidence
from portal_api.config import Settings
from portal_api.models import AuditLog, PendingItem, PendingPriority, Project
from portal_api.repositories import (
    AuditLogRepository,
    PendingItemRepository,
    TenantContext,
)

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
            data={"reason": "insufficient_context"},
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

    try:
        result = get_responder(settings).answer(evidence, question)
    except Exception as exc:  # provider failure → deterministic offline fallback (runbook)
        logger.warning("Provedor de IA indisponível, usando fallback offline: %s", exc)
        from portal_api.ai.responder import OfflineResponder

        result = OfflineResponder().answer(evidence, question)

    # Only citations that point at real evidence count — no fabricated sources.
    cited = [by_id[sid] for sid in result.source_ids if sid in by_id]

    # Cite-or-gap: a factual answer without a real citation is treated as a gap.
    if not result.sufficient or not cited:
        pending_id = _create_pendencia(session, ctx, question, actor_user_id)
        return ChatResult(
            answer=result.answer if not result.sufficient else GAP_MESSAGE,
            sources=[],
            confidence="insufficient_context",
            pending_created=True,
            pending_id=pending_id,
        )

    return ChatResult(
        answer=result.answer,
        sources=[item.citation for item in cited],
        confidence="grounded",
        pending_created=False,
    )
