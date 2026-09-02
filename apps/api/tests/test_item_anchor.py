"""A âncora é alcançável na tela que a leva (FDD 021, ADR 0056; busca na ADR 0057).

Arquivo próprio e **não** extensão do ``test_tabs.py``: aquele tem docstring
específico sobre o rótulo da aba ser identificador em dois deployables, e a varredura
de AST daqui o soterraria. O custo é umas quatro linhas de regex duplicadas para ler
o TSX, e vale.

O modo de falha que estas guardas existem para pegar é silencioso do começo ao fim:
o cliente recebe a mensagem, clica, chega na aba certa — e **nada acontece**. Não há
erro, não há log, não há teste vermelho. É a mesma classe da ADR 0033 (painel sobre
campo sem escritor) e da ADR 0043 (controle sobre campo sem escritor), agora entre o
Python que compõe a URL e o TSX que teria de reconhecê-la.

**As duas superfícies internas entraram na ADR 0057, e as guardas são as mesmas.**
O aviso e a busca respondem a mesma pergunta — "qual linha desta aba?" — e a
única diferença é onde o rótulo nasce. Um arquivo só, e não dois: o par que
importa é ``âncora publicada`` × ``data-item desenhado``, e duas guardas sobre a
mesma igualdade divergiriam pelo motivo de ``tabs.py`` existir.
"""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path

from portal_api import anchors, notifications, search, tabs
from portal_api.models import NotificationKind

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_ROOT = _REPO_ROOT / "apps" / "api" / "src" / "portal_api"
_DASHBOARD = _REPO_ROOT / "app" / "DashboardClient.tsx"

#: `data-item={`milestone:${item.title}`}` — o que interessa é o prefixo.
#:
#: ``[a-z_]+`` e não ``[a-z]+`` desde a ADR 0087: os espaços de nomes são
#: identificadores de código e dois deles são ``snake_case`` (``pain_point``,
#: ``improvement_opportunity``). Com o casador antigo o ``_`` fazia a expressão
#: **não casar de todo** — o namespace sumia do conjunto do TSX e a guarda de
#: igualdade acusaria "só no Python" um atributo que está escrito ali.
_DATA_ITEM = re.compile(r"data-item=\{`([a-z_]+):")
#: Início de uma função de topo do componente, que é a unidade de recorte do TSX.
_FUNCTION = re.compile(r"^(?:export default )?function (\w+)\s*\(", re.MULTILINE)
#: `case "Cronograma":` … `return <ScheduleView`, dentro do `switch (activeNav)`.
_CASE = re.compile(r'case "([^"]+)":\s*return\s*<(\w+)', re.DOTALL)
_DEFAULT_CASE = re.compile(r"default:\s*return\s*\(?\s*<(\w+)", re.DOTALL)
#: Um componente filho usado em JSX. Só os que começam com maiúscula são componentes.
_CHILD = re.compile(r"<([A-Z]\w+)")


def _dashboard() -> str:
    return _DASHBOARD.read_text(encoding="utf-8")


