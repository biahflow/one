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
    PendingOrigin,
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
    #: **Quando a fonte data o fato**, e só aí (ADR 0038). O documento sabe quando
    #: mudou (`source_updated_at`) e a pendência sabe quando foi aberta, porque as
    #: duas datas vêm do Biahflow ou do Drive. O marco e o status ficam ``None`` de
    #: propósito: a linha do marco é **apagada e recriada a cada sincronização**, de
    #: modo que o `created_at` dela diz quando o portal copiou, não quando o fato
    #: aconteceu — carimbar isso como data da evidência seria a falsa precisão que
    #: `results.py` recusa quando falta premissa. Quem não tem data declara a lacuna
    #: pela ausência, e o prompt leva a data da sincronização à parte.
    dated_at: date | None = None

    @property
    def citation(self) -> str:
        """O rótulo como o cliente o vê, com a data da fonte quando existe.

        Sem `dated_at` o rótulo sai byte a byte como saía antes da ADR 0038 — é o
        que mantém verdes as asserções de rótulo que já existiam, e é a forma de
        não fingir data para quem não tem.
        """
        label = f"{self.source} — {self.location}" if self.location else self.source
        return f"{label} ({self.dated_at:%d/%m/%Y})" if self.dated_at else label


def collect_evidence(session: Session, ctx: TenantContext, project: Project) -> list[Evidence]:
    """Gather the project's citable facts (project, milestones, open pendings) for ``ctx``."""
    status_label = PROJECT_STATUS_LABELS.get(project.status, project.status.value)
    # A data da sincronização entra no **texto** desta evidência, e não no `dated_at`
    # dela (ADR 0038). O `dated_at` é "quando a fonte data o fato", e o status não
    # tem essa data: o que existe é "quando copiamos o estado". Dizer isso na frase
    # deixa o modelo saber de quando é o retrato sem que o rótulo da citação passe a
    # significar duas coisas diferentes conforme a espécie da evidência. É também a
    # razão de não haver parâmetro novo no `Responder`: o "estado em" pertence a
    # esta evidência, que já é a frase que o portal escreve sobre o projeto inteiro.
    synced = f" Estado sincronizado em {project.updated_at:%d/%m/%Y}." if project.updated_at else ""
    evidence: list[Evidence] = [
        Evidence(
            id="project",
            source="Status do projeto",
            location=f"{project.completion_percent}% concluído",
            text=(
                f"O projeto '{project.name}' está {status_label} e "
                f"{project.completion_percent}% concluído.{synced}"
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
        # **A lacuna de ontem não é a evidência de hoje.** Quando o assistente não
        # acha resposta ele abre uma pendência cujo título carrega a pergunta
        # (`ai/service.py`), e essa linha volta aqui como evidência com
        # `source="Pendência: Responder dúvida do cliente: <pergunta>"`. O casador
        # do `OfflineResponder` aceita qualquer evidência que compartilhe um token
        # de quatro letras com a pergunta, então a pergunta seguinte casa a lacuna
        # que a anterior gerou — e o turno sai `sufficient=True` citando o próprio
        # fracasso, cada rodada deixando mais material para a próxima.
        #
        # É a regra 3 do `AGENTS.md` pelo avesso: a resposta cita fonte, e a fonte
        # é o portal repetindo a pergunta do cliente. A mesma razão que faz
        # `conversation_message` nunca ser fonte de recuperação (ADR 0015) vale
        # aqui, porque o conteúdo é o mesmo — o que o cliente digitou.
        #
        # O recorte é por `origin` e não por texto: só dois sítios criam
        # `PendingItem`, e o do chat é o único que cai no default `portal`, então
        # a coluna responde exatamente à pergunta "isto veio da fonte?". É o mesmo
        # discriminador que `sync_snapshot` já usa para não apagar as do chat.
        if pending.origin is not PendingOrigin.biahflow:
            continue
        owner = f" (responsável: {pending.owner_label})" if pending.owner_label else ""
        evidence.append(
            Evidence(
                id=f"pending-{pending.id}",
                source=f"Pendência: {pending.title}",
                location="",
                text=f"Há uma pendência aberta: '{pending.title}'{owner}.",
                # Quando foi **aberta**, e é data de fonte de verdade: `sync_snapshot`
                # carimba o `created_at` desta linha com o `opened_at` do Biahflow em
                # vez de deixá-lo com a hora da cópia (ADR 0038).
                dated_at=pending.created_at.date() if pending.created_at else None,
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
        #
        # Nome **distinto** de `embedding.failed` (worker.py), de propósito: lá o
        # documento fica fora do índice e o efeito é permanente até alguém
        # reindexar; aqui o chat perdeu a metade documental de *uma* resposta e a
        # seguinte pode dar certo. O mesmo nome faria o limiar do `alerts.md`
        # significar duas coisas, que é como um alerta deixa de ser lido.
        logger.warning(
            "embedding.unavailable",
            extra={"model": embedder.model_name, "reason": type(exc).__name__},
        )
        return []

    matches = DocumentChunkRepository(session, ctx).search(
        vector, limit=settings.rag_top_k, max_distance=embedder.max_distance
    )
    documents = DocumentRepository(session, ctx)
    #: Título **e** data por documento, resolvidos uma vez por linha e não por trecho.
    seen: dict[str, tuple[str, date | None]] = {}
    evidence: list[Evidence] = []
    for chunk, _distance in matches:
        key = str(chunk.document_id)
        if key not in seen:
            document = documents.get(chunk.document_id)
            if document is None:
                continue
            # `source_updated_at` é o que a **fonte** diz (o `modifiedTime` do Drive,
            # a data do upload); `indexed_at` é o que este lado sabe, e serve de
            # segunda escolha porque um documento indexado sem data de origem ainda
            # tem um "desde quando este texto está citável" (ADR 0038).
            stamp = document.source_updated_at or document.indexed_at
            seen[key] = (document.title, stamp.date() if stamp else None)
        title, dated_at = seen[key]
        evidence.append(
            Evidence(
                id=f"chunk-{chunk.id}",
                source=f"Documento: {title}",
                location=chunk.location,
                text=chunk.text,
                document_id=key,
                dated_at=dated_at,
            )
        )
    return evidence
