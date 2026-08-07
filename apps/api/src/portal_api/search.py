"""A busca do projeto — o único lugar onde um termo digitado vira linhas (ADR 0024).

Mesma forma de :mod:`portal_api.notifications`, :mod:`portal_api.conversations` e
:mod:`portal_api.retention`: a operação nasce em cinco repositórios diferentes, e
espalhar a projeção faria "o que a busca alcança" deixar de caber num arquivo —
que é justamente a pergunta que alguém faz ao revisar isolamento.

Duas fontes, um resultado, e as duas passam pelo mesmo par de barreiras: o filtro
do ``TenantScopedRepository`` primeiro, a RLS depois. As **linhas** do read model
(documento, reunião, pendência, marco) casam por título e descrição; os
**trechos** de documento casam por full-text, e é o que faz "buscar no contexto do
projeto" — a frase que a tela já dizia — valer para o conteúdo do contrato e não
só para o nome dele.

Três regras governam o que sai daqui:

1. **Só entra o que o cliente já alcança por alguma aba.** ``Decision`` tem
   modelo desde a Fase 1 e não é projetada em ``build_dashboard``: um hit dela
   levaria a lugar nenhum, que é a mesma classe de defeito que a ADR 0017
   corrigiu ao transformar a citação em link. Quando existir aba de decisões,
   entra aqui junto.
2. **O trecho só existe se o documento passou pela varredura.** Hoje um
   documento não varrido não chega a ter chunk — o ``ingest_document`` recusa —,
   e a asserção fica escrita mesmo assim, porque "não tem como acontecer" é como
   o portal descobriria que passou a ter (ver ``document_download`` em
   ``main.py``, que faz o mesmo pelo mesmo motivo).
3. **A busca não erra, ela não acha.** Termo curto demais, termo só de espaços
   ou termo sem casamento devolvem lista vazia — nunca 422, nunca "o resultado
   mais próximo". Um resultado por aproximação é o análogo, aqui, do trecho menos
   distante que o corte de :mod:`portal_api.ai.retrieval` recusa citar.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import ColumnElement, func, or_
from sqlalchemy.orm import Session

from portal_api.tabs import (
    TAB_DOCUMENTS,
    TAB_MEETINGS,
    TAB_PENDINGS,
    TAB_SCHEDULE,
)
from portal_api.models import (
    Document,
    DocumentChunk,
    Meeting,
    Milestone,
    PendingItem,
)
from portal_api.repositories import (
    DocumentChunkRepository,
    DocumentRepository,
    MeetingRepository,
    MilestoneRepository,
    PendingItemRepository,
    TenantContext,
)
from portal_api.scanner import ScanState
from portal_api.textfold import REGCONFIG, fold, folded, text_vector

#: Abaixo disto a busca não roda. Uma letra casa com metade do projeto e a lista
#: deixa de informar; o debounce da tela evita a maior parte destas chamadas, e
#: este é o lado do servidor da mesma decisão.
MIN_QUERY_LENGTH = 2

#: Teto por espécie e teto geral. O primeiro é o que impede um projeto com
#: duzentos documentos de esconder a única reunião que casou.
PER_KIND_LIMIT = 5
TOTAL_LIMIT = 20

#: Para onde o clique leva. Os valores são os rótulos de `navItems` em
#: `app/DashboardClient.tsx` — a tela navega por rótulo desde a Fase 2, então
#: mandar o rótulo pronto evita um segundo mapa do lado do navegador que
#: envelheceria sozinho.
#:
#: *Mudaram de casa na ADR 0043, e não de valor* — agora vêm de
#: :mod:`portal_api.tabs`, importado no topo. O link do aviso passou a precisar dos
#: mesmos rótulos, e três cópias de um literal que **tem** de ser idêntico é o modo
#: de falha do ``textfold.py``: divergem sem nada ficar vermelho.


@dataclass(frozen=True)
class Hit:
    """Uma linha do resultado, já no formato que a tela mostra.

    ``document_id`` só vem preenchido quando há arquivo por trás — é o que
    permite ao trecho abrir a fonte pela rota de download assinado que já existe
    (ADR 0017), em vez de pedir que o cliente confie no rótulo.
    """

    kind: str
    title: str
    detail: str
    location: str
    tab: str
    document_id: str = ""

    def to_payload(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "location": self.location,
            "tab": self.tab,
            "document_id": self.document_id,
        }


def _like_pattern(term: str) -> str:
    """``%termo%`` com os curingas do LIKE neutralizados.

    Sem isto um ``%`` digitado casaria com o projeto inteiro e um ``_`` com
    qualquer caractere — a busca passaria a responder a uma sintaxe que ninguém
    documentou e que o cliente não sabe que está usando.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _matches(pattern: str, *columns: ColumnElement[str]) -> ColumnElement[bool]:
    return or_(*(folded(column).like(pattern, escape="\\") for column in columns))