def _blocks() -> dict[str, str]:
    """Cada função de topo do ``DashboardClient.tsx``, do nome ao corpo.

    Recorte por texto e não por parser de TypeScript: o repositório não tem um, e
    trazer um para uma guarda seria pagar uma dependência para responder uma
    pergunta que quatro linhas de regex respondem. O limite está declarado no
    docstring de :func:`test_the_anchor_lands_on_the_tab_the_link_opens`.
    """
    source = _dashboard()
    starts = [(match.group(1), match.start()) for match in _FUNCTION.finditer(source)]
    blocks: dict[str, str] = {}
    for index, (name, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(source)
        blocks[name] = source[start:end]
    return blocks


def _balanced(source: str, at: int) -> str:
    """Do `{` em ``at`` até a chave que o fecha."""
    depth = 0
    for index in range(at, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[at : index + 1]
    raise AssertionError("chave sem fechamento em app/DashboardClient.tsx")


def _tab_components() -> dict[str, str]:
    """Rótulo de aba → componente que o ``switch (activeNav)`` renderiza."""
    source = _dashboard()
    at = source.find("switch (activeNav)")
    assert at != -1, "não achei o `switch (activeNav)` em app/DashboardClient.tsx"
    block = _balanced(source, source.index("{", at))

    mapping = {label: component for label, component in _CASE.findall(block)}
    fallback = _DEFAULT_CASE.search(block)
    assert fallback is not None, "o `switch (activeNav)` perdeu o `default:`"

    # A aba do `default:` é a que não tem `case` próprio — e é uma só, senão o
    # `switch` estaria mandando duas abas para a mesma tela sem dizer.
    uncased = [tab for tab in tabs.ALL if tab not in mapping]
    assert len(uncased) == 1, f"abas sem `case` e sem `default`: {uncased}"
    mapping[uncased[0]] = fallback.group(1)
    return mapping


def _change_calls() -> list[tuple[str, int, ast.Call]]:
    """Toda construção de ``Change`` do pacote, com onde ela está.

    Varredura de AST e não de fixture: as construções são **quatro origens**
    diferentes (o `diff` do sync, as duas tasks do worker e a rota de resposta do
    canal), e uma guarda dirigida por fixture só veria a que a fixture exercita.
    """
    calls: list[tuple[str, int, ast.Call]] = []
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name == "Change":
                calls.append((path.name, node.lineno, node))
    return calls


def _kind_of(call: ast.Call) -> str | None:
    """O membro de ``NotificationKind`` que este ``Change`` declara."""
    for keyword in call.keywords:
        if keyword.arg == "kind" and isinstance(keyword.value, ast.Attribute):
            return keyword.value.attr
    return None


def _has_item(call: ast.Call) -> bool:
    return any(keyword.arg == "item" for keyword in call.keywords)


def _hit_calls() -> list[tuple[str, int, str, str]]:
    """Toda construção de ``Hit`` do pacote: arquivo, linha, ``kind`` e aba.

    Por AST e não por fixture, pela razão de :func:`_change_calls`: uma guarda
    dirigida por fixture só vê a espécie que a fixture exercita, e foi esse ponto
    cego que deixou dez ramificações sem ``link`` até a ADR 0043. Aqui as
    construções são seis num arquivo só — mas "num arquivo só" é o estado de hoje,
    e é exatamente o tipo de premissa que a varredura dispensa.

    A aba chega como ``tab=TAB_MEETINGS``, que é um ``Name``: resolvê-lo contra
    :mod:`portal_api.tabs` é o que faz esta guarda comparar **rótulos**, e não
    nomes de constante que poderiam apontar para o valor errado.
    """
    calls: list[tuple[str, int, str, str]] = []
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id == "Hit"):
                continue
            kind = next(
                (
                    keyword.value.value
                    for keyword in node.keywords
                    if keyword.arg == "kind" and isinstance(keyword.value, ast.Constant)
                ),
                None,
            )
            assert isinstance(kind, str), (
                f"{path.name}:{node.lineno} constrói `Hit` sem `kind=` literal — a"
                " guarda não tem como saber que linha da tela ele aponta."
            )
            tab_node = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "tab"),
                None,
            )
            assert isinstance(tab_node, ast.Name), (
                f"{path.name}:{node.lineno} constrói `Hit` sem `tab=` legível."
            )
            calls.append((path.name, node.lineno, kind, getattr(tabs, tab_node.id)))
    return calls


def test_every_change_that_can_point_at_a_row_carries_the_anchor() -> None:
    """Toda construção de ``Change`` passa ``item=`` ou está declarada sem ele.

    Varre as quatro origens por AST, e não a fixture de um teste: a ADR 0043 nasceu
    de um campo que dez ramificações nunca preencheram, e o `diff` é só uma das
    quatro. As outras três são as duas tasks do worker e a resposta do canal.
    """
    offenders: list[str] = []
    for filename, line, call in _change_calls():
        kind = _kind_of(call)
        if kind is None:
            offenders.append(f"{filename}:{line} não declara `kind=` legível")
            continue
        if _has_item(call) or NotificationKind[kind] in notifications.ANCHORLESS:
            continue
        offenders.append(f"{filename}:{line} ({kind})")

    assert offenders == [], (
        "estes avisos não dizem qual linha da tela abrem: "
        + ", ".join(offenders)
        + ". Passe `item=<o rótulo que a tela mostra>` na construção, ou declare a"
        " espécie em `notifications.ANCHORLESS` com o motivo escrito — sem isso o"
        " link cai na aba e o critério (4) da FDD 021 degrada em silêncio."
    )


