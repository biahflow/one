"""Evidence retrieval from the project read model, strictly tenant-scoped.

Per docs/ai/context-contract.md the retriever receives the tenant/project context and only
returns evidence matching it. The scoped repositories enforce that filter, so a caller can
never retrieve another project's rows.

Duas fontes, uma forma. :func:`collect_evidence` lê o read model estruturado
(projeto, marcos, pendências) e :func:`collect_document_evidence` lê o índice dos
documentos por similaridade (ADR 0014). As duas devolvem :class:`Evidence`, e é
por isso que ligar o RAG não custou uma linha no prompt, no respondedor ou na
política de citação: o contrato entre recuperação e resposta já era este.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from portal_api.ai.embeddings import get_embedder
from portal_api.config import Settings
from portal_api.models import (
    MilestoneState,
    PendingState,
    Project,
    ProjectStatus,
)
from portal_api.repositories import (
    DocumentChunkRepository,
    DocumentRepository,
    MilestoneRepository,
    PendingItemRepository,
    TenantContext,
)

logger = logging.getLogger(__name__)

PROJECT_STATUS_LABELS: dict[ProjectStatus, str] = {
    ProjectStatus.discovery: "em descoberta",
    ProjectStatus.in_implementation: "em implementação",
    ProjectStatus.live: "em produção",
    ProjectStatus.paused: "pausado",
}
MILESTONE_STATE_LABELS: dict[MilestoneState, str] = {
    MilestoneState.planned: "planejado",
    MilestoneState.in_progress: "em andamento",
    MilestoneState.next: "próxima entrega",
    MilestoneState.done: "concluído",
}
_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _short_date(value: date | None) -> str:
    return f"{value.day:02d} {_MONTHS[value.month - 1]}" if value else ""


@dataclass(frozen=True)
class Evidence:
    """A single citable fact from the read model."""

    id: str
    source: str
    location: str
    text: str
    #: O documento por trás da citação, quando há um arquivo (Fase 5, ADR 0017).
    #: Vazio para a evidência que vem do read model — um marco não é um arquivo
    #: e não tem o que abrir. É o que permite à citação virar link em vez de
    #: pedir que o cliente confie no rótulo.
    document_id: str = ""

    @property
    def citation(self) -> str:
        return f"{self.source} — {self.location}" if self.location else self.source


def collect_evidence(session: Session, ctx: TenantContext, project: Project) -> list[Evidence]:
    """Gather the project's citable facts (project, milestones, open pendings) for ``ctx``."""
    status_label = PROJECT_STATUS_LABELS.get(project.status, project.status.value)
    evidence: list[Evidence] = [
        Evidence(
            id="project",
            source="Status do projeto",
            location=f"{project.completion_percent}% concluído",
            text=(
                f"O projeto '{project.name}' está {status_label} e "
                f"{project.completion_percent}% concluído."
            ),
        )
    ]

    milestones = sorted(
        MilestoneRepository(session, ctx).list(), key=lambda item: item.position
    )
    for milestone in milestones:
        state_label = MILESTONE_STATE_LABELS.get(milestone.state, milestone.state.value)
        due = _short_date(milestone.due_date)
        text = f"O marco '{milestone.title}' está {state_label}"
        text += f", previsto para {due}." if due else "."
        evidence.append(
            Evidence(
                id=f"milestone-{milestone.id}",
                source=f"Marco: {milestone.title}",
                location=due,
                text=text,
            )
        )

    for pending in PendingItemRepository(session, ctx).list():
        if pending.state == PendingState.resolved:
            continue
        owner = f" (responsável: {pending.owner_label})" if pending.owner_label else ""
        evidence.append(
            Evidence(
                id=f"pending-{pending.id}",
                source=f"Pendência: {pending.title}",
                location="",
                text=f"Há uma pendência aberta: '{pending.title}'{owner}.",
            )
        )

    return evidence


def collect_document_evidence(
    session: Session, ctx: TenantContext, question: str, settings: Settings
) -> list[Evidence]:
    """Os trechos de documento mais próximos da pergunta, dentro do tenant.

    O corte de distância vem do próprio embedder, e não da configuração da
    recuperação: ele é uma propriedade do espaço vetorial (ver
    :mod:`portal_api.ai.embeddings`). Sem trecho dentro do corte a lista volta
    vazia — que é como esta função declara "não há evidência", deixando o
    serviço abrir a pendência em vez de citar o menos distante.
    """
    if not question.strip():
        return []

    embedder = get_embedder(settings)
    try:
        vector = embedder.embed_query(question)
    except Exception as exc:
        # Provedor fora do ar degrada para o read model estruturado, que já
        # responde parte das perguntas. Ficar sem chat inteiro seria pior.
        logger.warning("Embeddings indisponíveis; recuperando só o read model: %s", exc)
        return []

    matches = DocumentChunkRepository(session, ctx).search(
        vector, limit=settings.rag_top_k, max_distance=embedder.max_distance
    )
    documents = DocumentRepository(session, ctx)
    titles: dict[str, str] = {}
    evidence: list[Evidence] = []
    for chunk, _distance in matches:
        key = str(chunk.document_id)
        if key not in titles:
            document = documents.get(chunk.document_id)
            if document is None:
                continue
            titles[key] = document.title
        evidence.append(
            Evidence(
                id=f"chunk-{chunk.id}",
                source=f"Documento: {titles[key]}",
                location=chunk.location,
                text=chunk.text,
                document_id=key,
            )
        )
    return evidence
