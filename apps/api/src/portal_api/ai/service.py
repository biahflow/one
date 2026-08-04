"""Chat orchestration: retrieve evidence → answer → cite, or declare the gap + pendência.

Enforces the contract regardless of the responder: a factual answer must carry citations to
real evidence; otherwise the turn is a gap that creates a pendência (never an invented fact).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from portal_api.ai.responder import GAP_MESSAGE, get_responder
from portal_api.ai.retrieval import Evidence, collect_evidence
from portal_api.config import Settings
from portal_api.models import PendingItem, PendingPriority, Project
from portal_api.repositories import PendingItemRepository, TenantContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatResult:
    answer: str
    sources: list[str]
    confidence: str  # "grounded" | "insufficient_context"
    pending_created: bool


def _create_pendencia(session: Session, ctx: TenantContext, question: str) -> None:
    PendingItemRepository(session, ctx).add(
        PendingItem(
            title=f"Responder dúvida do cliente: {question[:160]}",
            description="Pergunta sem evidência suficiente no contexto do projeto (chat).",
            owner_label="Portal Labs",
            priority=PendingPriority.medium,
        )
    )


def answer_question(
    session: Session,
    ctx: TenantContext,
    project: Project,
    question: str,
    settings: Settings,
) -> ChatResult:
    evidence = collect_evidence(session, ctx, project)
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
        _create_pendencia(session, ctx, question)
        return ChatResult(
            answer=result.answer if not result.sufficient else GAP_MESSAGE,
            sources=[],
            confidence="insufficient_context",
            pending_created=True,
        )

    return ChatResult(
        answer=result.answer,
        sources=[item.citation for item in cited],
        confidence="grounded",
        pending_created=False,
    )