def test_the_anchorless_list_has_no_dead_entries() -> None:
    """A isenção vence, como a do ``advisories.json`` e a do ``NOT_AN_ALERT``.

    Uma espécie que ganhou âncora e continua listada aqui é allowlist que ninguém
    revisa — sedimento, na palavra da ADR 0033 —, e a próxima pessoa a ler a lista
    concluirá que a ausência de âncora ali é decisão em vigor.
    """
    anchorless_in_code = {
        NotificationKind[kind]
        for _, _, call in _change_calls()
        if (kind := _kind_of(call)) is not None and not _has_item(call)
    }
    stale = sorted(
        kind.value for kind in notifications.ANCHORLESS if kind not in anchorless_in_code
    )

    assert stale == [], (
        "estas espécies estão em `ANCHORLESS` e nenhuma construção as deixa sem"
        f" âncora: {', '.join(stale)}. Tire a linha."
    )


def test_every_anchored_kind_is_rendered_by_the_screen() -> None:
    """Todo espaço de nomes que o Python publica é um que a tela reconhece.

    Irmã do ``test_the_python_labels_are_exactly_the_navigation_ones``, e contra o
    mesmo modo de falha: lá um rótulo de aba trocado de um lado só, aqui um espaço
    de nomes que só existe de um lado. O cliente clica no aviso, chega na aba certa
    e **nada acontece** — sem erro em lugar nenhum.

    A igualdade é nos dois sentidos de propósito. Namespace só no Python é a âncora
    que nunca casa; namespace só no TSX é atributo construído antes do escritor, que
    é o defeito da ADR 0033 — e por isso Resultados e Decisões não têm ``data-item``.

    **Virou união na ADR 0057, e nunca subconjunto — o buraco foi medido.** Com a
    versão anterior, que olhava só o ``ITEM_ANCHOR``, a mutação
    ``HIT_ANCHOR["milestone"] = "marco"`` passa **verde**: o conjunto do aviso
    continua idêntico ao do TSX, e a busca publica em silêncio um namespace que a
    tela não desenha — o cliente clica no resultado, chega na aba certa e nada
    acontece. Aceitar subconjunto ("a busca só pode usar o que o aviso já usa")
    seria a mesma frouxidão da ADR 0035, onde ``POST /chat`` aparecia coberto por
    um 404 que era de outra rota.
    """
    published = set(notifications.ITEM_ANCHOR.values()) | set(search.HIT_ANCHOR.values())
    rendered = set(_DATA_ITEM.findall(_dashboard()))

    assert published == rendered, (
        "os espaços de nomes da âncora divergem entre os dois deployables. "
        f"só no Python: {sorted(published - rendered)}; "
        f"só no TSX: {sorted(rendered - published)}. "
        "Acrescente o `data-item={`<ns>:${…}`}` na lista correspondente de "
        "`app/DashboardClient.tsx`, ou tire a linha de `notifications.ITEM_ANCHOR`"
        " / `search.HIT_ANCHOR`."
    )
    # E o vocabulário declarado é o vocabulário em uso. `anchors.ALL` é o que
    # alguém **escreveu**; a união acima é o que o código **faz**, e comparar as
    # duas é o que impede o módulo folha de virar sedimento — a mesma pergunta
    # que a guarda de allowlist obsoleta faz ao `NOT_CONSUMED`.
    assert published == set(anchors.ALL), (
        "`anchors.ALL` não é mais a lista dos espaços de nomes em uso. "
        f"declarado e não usado: {sorted(set(anchors.ALL) - published)}; "
        f"usado e não declarado: {sorted(published - set(anchors.ALL))}."
    )


