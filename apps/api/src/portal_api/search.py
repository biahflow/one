"""A busca do projeto — o único lugar onde um termo digitado vira linhas (ADR 0024).

Mesma forma de :mod:`portal_api.notifications`, :mod:`portal_api.conversations` e
:mod:`portal_api.retention`: a operação nasce em cinco repositórios diferentes, e
espalhar a projeção faria "o que a busca alcança" deixar de caber num arquivo —
que é justamente a pergunta que alguém faz ao revisar isolamento.

Duas fontes, um resultado, e as duas passam pelo mesmo par de barreiras: o filtro
do ``TenantScopedRepository`` primeiro, a RLS depois. As **linhas** do read model
(documento, reunião, pendência, marco, e desde a ADR 0087 as quatro listas do
Discovery) casam por título e descrição; os **trechos** de documento casam por
full-text, e é o que faz "buscar no contexto do projeto" — a frase que a tela já
dizia — valer para o conteúdo do contrato e não só para o nome dele.

Três regras governam o que sai daqui:

1. **Só entra o que o cliente já alcança por alguma aba.** Um hit que levasse a
   lugar nenhum é a mesma classe de defeito que a ADR 0017 corrigiu ao
   transformar a citação em link. Esta regra teve uma exceção nomeada por três
   fases: ``Decision`` tinha modelo desde a Fase 1, não era projetada em
   ``build_dashboard``, e a linha de cima dizia *"quando existir aba de decisões,
   entra aqui junto"*. A ADR 0049 fechou isso — a aba existe, e a decisão entra
   aqui pelo título **e pelo racional**, que é o campo pelo qual alguém
   efetivamente a procura.
2. **O trecho só existe se o documento passou pela varredura.** Hoje um
   documento não varrido não chega a ter chunk — o ``ingest_document`` recusa —,
   e a asserção fica escrita mesmo assim, porque "não tem como acontecer" é como
   o portal descobriria que passou a ter (ver ``document_download`` em
   ``main.py``, que faz o mesmo pelo mesmo motivo).
3. **A busca não erra, ela não acha.** Termo curto demais, termo só de espaços
   ou termo sem casamento devolvem lista vazia — nunca 422, nunca "o resultado
   mais próximo". Um resultado por aproximação é o análogo, aqui, do trecho menos
   distante que o corte de :mod:`portal_api.ai.retrieval` recusa citar.
4. **Nenhuma espécie que casou é zerada por causa de outra** (ADR 0087). O teto
   geral é distribuído em rodízio entre as espécies, e não aplicado à ordem de
   inserção: com nove espécies a cinco, são 45 candidatos para 20 vagas, e um
   corte por ordem faria os **trechos** — que entram por último e são o que a
   ADR 0024 §4 diz fazer a promessa valer — sumirem em silêncio num projeto com
   vinte linhas de read model casando.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import ColumnElement, func, or_
from sqlalchemy.orm import Session

from portal_api import anchors
from portal_api.tabs import (
    TAB_DISCOVERY,
    TAB_DOCUMENTS,
    TAB_DECISIONS,
    TAB_MEETINGS,
    TAB_PENDINGS,
    TAB_SCHEDULE,
)
from portal_api.models import (
    Decision,
    Document,
    DocumentChunk,
    EpistemicStatus,
    Finding,
    ImprovementOpportunity,
    Meeting,
    Milestone,
    PainPoint,
    PendingItem,
    Process,
    ProcessStep,
    SolutionHypothesis,
)
from portal_api.repositories import (
    DecisionRepository,
    DocumentChunkRepository,
    DocumentRepository,
    FindingRepository,
    ImprovementOpportunityRepository,
    MeetingRepository,
    MilestoneRepository,
    PainPointRepository,
    PendingItemRepository,
    ProcessRepository,
    ProcessStepRepository,
    SolutionHypothesisRepository,
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


#: Qual **linha** da aba cada espécie de resultado aponta (ADR 0057).
#:
#: Irmão do ``ITEM_ANCHOR`` de :mod:`portal_api.notifications`, e a divisão entre
#: os dois é a mesma que o ``LINK_TAB`` já fazia: o ``tab`` acima responde "que
#: tela?", este responde "qual linha daquela tela?". A diferença com o aviso é que
#: aqui a resposta **inteira** cabe numa tabela, e por um motivo verificável: no
#: aviso o rótulo é do evento (só quem comparou os dois estados sabe qual marco
#: ficou pronto), e aqui ``Hit.title`` **é** o rótulo nas seis espécies — daí a
#: âncora ser derivada em :meth:`Hit.anchor` em vez de escrita em cada construção.
#:
#: **Explícito por espécie, nunca derivado do ``kind``.** Derivar parece a saída
#: óbvia e produziria duas âncoras erradas: ``chunk`` viraria um namespace que não
#: existe em lado nenhum, e ``decision`` ganharia um que a ADR 0056 recusou de
#: propósito (a aba de Decisões não desenha ``data-item``).
#:
#: ``chunk`` recebe ``document``, e é a aplicação literal do *"a âncora é do
#: objeto, não do fato"* da ADR 0056: o trecho é do documento, e a linha que a aba
#: de Documentos desenha é a do documento — como ``transcript_ready`` e
#: ``meeting_scheduled`` compartilham ``meeting``.
#:
#: **Sem teto de tamanho, ao contrário do ``deep_link``.** O ``_MAX_LINK`` é
#: orçamento da *mensagem do canal*; aqui o valor viaja em JSON para uma tela que
#: já recebeu o título inteiro. Logo não há queda a registrar — **nenhum evento
#: novo e nenhuma linha em ``docs/runbooks/alerts.md``**.
#:
#: **As quatro do Discovery ancoram por ``id``, e a bifurcação é decisão da ADR
#: 0087.** A ADR 0056 recusou o ``id`` por duas razões, e as duas são nulas aqui: o
#: campo não existia nos esquemas de lista, e o uuid local é recriado a cada sync.
#: ``ProcessOut.id``, ``FindingOut.id``, ``PainPointOut.id`` e
#: ``ImprovementOpportunityOut.id`` **são publicados**, e o que sai neles é o id da
#: origem, nunca o uuid local (ver ``_discovery_projection``). O critério que a ADR
#: 0056 aplicou — *"publica-se na URL o que a tela já usa como identidade"* — aponta
#: para o id aqui, porque as chaves de lista dos quatro blocos **já são** ``item.id``.
#: E ancorar por texto esbarraria no ``Finding``, que não tem título: tem
#: ``statement``, que é uma frase e pode ser um parágrafo.
HIT_ANCHOR: dict[str, str] = {
    "document": anchors.ANCHOR_DOCUMENT,
    "meeting": anchors.ANCHOR_MEETING,
    "pending": anchors.ANCHOR_PENDING,
    "milestone": anchors.ANCHOR_MILESTONE,
    "chunk": anchors.ANCHOR_DOCUMENT,
    "process": anchors.ANCHOR_PROCESS,
    "finding": anchors.ANCHOR_FINDING,
    "pain_point": anchors.ANCHOR_PAIN_POINT,
    "improvement_opportunity": anchors.ANCHOR_IMPROVEMENT_OPPORTUNITY,
}

#: O estado epistêmico de um achado, na palavra que o cliente lê (Language Map §4).
#:
#: **Sai da API porque é a API que sabe** (ADR 0087). A regra 1 da §3 do mapa é que
#: um ``hypothesis`` aparece **rotulado** como hipótese ou não aparece — nunca como
#: fato —, e um resultado de busca com o ``statement`` cru é uma afirmação sem
#: rótulo: leitura de fato por omissão, que é o defeito exato que a ADR 0086 existe
#: para impedir, reaparecendo por uma porta que ela não olhou. O rótulo viaja pronto
#: no ``detail`` pelo argumento do ``tab`` acima: um segundo mapa do lado do
#: navegador envelheceria sozinho.
#:
#: O preço é o modo de falha do ``textfold.py``: os três literais são os **mesmos**
#: do ``EPISTEMIC_LABEL`` de ``app/DashboardClient.tsx`` e têm de continuar sendo,
#: senão a mesma hipótese sai "Hipótese" na aba e outra coisa na busca. Quem cobra é
#: ``test_ready_made_labels.py``, que lê o mapa do TSX e o compara com este — e cobra
#: também que os três membros do enum estejam aqui, porque um ``.get(..., "")`` faria
#: o esquecimento **apagar o rótulo** em vez de reprovar.
#:
#: Mora aqui, e não num módulo folha, pela razão de o ``anchors.py`` ter nascido
#: dentro do ``notifications.py``: hoje há um produtor só deste rótulo em Python.
#: No dia em que houver um segundo, ele muda de casa sem mudar de valor.
EPISTEMIC_LABEL: dict[EpistemicStatus, str] = {
    EpistemicStatus.fact: "Fato",
    EpistemicStatus.hypothesis: "Hipótese",
    EpistemicStatus.unknown: "Pergunta em aberto",
}

#: O estado de uma reunião, na palavra que o cliente lê.
#:
#: **Defeito anterior, achado por esta fatia e fechado nela** (ADR 0087). A busca
#: mandava ``detail=meeting.status`` — ``held``/``scheduled``, o código cru da origem
#: — enquanto a aba Reuniões desenha *"Realizada"* e *"Agendada"*, traduzidos pelo
#: BFF em ``app/page.tsx``. **O mesmo valor com dois nomes**, conforme a porta por
#: onde o cliente chega, e nada ficava vermelho: é a ADR 0033 numa direção que
#: ninguém tinha olhado — não um painel sobre campo sem escritor, e sim dois
#: escritores discordando sobre a mesma palavra.
#:
#: Fechado **aqui** porque a fatia construiu o mecanismo exato de que ele precisava:
#: rótulo pronto saindo da API, e guarda comparando os dois deployables.
#:
#: **A indexação é indireta, ao contrário do ``EPISTEMIC_LABEL``, e a assimetria é
#: consciente.** Lá o domínio é um ``enum`` de três membros (§4 do Language Map), e
#: um membro sem rótulo reprova numa guarda de completude — daí indexar direto, com
#: o argumento de que um ``.get(..., "")`` **apagaria** o rótulo. Aqui não há o que
#: enumerar, e é decisão escrita no próprio modelo: ``Meeting.status`` é ``String``
#: *"para que uma nova opção lá não exija migração de enum aqui"*. Sem domínio
#: fechado não há guarda de completude possível, então a queda é para o **código
#: cru** — exatamente o que o ``?? meeting.status`` do BFF já faz, porque duas portas
#: caindo de formas diferentes recriaria o defeito que esta tabela conserta.
MEETING_STATUS_LABEL: dict[str, str] = {
    "scheduled": "Agendada",
    "held": "Realizada",
}

#: Quem legitimamente **não** aponta para uma linha, com o motivo escrito.
#:
#: Na forma do ``ANCHORLESS`` do aviso, do ``NOT_AN_ALERT`` de
#: ``test_telemetry.py`` e do ``NOT_CONSUMED`` de ``tests/api-contract.test.mjs``:
#: a isenção existe, e ela é uma frase que alguém assinou.
#: ``test_item_anchor.py`` cobra as duas direções, e proíbe uma espécie de estar
#: nas duas tabelas — estando, a isenção passaria a cobrir quem não precisa dela.
ANCHORLESS_HITS: dict[str, str] = {
    "decision": (
        "a aba de Decisões **não** desenha `data-item`, e isso é decisão da ADR "
        "0056: namespace que só existe de um lado é atributo construído antes do "
        "escritor, o defeito da ADR 0033 escrito ao contrário. O clique leva à "
        "aba, que é a resolução que a ADR 0024 estabeleceu e continua correta — a "
        "decisão é lida inteira ali, não é uma linha de lista que se procura"
    ),
}


@dataclass(frozen=True)
class Hit:
    """Uma linha do resultado, já no formato que a tela mostra.

    ``document_id`` só vem preenchido quando há arquivo por trás — é o que
    permite ao trecho abrir a fonte pela rota de download assinado que já existe
    (ADR 0017), em vez de pedir que o cliente confie no rótulo.

    ``anchor_id`` só vem preenchido nas quatro espécies do Discovery, e é o ``id``
    da origem que a tela usa como chave de lista (ADR 0087). Vazio quer dizer "a
    identidade desta linha é o próprio ``title``", que é como as outras cinco
    espécies sempre foram — e **não** "invente uma", pela convenção do
    ``document_id`` ao lado.
    """

    kind: str
    title: str
    detail: str
    location: str
    tab: str
    document_id: str = ""
    anchor_id: str = ""

    @property
    def anchor(self) -> str:
        """A linha da aba que este resultado aponta, no formato do ``?item=``.

        Vazio é uma resposta legítima e quer dizer "não há o que ancorar" — nunca
        "ancore por sua conta", que é a mesma convenção do ``document_id`` ao
        lado. Quem cai nela está declarado em :data:`ANCHORLESS_HITS`.

        **Derivada, e aqui isso é correto** — ao contrário do ``Change.item``, que
        é escrito em cada construção. Lá o rótulo é do evento e não há tabela
        possível; aqui ``title`` **é** o rótulo nas cinco espécies do read model do
        projeto, então não há como esquecê-la numa construção nova: uma espécie sem
        linha no ``HIT_ANCHOR`` reprova em ``test_item_anchor.py`` em vez de sair
        vazia.

        **A metade da direita bifurca, e a da esquerda não** (ADR 0087): quando o
        ``anchor_id`` vem preenchido, é ele que vai depois do ``:``. O argumento
        está no docstring de :data:`HIT_ANCHOR`, e o que ele **não** faz é trocar a
        forma das outras cinco — ali o rótulo continua sendo o ``title``, que é o
        que a tela desenha como ``data-item``.
        """
        namespace = HIT_ANCHOR.get(self.kind)
        if not namespace:
            return ""
        return f"{namespace}:{self.anchor_id or self.title}"

    def to_payload(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "location": self.location,
            "tab": self.tab,
            "document_id": self.document_id,
            "item_anchor": self.anchor,
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


def _meeting_label(status: str | None) -> str:
    """O estado da reunião como a aba o escreve, e não como a origem o codifica.

    As três respostas são as **mesmas** do BFF, e é isso que a função existe para
    garantir: sem estado, vazio; estado conhecido, a palavra; estado que a tabela
    não conhece, o **código cru** — nunca vazio, porque sumir com o valor esconderia
    do cliente que a origem passou a dizer algo novo. Ver :data:`MEETING_STATUS_LABEL`
    para por que a queda aqui não é a mesma do rótulo epistêmico.
    """
    if not status:
        return ""
    return MEETING_STATUS_LABEL.get(status, status)


def search_project(session: Session, ctx: TenantContext, query: str) -> list[Hit]:
    """Os resultados da busca dentro de ``ctx``, prontos para a tela.

    Determinístico e sem rede: o teste executa esta função direto, e a rota é uma
    casca em volta dela — a mesma divisão de ``results.compute_results``.
    """
    term = fold(query.strip())
    if len(term) < MIN_QUERY_LENGTH:
        return []

    pattern = _like_pattern(term)
    # Uma lista por espécie, e não uma lista só: o teto geral é distribuído entre
    # elas (ver :func:`_fit`), e para isso é preciso saber de quem é cada hit. A
    # ordem em que elas entram aqui é a ordem em que o resultado sai.
    document_hits: list[Hit] = []
    meeting_hits: list[Hit] = []
    decision_hits: list[Hit] = []
    pending_hits: list[Hit] = []
    milestone_hits: list[Hit] = []

    documents = DocumentRepository(session, ctx)
    for document in documents.matching(
        _matches(pattern, Document.title, func.coalesce(Document.author_label, "")),
        order_by=(Document.source_updated_at.desc().nulls_last(), Document.title),
        limit=PER_KIND_LIMIT,
    ):
        document_hits.append(
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
        meeting_hits.append(
            Hit(
                kind="meeting",
                title=meeting.title,
                detail=_meeting_label(meeting.status),
                location="",
                tab=TAB_MEETINGS,
            )
        )

    # Decisões. É a linha que a regra 1 deste módulo prometia: elas ficavam de fora
    # porque nenhuma aba as mostrava, e o docstring dizia "quando existir aba de
    # decisões, entra aqui junto". A aba existe agora.
    #
    # `rationale` entra no casamento, e é o campo que faz a busca valer a pena aqui:
    # quem procura decisão raramente lembra o título dela — lembra do assunto que a
    # motivou, que é o que está no porquê.
    decisions = DecisionRepository(session, ctx)
    for decision in decisions.matching(
        _matches(pattern, Decision.title, func.coalesce(Decision.rationale, "")),
        order_by=(Decision.decided_on.desc().nulls_last(), Decision.title),
        limit=PER_KIND_LIMIT,
    ):
        decision_hits.append(
            Hit(
                kind="decision",
                title=decision.title,
                detail=decision.owner_label or "",
                location="",
                tab=TAB_DECISIONS,
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
        pending_hits.append(
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
        milestone_hits.append(
            Hit(
                kind="milestone",
                title=milestone.title,
                detail=milestone.owner_label or "",
                location="",
                tab=TAB_SCHEDULE,
            )
        )

    return _fit(
        [
            document_hits,
            meeting_hits,
            decision_hits,
            pending_hits,
            milestone_hits,
            _process_hits(session, ctx, pattern),
            _finding_hits(session, ctx, pattern),
            _pain_point_hits(session, ctx, pattern),
            _improvement_opportunity_hits(session, ctx, pattern),
            _chunk_hits(session, ctx, term),
        ]
    )


def _fit(groups: list[list[Hit]], limit: int = TOTAL_LIMIT) -> list[Hit]:
    """As ``limit`` vagas distribuídas entre as espécies, em rodízio (ADR 0087).

    Pura e sem sessão de propósito: o defeito que ela conserta é aritmético — nove
    espécies a cinco são 45 candidatos para 20 vagas —, e um teste que precisasse de
    Postgres para exercitá-lo seria um teste que não roda na máquina de quem não
    subiu o banco.

    O corte anterior era ``hits[:TOTAL_LIMIT]`` **em ordem de inserção**, e os
    trechos entram por último: vinte linhas de read model casando derrubavam os
    trechos inteiros, e eles são o que a ADR 0024 §4 diz fazer a promessa da busca
    valer. Já era assim com cinco espécies (25 candidatos); com nove o silêncio dos
    trechos viraria o caso comum.

    **Rodízio e não fatia igual**, porque fatia igual desperdiça: com duas vagas por
    espécie, uma espécie com um hit só devolveria a vaga a ninguém. Cada rodada dá
    uma vaga a cada espécie que ainda tem candidato, e a sobra volta para quem tem.

    **A saída continua agrupada por espécie**, e não intercalada: o rodízio decide
    *quantos* de cada um entram, não em que ordem eles saem. Intercalar mudaria a
    lista que a tela já desenha por um ganho que ninguém pediu.
    """
    quota = [0] * len(groups)
    taken = 0
    while taken < limit:
        served = False
        for index, group in enumerate(groups):
            if taken >= limit:
                break
            if quota[index] < len(group):
                quota[index] += 1
                taken += 1
                served = True
        if not served:
            break
    return [hit for index, group in enumerate(groups) for hit in group[: quota[index]]]


#: As sete colunas de texto de uma etapa: o nome mais as seis chaves do formulário
#: P-S-D-T-E-R. Os seis nomes em português são decisão do contrato do produtor (ver
#: :class:`portal_api.models.discovery.ProcessStep`), e entram na busca porque é
#: exatamente o que a aba desenha na tabela — "quem faz", "em que sistema", "que
#: erro acontece" é onde mora a frase que alguém procura.
_STEP_COLUMNS = (
    ProcessStep.name,
    ProcessStep.pessoas,
    ProcessStep.sistema,
    ProcessStep.dados,
    ProcessStep.tempo,
    ProcessStep.erro,
    ProcessStep.retrabalho,
)

#: As três de uma hipótese de solução. Mesma razão: a aba as desenha debaixo da
#: oportunidade, e quem procura "fila de exceção" está procurando a intervenção.
_HYPOTHESIS_COLUMNS = (
    SolutionHypothesis.statement,
    SolutionHypothesis.intervention,
    SolutionHypothesis.expected_effect,
)


def _optional(*columns: ColumnElement) -> tuple[ColumnElement[str], ...]:
    """As colunas já com ``coalesce``, para uma anulável não fazer o ``LIKE`` virar NULL.

    Aplicado ao grupo inteiro e não só às anuláveis de propósito: a lista das sete
    colunas da etapa é o formulário P-S-D-T-E-R, e escolher coluna a coluna faria a
    lista deixar de ser lida como uma coisa só — pelo custo de um ``coalesce`` inócuo
    sobre a que não aceita nulo.
    """
    return tuple(func.coalesce(column, "") for column in columns)


def _process_hits(
    session: Session, ctx: TenantContext, pattern: str
) -> list[Hit]:
    """Os processos que casam — pelo próprio nome ou por uma etapa deles.

    **Casa no filho, o hit é do pai**, que é o *"a âncora é do objeto, não do fato"*
    da ADR 0056 e o precedente literal do ``chunk``→``document`` ao lado: a linha que
    a aba desenha é a do processo, e a etapa é uma linha da tabela dentro dele.

    Um processo cujo nome **e** cujas etapas casam produz **um** hit, e o nome ganha:
    ali o ``detail`` fica vazio porque não há etapa a nomear. Vindo do filho, o
    ``detail`` é o nome da etapa — sem ele o cliente veria um processo na lista sem
    ter como saber por que ele apareceu.
    """
    processes = ProcessRepository(session, ctx)
    found: dict[int, Hit] = {}
    for process in processes.matching(
        _matches(pattern, Process.name),
        order_by=(Process.external_id,),
        limit=PER_KIND_LIMIT,
    ):
        found[process.external_id] = _process_hit(process, detail="")

    for step in ProcessStepRepository(session, ctx).matching(
        _matches(pattern, *_optional(*_STEP_COLUMNS)),
        order_by=(ProcessStep.external_id,),
        limit=PER_KIND_LIMIT,
    ):
        # Segunda leitura pelo repositório, como em `_chunk_hits`: o filtro de tenant
        # do pai vale de novo, e não se deduz do filho.
        parent = processes.get(step.process_id)
        if parent is None or parent.external_id in found:
            continue
        found[parent.external_id] = _process_hit(parent, detail=step.name)

    return [found[key] for key in sorted(found)][:PER_KIND_LIMIT]


def _process_hit(process: Process, *, detail: str) -> Hit:
    return Hit(
        kind="process",
        title=process.name,
        detail=detail,
        location="",
        tab=TAB_DISCOVERY,
        anchor_id=str(process.external_id),
    )


def _finding_hits(
    session: Session, ctx: TenantContext, pattern: str
) -> list[Hit]:
    """Os achados que casam, **sempre com o estado epistêmico no ``detail``**.

    Hipótese e lacuna entram na busca, e é decisão (ADR 0087): excluí-las faria a
    busca ser uma segunda régua sobre o mesmo dado que a aba já mostra rotulado — e
    a regra 1 da §3 do Language Map pede o rótulo, não a omissão. O que não pode
    existir é o achado **sem** rótulo, que é a leitura de fato por omissão.

    ``Evidence`` fica de fora do casamento, e não por esquecimento: ela é JSONB
    dentro do ``Finding`` e não coluna, e o que ela carrega é ponteiro para a fonte —
    ``raw_excerpt`` e ``content_hash`` são barrados por lista branca na ingestão (ADR
    0086). Buscar dentro do blob acrescentaria uma superfície onde o guard de
    visibilidade não enxerga.
    """
    return [
        Hit(
            kind="finding",
            title=finding.statement,
            detail=EPISTEMIC_LABEL[finding.epistemic_status],
            location="",
            tab=TAB_DISCOVERY,
            anchor_id=str(finding.external_id),
        )
        for finding in FindingRepository(session, ctx).matching(
            _matches(pattern, Finding.statement),
            order_by=(Finding.external_id,),
            limit=PER_KIND_LIMIT,
        )
    ]


def _pain_point_hits(
    session: Session, ctx: TenantContext, pattern: str
) -> list[Hit]:
    """As dores confirmadas que casam, pelo título e pela descrição.

    **O ``detail`` fica vazio, e é decisão medida** (ADR 0087). Os dois candidatos
    óbvios não servem, e pelo mesmo argumento por dois caminhos:

    - o ``impact_estimate`` vem sem unidade declarada e o ``impact_type`` diz coisas
      que não são dinheiro, então formatá-lo aqui repetiria o número **sem** a frase
      que a aba escreve em volta dele (ADR 0086);
    - o ``status`` é o código cru da origem (``confirmed``) e **a aba não o desenha**
      — o bloco de dor mostra título, impacto, descrição e os achados que a
      sustentam. Pô-lo aqui faria a busca mostrar *mais* do que a aba, que é a ADR
      0024 §5 ao contrário, e mostrá-lo em inglês numa tela cujo texto visível é
      PT-BR.

    Vazio é a resposta honesta: o título **é** o rótulo desta linha, e a tela só
    desenha o ``detail`` quando ele existe.
    """
    return [
        Hit(
            kind="pain_point",
            title=pain.title,
            detail="",
            location="",
            tab=TAB_DISCOVERY,
            anchor_id=str(pain.external_id),
        )
        for pain in PainPointRepository(session, ctx).matching(
            _matches(pattern, PainPoint.title, *_optional(PainPoint.description)),
            order_by=(PainPoint.external_id,),
            limit=PER_KIND_LIMIT,
        )
    ]


def _improvement_opportunity_hits(
    session: Session, ctx: TenantContext, pattern: str
) -> list[Hit]:
    """O backlog de melhoria que casa — pela oportunidade ou por uma hipótese dela.

    Mesma forma e mesma razão de :func:`_process_hits`: a hipótese de solução vem
    **aninhada** no pai e é ele que a aba desenha como linha.

    **O ``detail`` fica vazio**, pelo argumento escrito em :func:`_pain_point_hits`
    e por um segundo que é só daqui: a hipótese que casou é uma frase inteira, e
    nomeá-la trocaria o rótulo curto por um parágrafo na lista de resultados — ao
    contrário do processo, onde o que casa no filho tem **nome** e cabe.
    """
    opportunities = ImprovementOpportunityRepository(session, ctx)
    found: dict[int, Hit] = {}
    for opportunity in opportunities.matching(
        _matches(
            pattern,
            ImprovementOpportunity.title,
            *_optional(
                ImprovementOpportunity.desired_change,
                ImprovementOpportunity.impact_hypothesis,
            ),
        ),
        order_by=(ImprovementOpportunity.external_id,),
        limit=PER_KIND_LIMIT,
    ):
        found[opportunity.external_id] = _improvement_opportunity_hit(opportunity)

    for hypothesis in SolutionHypothesisRepository(session, ctx).matching(
        _matches(pattern, *_optional(*_HYPOTHESIS_COLUMNS)),
        order_by=(SolutionHypothesis.external_id,),
        limit=PER_KIND_LIMIT,
    ):
        parent = opportunities.get(hypothesis.improvement_opportunity_id)
        if parent is None or parent.external_id in found:
            continue
        found[parent.external_id] = _improvement_opportunity_hit(parent)

    return [found[key] for key in sorted(found)][:PER_KIND_LIMIT]


def _improvement_opportunity_hit(opportunity: ImprovementOpportunity) -> Hit:
    return Hit(
        kind="improvement_opportunity",
        title=opportunity.title,
        detail="",
        location="",
        tab=TAB_DISCOVERY,
        anchor_id=str(opportunity.external_id),
    )


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