def search_project(session: Session, ctx: TenantContext, query: str) -> list[Hit]:
    """Os resultados da busca dentro de ``ctx``, prontos para a tela.

    Determinístico e sem rede: o teste executa esta função direto, e a rota é uma
    casca em volta dela — a mesma divisão de ``results.compute_results``.
    """
    term = fold(query.strip())
    if len(term) < MIN_QUERY_LENGTH:
        return []

    pattern = _like_pattern(term)
    hits: list[Hit] = []

    documents = DocumentRepository(session, ctx)
    for document in documents.matching(
        _matches(pattern, Document.title, func.coalesce(Document.author_label, "")),
        order_by=(Document.source_updated_at.desc().nulls_last(), Document.title),
        limit=PER_KIND_LIMIT,
    ):
        hits.append(
            Hit(
                kind="document",
                title=document.title,
                detail=document.author_label or "",
                location="",
                tab=TAB_DOCUMENTS,
                document_id=(
                    str(document.id)
                    if document.storage_key
                    and document.scan_state in (ScanState.clean, ScanState.skipped)
                    else ""
                ),
            )
        )

    meetings = MeetingRepository(session, ctx)
    for meeting in meetings.matching(
        _matches(pattern, Meeting.title, func.coalesce(Meeting.summary, "")),
        order_by=(Meeting.held_at.desc().nulls_last(), Meeting.title),
        limit=PER_KIND_LIMIT,
    ):
        hits.append(
            Hit(
                kind="meeting",
                title=meeting.title,
                detail=meeting.status or "",
                location="",
                tab=TAB_MEETINGS,
            )
        )

    pendings = PendingItemRepository(session, ctx)
    for pending in pendings.matching(
        _matches(
            pattern,
            PendingItem.title,
            func.coalesce(PendingItem.description, ""),
            func.coalesce(PendingItem.owner_label, ""),
        ),
        order_by=(PendingItem.created_at.desc(), PendingItem.title),
        limit=PER_KIND_LIMIT,
    ):
        hits.append(
            Hit(
                kind="pending",
                title=pending.title,
                detail=pending.owner_label or "",
                location="",
                tab=TAB_PENDINGS,
            )
        )

    milestones = MilestoneRepository(session, ctx)
    for milestone in milestones.matching(
        _matches(pattern, Milestone.title, func.coalesce(Milestone.owner_label, "")),
        order_by=(Milestone.position, Milestone.title),
        limit=PER_KIND_LIMIT,
    ):
        hits.append(
            Hit(
                kind="milestone",
                title=milestone.title,
                detail=milestone.owner_label or "",
                location="",
                tab=TAB_SCHEDULE,
            )
        )

    hits.extend(_chunk_hits(session, ctx, term))
    return hits[:TOTAL_LIMIT]


def _chunk_hits(session: Session, ctx: TenantContext, term: str) -> list[Hit]:
    """Os trechos de documento que casam com o termo, com a página de onde saem.

    O rótulo de posição é o mesmo ``location`` que a citação do chat mostra, e
    pela mesma razão ele é verdade: o chunking nunca cruza fronteira de página
    (ADR 0014).
    """
    vector = text_vector(DocumentChunk.text)
    query = func.websearch_to_tsquery(REGCONFIG, term)
    matches = DocumentChunkRepository(session, ctx).matching(
        vector.op("@@")(query),
        order_by=(func.ts_rank(vector, query).desc(), DocumentChunk.ordinal),
        limit=PER_KIND_LIMIT,
    )
    if not matches:
        return []

    documents = DocumentRepository(session, ctx)
    hits: list[Hit] = []
    for chunk in matches:
        document = documents.get(chunk.document_id)
        # Segunda barreira, como em `document_download`: o repositório já filtrou
        # pelo tenant, e a varredura é um portão separado do isolamento.
        if document is None or document.scan_state not in (
            ScanState.clean,
            ScanState.skipped,
        ):
            continue
        hits.append(
            Hit(
                kind="chunk",
                title=document.title,
                detail=_excerpt(chunk.text, term),
                location=chunk.location,
                tab=TAB_DOCUMENTS,
                document_id=str(document.id) if document.storage_key else "",
            )
        )
    return hits


#: Quanto do trecho volta para a tela. Não é o trecho inteiro: um chunk tem
#: ~1.000 caracteres e a lista viraria uma parede de texto.
EXCERPT_RADIUS = 90


def _excerpt(text: str, term: str) -> str:
    """A vizinhança do casamento, para a pessoa reconhecer o que achou.

    Recortado em Python e não por ``ts_headline`` porque o casamento aqui é sobre
    o texto **dobrado** e o recorte é sobre o original: as duas cadeias têm o
    mesmo comprimento (``translate`` é caractere a caractere), então o índice de
    uma vale na outra — e é o original que vai para a tela, com acento.
    """
    flat = " ".join(text.split())
    position = fold(flat).find(term.split()[0] if term.split() else term)
    if position < 0:
        return flat[: EXCERPT_RADIUS * 2] + ("…" if len(flat) > EXCERPT_RADIUS * 2 else "")

    start = max(0, position - EXCERPT_RADIUS)
    end = min(len(flat), position + EXCERPT_RADIUS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(flat) else ""
    return f"{prefix}{flat[start:end].strip()}{suffix}"