def test_the_anchor_lands_on_the_tab_the_link_opens() -> None:
    """E o ``data-item`` está na aba que o ``LINK_TAB`` abre, não em outra qualquer.

    Existir não basta: um ``pending:`` renderizado só na Visão geral deixaria o link
    de ``pending_opened`` — que abre Pendências — apontando para uma linha que
    aquela aba não desenha. É o mesmo elo frouxo que a ADR 0035 mediu ao dar
    ``POST /chat`` como coberto por um 404 que era de outra rota.

    **A busca entrou na ADR 0057, e é o elo que só ela pega.** A mutação
    ``HIT_ANCHOR["meeting"] = ANCHOR_PENDING`` passa por todas as outras: a de
    espaços de nomes compara conjuntos e ``pending`` continua publicado; a de
    cobertura vê a espécie mapeada; a isenção não é tocada. Só aqui aparece que o
    resultado de reunião abriria a aba "Reuniões" apontando para uma linha que
    quem desenha é a aba de Pendências. É o mesmo achado da ADR 0034, onde o
    evento sem limiar era irmão exato de um que já tinha.

    **Limite declarado**, como o corpus de ``tests/api-contract.test.mjs`` declara o
    dele: o recorte do TSX é por função de topo, e a expansão de componente filho é
    de **um nível** — o bastante para o ``JourneyPanel``, que quem renderiza é o
    ``OverviewView``. Um terceiro nível passaria despercebido por esta guarda.
    """
    blocks = _blocks()
    tab_component = _tab_components()

    where: dict[str, set[str]] = {}
    for name, body in blocks.items():
        for namespace in _DATA_ITEM.findall(body):
            where.setdefault(namespace, set()).add(name)

    # As duas superfícies, no mesmo laço: o par que interessa é (namespace, aba),
    # e de onde ele veio só muda a etiqueta da mensagem de erro. O aviso sabe a
    # aba pelo `LINK_TAB`; a busca a carrega na própria construção do `Hit`.
    anchored: list[tuple[str, str, str]] = [
        (f"aviso {kind.value}", namespace, notifications.LINK_TAB[kind])
        for kind, namespace in notifications.ITEM_ANCHOR.items()
    ] + [
        (f"busca {kind}", search.HIT_ANCHOR[kind], tab)
        for _, _, kind, tab in _hit_calls()
        if kind in search.HIT_ANCHOR
    ]

    misplaced: list[str] = []
    for origin, namespace, tab in anchored:
        component = tab_component[tab]
        reachable = {component} | {
            child for child in _CHILD.findall(blocks.get(component, "")) if child in blocks
        }
        if not (where.get(namespace, set()) & reachable):
            misplaced.append(
                f"{origin}: `{namespace}:` abriria a aba {tab!r} ({component}), "
                f"e o `data-item` está em {sorted(where.get(namespace, set())) or 'lugar nenhum'}"
            )

    assert misplaced == [], (
        "estas espécies levam o cliente a uma aba que não desenha a linha ancorada: "
        + "; ".join(misplaced)
        + ". Ponha o `data-item` no componente daquela aba (ou num filho direto dele)."
    )


def test_the_longest_possible_link_still_fits_the_channel() -> None:
    """Estourou o teto, a âncora **cai** — nunca é truncada.

    Os títulos são ``String(200)``, e duzentos caracteres acentuados
    percent-encoded passam de mil: o caso não é hipotético. Truncar produziria uma
    âncora que não casa com nada *parecendo* que casou, e a decisão de dropar é o
    que torna a degradação monotônica — sem âncora, o link é o de hoje.
    """
    project_id = uuid.uuid4()
    huge = "ção" * 67  # 201 caracteres, todos com acento em dois deles

    link = notifications.deep_link(project_id, NotificationKind.milestone_done, huge)

    assert link == f"/?project={project_id}&tab=Cronograma"
    assert "item=" not in link


def test_a_kind_without_anchor_still_produces_the_tab_link() -> None:
    """O piso da fatia: sem âncora, o link é exatamente o de antes dela."""
    project_id = uuid.uuid4()

    assert notifications.deep_link(
        project_id, NotificationKind.project_status_changed, "Automação Financeira"
    ) == f"/?project={project_id}&tab=Vis%C3%A3o%20geral"
    assert (
        notifications.deep_link(project_id, NotificationKind.milestone_done)
        == f"/?project={project_id}&tab=Cronograma"
    )
    # E a espécie sem aba continua sem link nenhum.
    assert notifications.deep_link(project_id, NotificationKind.onboarding_stuck) is None


