"""A âncora do aviso é alcançável na tela que o aviso abre (FDD 021, ADR 0056).

Arquivo próprio e **não** extensão do ``test_tabs.py``: aquele tem docstring
específico sobre o rótulo da aba ser identificador em dois deployables, e a varredura
de AST daqui o soterraria. O custo é umas quatro linhas de regex duplicadas para ler
o TSX, e vale.

O modo de falha que estas guardas existem para pegar é silencioso do começo ao fim:
o cliente recebe a mensagem, clica, chega na aba certa — e **nada acontece**. Não há
erro, não há log, não há teste vermelho. É a mesma classe da ADR 0033 (painel sobre
campo sem escritor) e da ADR 0043 (controle sobre campo sem escritor), agora entre o
Python que compõe a URL e o TSX que teria de reconhecê-la.
"""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path

from portal_api import notifications, tabs
from portal_api.models import NotificationKind

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_ROOT = _REPO_ROOT / "apps" / "api" / "src" / "portal_api"
_DASHBOARD = _REPO_ROOT / "app" / "DashboardClient.tsx"

#: `data-item={`milestone:${item.title}`}` — o que interessa é o prefixo.
_DATA_ITEM = re.compile(r"data-item=\{`([a-z]+):")
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
    """
    published = set(notifications.ITEM_ANCHOR.values())
    rendered = set(_DATA_ITEM.findall(_dashboard()))

    assert published == rendered, (
        "os espaços de nomes da âncora divergem entre os dois deployables. "
        f"só no Python: {sorted(published - rendered)}; "
        f"só no TSX: {sorted(rendered - published)}. "
        "Acrescente o `data-item={`<ns>:${…}`}` na lista correspondente de "
        "`app/DashboardClient.tsx`, ou tire a linha de `notifications.ITEM_ANCHOR`."
    )


def test_the_anchor_lands_on_the_tab_the_link_opens() -> None:
    """E o ``data-item`` está na aba que o ``LINK_TAB`` abre, não em outra qualquer.

    Existir não basta: um ``pending:`` renderizado só na Visão geral deixaria o link
    de ``pending_opened`` — que abre Pendências — apontando para uma linha que
    aquela aba não desenha. É o mesmo elo frouxo que a ADR 0035 mediu ao dar
    ``POST /chat`` como coberto por um 404 que era de outra rota.

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

    misplaced: list[str] = []
    for kind, namespace in notifications.ITEM_ANCHOR.items():
        tab = notifications.LINK_TAB[kind]
        component = tab_component[tab]
        reachable = {component} | {
            child for child in _CHILD.findall(blocks.get(component, "")) if child in blocks
        }
        if not (where.get(namespace, set()) & reachable):
            misplaced.append(
                f"{kind.value}: `{namespace}:` abriria a aba {tab!r} ({component}), "
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