def test_every_change_that_names_a_row_has_a_namespace_to_name_it_with() -> None:
    """Passar ``item=`` sem linha no ``ITEM_ANCHOR`` é âncora que não sai.

    O elo que faltava, e ele foi **medido**: tirando ``transcript_ready`` do
    ``ITEM_ANCHOR`` — espécie que compartilha o espaço de nomes ``meeting:`` com a
    ``meeting_scheduled`` — as outras cinco guardas ficam **todas verdes**. A de
    cima aceita a construção porque ela tem ``item=``; a de espaços de nomes
    compara conjuntos, e ``meeting`` continua publicado pela irmã; a de aba só
    percorre o que está no ``ITEM_ANCHOR``, e o que saiu dele não é percorrido.

    O resultado é o defeito exato que esta fatia existe para impedir, com o
    agravante de o autor **ter escrito** o rótulo: o `deep_link` descarta o `item`
    que recebeu, o link cai na aba, e nada fica vermelho. É o irmão do achado da
    ADR 0034, onde o evento sem limiar era irmão exato de um que já tinha.
    """
    orphans = sorted(
        {
            kind
            for _, _, call in _change_calls()
            if _has_item(call) and (kind := _kind_of(call)) is not None
            and NotificationKind[kind] not in notifications.ITEM_ANCHOR
        }
    )

    assert orphans == [], (
        "estas espécies passam `item=` e o `deep_link` o descarta, porque elas não"
        f" têm espaço de nomes: {', '.join(orphans)}. Acrescente a linha em"
        " `notifications.ITEM_ANCHOR` — sem ela o rótulo é escrito e jogado fora, e"
        " o link volta para a aba sem nada ficar vermelho."
    )


def test_no_kind_is_in_both_tables() -> None:
    """Uma espécie ou aponta para uma linha, ou está declarada sem apontar.

    Estar nas duas faz a guarda de cima aceitar uma construção sem ``item=`` para
    uma espécie que tem espaço de nomes — a isenção passaria a cobrir justamente
    quem não precisava dela.
    """
    both = sorted(
        kind.value for kind in notifications.ITEM_ANCHOR if kind in notifications.ANCHORLESS
    )

    assert both == [], f"espécies em `ITEM_ANCHOR` e `ANCHORLESS` ao mesmo tempo: {both}"


# --- a outra superfície: a busca (ADR 0057) ---------------------------------


def test_every_search_hit_knows_which_row_it_points_at() -> None:
    """Toda construção de ``Hit`` tem espaço de nomes, ou está declarada sem ele.

    O irmão exato de ``test_every_change_that_can_point_at_a_row_carries_a_anchor``
    para a outra superfície, e vale por si porque **a âncora da busca é derivada**:
    lá o rótulo é escrito em cada construção e a ausência aparece na construção;
    aqui :meth:`search.Hit.anchor` devolve ``""`` em silêncio para uma espécie
    fora do ``HIT_ANCHOR``, e a lista chega à tela com um clique que não destaca
    nada. Espécie nova é o caso que isto existe para pegar: ela nasce sem linha em
    nenhuma das duas tabelas.

    Tirar ``"pending"`` do ``HIT_ANCHOR`` reprova **aqui e só aqui**: a de espaços
    de nomes compara conjuntos, e ``pending`` continua publicado pelo
    ``ITEM_ANCHOR`` das três espécies de pendência. É o método da sétima asserção
    da ADR 0056, com a espécie escolhida pelo mesmo critério — a que compartilha o
    namespace com outra.
    """
    offenders = sorted(
        {
            f"{filename}:{line} ({kind})"
            for filename, line, kind, _ in _hit_calls()
            if kind not in search.HIT_ANCHOR and kind not in search.ANCHORLESS_HITS
        }
    )

    assert offenders == [], (
        "estes resultados de busca não dizem qual linha da tela abrem: "
        + ", ".join(offenders)
        + ". Acrescente a espécie em `search.HIT_ANCHOR`, ou declare-a em"
        " `search.ANCHORLESS_HITS` com o motivo escrito — sem isso o clique cai na"
        " aba e a degradação é invisível, que é o defeito que a ADR 0033 nomeou."
    )


def test_the_anchorless_hits_list_has_no_dead_entries() -> None:
    """A isenção da busca vence, e não se sobrepõe ao mapa.

    Duas perguntas numa, pela razão de as duas serem sobre a mesma frouxidão. A
    **linha morta**: uma espécie que ganhou âncora e continua isenta é allowlist
    que ninguém revisa — sedimento, na palavra da ADR 0033 —, e quem ler a lista
    concluirá que a ausência de âncora ali é decisão em vigor. A **sobreposição**:
    estar nas duas tabelas faria a guarda de cima aceitar uma espécie que já tem
    espaço de nomes, e a isenção passaria a cobrir justamente quem não precisa
    dela — é a oitava asserção da ADR 0056 aplicada aqui.
    """
    built = {kind for _, _, kind, _ in _hit_calls()}

    stale = sorted(kind for kind in search.ANCHORLESS_HITS if kind not in built)
    assert stale == [], (
        "estas espécies estão em `search.ANCHORLESS_HITS` e a busca não constrói"
        f" `Hit` nenhum com elas: {', '.join(stale)}. Tire a linha."
    )

    both = sorted(kind for kind in search.HIT_ANCHOR if kind in search.ANCHORLESS_HITS)
    assert both == [], (
        f"espécies em `HIT_ANCHOR` e `ANCHORLESS_HITS` ao mesmo tempo: {both}"
    )


def test_the_query_parameters_the_link_writes_are_the_ones_the_screen_reads() -> None:
    """Os nomes que o ``deep_link`` escreve na URL são os que o BFF e a tela leem.

    A terceira fronteira desta família, e a que faltava. ``tabs.py`` cobre o
    **valor** da aba e o ``ITEM_ANCHOR`` cobre o **valor** do namespace; ninguém
    cobria o **nome do parâmetro**. Renomear ``&item=`` para ``&row=`` só no
    Python deixa tudo verde: a URL sai bem formada, o BFF lê ``item`` e recebe
    ``undefined``, a tela abre a aba certa e não destaca nada. Até esta guarda,
    quem pegaria isso era só o e2e — que precisa da pilha inteira de pé e, desde
    13/08/2026, de um portal que não existe.

    Os dois leitores entram porque são dois saltos independentes: ``page.tsx``
    tira o valor da barra de endereço, e ``DashboardClient.tsx`` tira o **mesmo**
    parâmetro do ``link`` do aviso quando decide se intercepta o clique. Um nome
    trocado em qualquer um dos dois é a mesma falha silenciosa.
    """
    source = _SOURCE_ROOT.joinpath("notifications.py").read_text(encoding="utf-8")
    body = source[source.index("def deep_link(") :]
    written = sorted(set(re.findall(r"[?&](\w+)=", body)))
    assert written == ["item", "project", "tab"], (
        f"o `deep_link` passou a escrever outros parâmetros: {written}."
        " Se for de propósito, os leitores abaixo precisam saber deles."
    )

    page = (_REPO_ROOT / "app" / "page.tsx").read_text(encoding="utf-8")
    params = re.search(r"searchParams:\s*Promise<\{([^}]*)\}>", page)
    assert params is not None, "não achei o tipo de `searchParams` em app/page.tsx"

    dashboard = _dashboard()
    missing = [
        name
        for name in written
        if not re.search(rf"\b{name}\?:", params.group(1))
        or f'.get("{name}")' not in dashboard
    ]

    assert missing == [], (
        f"o `deep_link` escreve {missing} na URL e o outro lado não os lê pelo"
        " mesmo nome. Confira o tipo de `searchParams` em `app/page.tsx` e o"
        " `anchorTarget` em `app/DashboardClient.tsx` — um nome trocado aqui abre"
        " a tela certa sem destaque nenhum, e nada fica vermelho."
    )
