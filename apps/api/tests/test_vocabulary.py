"""O vocabulário canônico, e a guarda que impede um termo fora dele de voltar (Issue #91).

O [Language Map v1.1](../../../docs/ontology/language-map.md) é normativo desde a
ADR 0079, e a §6 dele começa com a frase que esta fatia existe para cumprir: *"Estas
viram teste automatizado no Pulse e revisão de PR nos dois repos."* Revisão de PR é o
mecanismo que a ADR 0034 já mediu e reprovou — lá o `alerts.md` foi corrigido à mão,
ficou sem portão e **em dois dias divergiu de novo pelo outro lado**.

**A dívida deste repositório é quase zero, e isso muda o argumento da guarda.** As três
fatias anteriores da adoção (ADR 0079, 0081 e 0082) renomearam a superfície, atravessaram
o degrau canônico e publicaram a lista positiva de visibilidade; a varredura desta achou
**zero** identificador novo a corrigir. Uma guarda que nasce verde sobre um repositório
limpo é preventiva, não pagadora de dívida — e o peso todo dela cai na **medição por
mutação** (ADR 0065), porque não há vermelho de nascença para exibir. As mutações estão
na tabela da ADR desta fatia.

## O que casa: batismo, nunca referência de uso

A guarda olha **declaração** — `class`, `def`, campo, constante de módulo, `type`,
`interface`, `const`, `function`, `let`, chave de enum —, e nunca uma referência de uso.
Não é preciosismo: `app/DashboardClient.tsx` cita `GateOutcome` em **duas notas
históricas** que explicam por que a D7 renomeou o termo, e `models/project.py` e a
migração `0039` fazem o mesmo. Uma guarda por referência cobraria que o repositório
apagasse o registro da própria decisão — que é exatamente o defeito que a ADR 0034 teve
de contornar no `alerts.md` ao ignorar as notas históricas do runbook.

A assimetria entre os dois lados é deliberada e foi medida. Em Python a guarda lê
`class`, `def` e atribuição em **nível de módulo ou de classe**; em TypeScript lê
`const`/`let` em **qualquer profundidade**. A razão é que `const` é a única forma de
declarar um valor em TS, então restringir por profundidade isentaria o corpo inteiro de
todo componente — e `stuckOnClient`, o caso que carrega esta fatia, mora dentro de uma
função. Do lado Python, incluir os locais acrescentaria **20 ocorrências**, das quais 10
são o literal `client = <cliente boto3>` de `storage.py`: vocabulário de transporte,
sete linhas de allowlist dizendo a mesma coisa sete vezes. O que se perde está nomeado
como item aberto na ADR: um local Python chamado `client_rows` passa.

## A armadilha que carrega a fatia

Oito componentes deste repositório se chamam `…Client` — `DashboardClient`,
`FunnelClient`, `KnowledgeClient` e os outros cinco. São **React Client Components**, e
`Client` ali é o vocabulário do React, não a organização. A isenção óbvia é pelo
*arquivo*: `*Client.tsx` inteiro fica de fora.

Ela está errada, e o erro é mensurável. `stuckOnClient` mora em
`app/admin/funnel/FunnelClient.tsx:111` — a isenção por arquivo o perdoa junto, **sem
nada ficar vermelho**. É o `.priority` da ADR 0033 e o corpus único que aquela ADR mediu.

A isenção correta é pela forma do **identificador**: o nome que é o `export default
function` do módulo *e* coincide com o basename do arquivo, num módulo que declara
`"use client"`. Medido: com a isenção por arquivo, renomear `stuckOnClient` para
`clientRows` passa verde; com a isenção por identificador, reprova.

## A allowlist não nasce vazia

`docs/ontology/legacy-allowlist.txt` nasce carregando as sobrevivências decididas, cada
uma com a razão escrita: `Blame.client` e `_client_has_authenticated` são o **lado**
(as pessoas do cliente), não a organização; `client_member` é papel de pessoa e já é
sobrevivência registrada na ADR 0079; `client_id`/`client_secret` são termos da RFC 6749;
`CLIENT_ERRORS` é a família 4xx da RFC 9110. Uma allowlist vazia é o defeito que a ADR
0033 nomeou (*"seguia vazia porque nada a consultava"*) e a asserção sobre lista vazia
que a ADR 0082 registrou (*"não percorre ramo nenhum"*).

Ela **só encolhe**. Não tem `review_by` e não tem prazo, no precedente do
`PINNED_BY_EXCEPTION` (ADR 0063) e do `FOUNDATION_WITHOUT_A_LINE` (ADR 0054) e **não** no
do `advisories.json`: dívida de vocabulário não caduca por calendário — ela some no dia
em que o termo sai do código, e quem a vence é
`test_the_allowlist_does_not_keep_a_line_that_stopped_being_needed`. A contagem é campo
separado justamente para impedir carona: uma ocorrência nova sob uma chave já isenta
reprova.

## Onde ela roda, e por que não é uma regra de eslint

Aqui, em `pytest`, dentro do job `api-quality` que já existe. `eslint.config.mjs` ignora
`apps/**`, então uma regra de eslint nunca alcançaria o lado Python — e "guarda que para
na fronteira do pacote" é literalmente o defeito que a ADR 0035 consertou na varredura de
telemetria. É uma guarda só, sobre os dois deployables, pela mesma razão de o `alerts.md`
ter uma só: **duas guardas sobre a mesma afirmação divergem**.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LANGUAGE_MAP = REPO_ROOT / "docs" / "ontology" / "language-map.md"
ALLOWLIST = REPO_ROOT / "docs" / "ontology" / "legacy-allowlist.txt"

#: A raiz do pacote Python — um dos dois deployables.
PYTHON_ROOT = REPO_ROOT / "apps" / "api" / "src" / "portal_api"

#: As raízes do BFF, e os três arquivos de raiz que o `CLAUDE.md` nomeia como parte
#: da camada web (`auth.ts`, `proxy.ts`) mais o `instrumentation.ts` que registra o
#: erro que o cliente vê. `next-env.d.ts` é gerado e fica de fora por isso.
WEB_ROOTS = (REPO_ROOT / "app", REPO_ROOT / "components")
WEB_FILES_AT_THE_ROOT = ("auth.ts", "proxy.ts", "instrumentation.ts")

#: O núcleo onde um modelo é batizado — o alcance da regra `modelo-em-portugues`.
CORE_MODEL_PREFIXES = (
    "apps/api/src/portal_api/models/",
    "apps/api/src/portal_api/schemas.py",
)


# Tudo abaixo é função pura de arquivo que a suíte não escreve, e as três asserções
# centrais varrem o repositório inteiro cada uma. Sem `@cache`, a guarda relê o
# `language-map.md` uma vez por identificador e leva 11s; com ele, 1,4s. É otimização
# mecânica e não muda o que a guarda afirma — cada mutação da tabela da ADR 0083 roda
# num processo próprio, e as dezoito reproduzem idênticas com e sem o memo.


# --- tokenização ------------------------------------------------------------
#
# `CamelCase` e `snake_case` na mesma moeda, que é a decisão que a ADR 0082 já
# tinha tomado para os recursos proibidos do contrato: comparar token, nunca
# substring. `ShowcaseOut` não é `case`, e `stuckOnClient` é `client`.

_TOKEN = re.compile(r"[A-ZÀ-Þ]+(?![a-zà-ÿ])|[A-ZÀ-Þ]?[a-zà-ÿ0-9]+")


@cache
def tokens(name: str) -> tuple[str, ...]:
    """Os tokens de um identificador, em minúsculas.

    >>> tokens("stuckOnClient")
    ('stuck', 'on', 'client')
    >>> tokens("CLIENT_ERRORS")
    ('client', 'errors')
    >>> tokens("ProcessoEtapa")
    ('processo', 'etapa')
    """
    parts: list[str] = []
    for chunk in re.split(r"[^0-9A-Za-zÀ-ÿ]+", name):
        if chunk:
            parts.extend(_TOKEN.findall(chunk))
    return tuple(part.lower() for part in parts)


def has_sequence(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    """A sequência aparece **contígua** dentro da outra.

    Contígua e não apenas presente: é o que separa `GateOutcome` de
    `AgentEventOutcome`, que é campo legítimo (resultado do evento, não decisão de
    gate) e que um banimento do token `outcome` teria pegado.
    """
    size = len(needle)
    if size == 0 or size > len(haystack):
        return False
    return any(haystack[i : i + size] == needle for i in range(len(haystack) - size + 1))


# --- o mapa normativo -------------------------------------------------------
#
# Nenhum termo desta guarda é digitado: todos saem das tabelas do
# `language-map.md`. Lista digitada à mão é o defeito das ADRs 0033 e 0035, e aqui
# ela teria a agravante de deixar a guarda banir em nome de um termo que o
# documento normativo não conhece.


def _section(text: str, heading: str) -> str:
    """O corpo de uma seção `##`, até a próxima."""
    body: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip().lower().startswith(heading.lower())
            continue
        if inside:
            body.append(line)
    return "\n".join(body)


def table_rows(block: str) -> list[tuple[str, ...]]:
    """As linhas de dado de uma tabela markdown, sem cabeçalho nem separador."""
    rows: list[tuple[str, ...]] = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if all(set(cell) <= set("-: ") for cell in cells):
            continue
        rows.append(cells)
    return rows[1:] if rows else rows


@cache
def _map_text() -> str:
    return LANGUAGE_MAP.read_text(encoding="utf-8")


@cache
def master_table() -> list[tuple[str, ...]]:
    """A §2 — termo canônico, as quatro superfícies e a coluna "Nunca chamar de"."""
    return table_rows(_section(_map_text(), "## 2."))


@cache
def banned_table() -> list[tuple[str, ...]]:
    """A §5 — termo banido, por quê, o que usar."""
    return table_rows(_section(_map_text(), "## 5."))


@lru_cache(maxsize=None)
def _banned_row(fragment: str) -> tuple[str, ...]:
    """A linha da §5 cuja célula de termo contém o fragmento, e só ela."""
    matches = [row for row in banned_table() if fragment in row[0]]
    assert len(matches) == 1, (
        f"a §5 do Language Map devia ter exatamente uma linha contendo {fragment!r}, "
        f"e tem {len(matches)}. Se o documento mudou, a regra que depende dela mudou "
        "junto — decida, não conserte o casador."
    )
    return matches[0]


def _backticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def _bolded(cell: str) -> list[str]:
    return re.findall(r"\*\*([^*]+)\*\*", cell)


def _quoted(cell: str) -> list[str]:
    return re.findall(r"[\"“]([^\"”]+)[\"”]", cell)


# --- corpus -----------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    path: str
    text: str


@cache
def python_sources() -> list[Source]:
    return [
        Source(str(path.relative_to(REPO_ROOT)), path.read_text(encoding="utf-8"))
        for path in sorted(PYTHON_ROOT.rglob("*.py"))
    ]


@cache
def web_sources() -> list[Source]:
    found: list[Path] = []
    for root in WEB_ROOTS:
        found.extend(root.rglob("*.ts"))
        found.extend(root.rglob("*.tsx"))
    found.extend(REPO_ROOT / name for name in WEB_FILES_AT_THE_ROOT)
    return [
        Source(str(path.relative_to(REPO_ROOT)), path.read_text(encoding="utf-8"))
        for path in sorted(set(found))
    ]


# --- declarações ------------------------------------------------------------


@dataclass(frozen=True)
class Declaration:
    path: str
    line: int
    name: str
    kind: str


def python_declarations(source: Source) -> list[Declaration]:
    """Classe, função, campo de classe e constante de módulo. Não parâmetro, não local.

    O corpo de uma função não é percorrido: ali um nome é local, e o equivalente
    Python de "campo" e "constante" é exatamente o que mora em nível de módulo e de
    classe. A medição que sustenta o recorte está no docstring do módulo.
    """
    found: list[Declaration] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                found.append(Declaration(source.path, child.lineno, child.name, "class"))
                visit(child)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.append(Declaration(source.path, child.lineno, child.name, "def"))
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        found.append(
                            Declaration(source.path, child.lineno, target.id, "field")
                        )
            elif isinstance(child, ast.AnnAssign) and isinstance(
                child.target, ast.Name
            ):
                found.append(
                    Declaration(source.path, child.lineno, child.target.id, "field")
                )
            elif isinstance(child, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                visit(child)

    visit(ast.parse(source.text))
    return found


@dataclass(frozen=True)
class Stripped:
    """O arquivo TS separado nas três coisas que a guarda pergunta por caminhos diferentes."""

    code: str
    literals: tuple[tuple[int, str], ...]
    jsx: tuple[tuple[int, str], ...]


def strip_typescript(text: str) -> Stripped:
    """Separa código, literais de string e texto JSX, preservando número de linha.

    Sem parser de TypeScript e por decisão: o que a guarda precisa é distinguir
    **comentário** de **código** e de **texto**, e um autômato de quatro estados faz
    isso. O comentário sai por construção, que é o que mantém as notas históricas de
    `GateOutcome` fora do alcance da guarda — o mesmo recorte por forma que a ADR 0064
    usou para a fence de estrutura.
    """
    out: list[str] = []
    literals: list[tuple[int, str]] = []
    index = 0
    size = len(text)
    state = "code"
    buffer = ""
    started = 1
    line = 1
    while index < size:
        char = text[index]
        if char == "\n":
            line += 1
        if state == "code":
            if char == "/" and index + 1 < size and text[index + 1] == "/":
                state = "line-comment"
                index += 2
                continue
            if char == "/" and index + 1 < size and text[index + 1] == "*":
                state = "block-comment"
                index += 2
                continue
            if char in "'\"`":
                state = char
                buffer = ""
                started = line
                out.append('"')
                index += 1
                continue
            out.append(char)
            index += 1
            continue
        if state == "line-comment":
            if char == "\n":
                state = "code"
                out.append("\n")
            index += 1
            continue
        if state == "block-comment":
            if char == "*" and index + 1 < size and text[index + 1] == "/":
                state = "code"
                index += 2
                continue
            if char == "\n":
                out.append("\n")
            index += 1
            continue
        # dentro de uma string
        if char == "\\":
            buffer += text[index : index + 2]
            index += 2
            continue
        if char == state:
            literals.append((started, buffer))
            state = "code"
            out.append('"')
            index += 1
            continue
        if char == "\n":
            out.append("\n")
        buffer += char
        index += 1
    code = "".join(out)
    jsx: list[tuple[int, str]] = []
    for match in re.finditer(r">([^<>{}]+)<", code):
        content = match.group(1).strip()
        if content:
            jsx.append((code.count("\n", 0, match.start()) + 1, content))
    return Stripped(code=code, literals=tuple(literals), jsx=tuple(jsx))


_WEB_DECLARATIONS = (
    re.compile(r"\b(?:class|interface|type|enum)\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)"),
    # Chave de enum, campo de `interface`/`type` e chave de objeto literal: as três
    # têm a mesma forma e as três são batismo. Desestruturação (`const { client }`)
    # fica de fora de propósito — ali o nome é de quem o publicou.
    re.compile(r"(?m)^[ \t]*(?:readonly[ \t]+)?([A-Za-z_$][\w$]*)[ \t]*[?!]?[ \t]*:"),
)

_USE_CLIENT = re.compile(r"^\s*[\"']use client[\"']")
_DEFAULT_COMPONENT = re.compile(r"\bexport\s+default\s+function\s+([A-Za-z_$][\w$]*)")


def default_client_component(source: Source) -> str | None:
    """O nome do React Client Component que o módulo publica, se ele for um.

    Três condições ao mesmo tempo: o módulo declara ``"use client"``, tem um
    ``export default function``, e o nome dele é o basename do arquivo. É a isenção
    por **identificador**, e a diferença para a isenção por *arquivo* é a medição
    que carrega esta fatia (ver o docstring do módulo).
    """
    if not _USE_CLIENT.match(source.text):
        return None
    match = _DEFAULT_COMPONENT.search(strip_typescript(source.text).code)
    if not match:
        return None
    stem = Path(source.path).name.rsplit(".", 1)[0]
    return match.group(1) if match.group(1) == stem else None


def web_declarations(source: Source) -> list[Declaration]:
    code = strip_typescript(source.text).code
    found: dict[tuple[str, int], Declaration] = {}
    for pattern in _WEB_DECLARATIONS:
        for match in pattern.finditer(code):
            name = match.group(1)
            line = code.count("\n", 0, match.start()) + 1
            found.setdefault(
                (name, line), Declaration(source.path, line, name, "web")
            )
    return list(found.values())


@cache
def declarations() -> list[tuple[Source, list[Declaration]]]:
    return [(source, python_declarations(source)) for source in python_sources()] + [
        (source, web_declarations(source)) for source in web_sources()
    ]


# --- texto visível ----------------------------------------------------------


def python_visible_text(source: Source) -> list[tuple[int, str]]:
    """Literais de string que **não** são docstring.

    A exclusão do docstring não é hipótese: `models/meeting.py:5` diz "transcription
    of external recordings is out of the MVP (see PRD)", que é prosa histórica sobre
    o produto e não texto que alguém lê na tela. Sem o recorte, a regra
    `prove-nao-e-piloto` nasceria vermelha em cima de um comentário.
    """
    tree = ast.parse(source.text)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            found.append((node.lineno, node.value))
    return found


@cache
def visible_text() -> list[tuple[Source, list[tuple[int, str]]]]:
    """Tudo que pode virar linha na tela do cliente, nos dois deployables.

    No web, literal de string e texto JSX; na API, literal de string que não é
    docstring — porque o corpo de um aviso e a frase que declara lacuna nascem em
    Python e chegam à mesma tela.
    """
    found: list[tuple[Source, list[tuple[int, str]]]] = []
    for source in web_sources():
        stripped = strip_typescript(source.text)
        found.append((source, list(stripped.literals) + list(stripped.jsx)))
    for source in python_sources():
        found.append((source, python_visible_text(source)))
    return found


# --- as regras --------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    identifier: str
    detail: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.rule, self.identifier)


R1 = "opportunity-sem-qualificador"
R2 = "client-como-organizacao"
R3 = "outcome-como-decisao-de-gate"
R4 = "modelo-em-portugues"
R5 = "nome-do-produto"
R6 = "prove-nao-e-piloto"
R7 = "roi-sem-rotulo-de-projecao"


@cache
def opportunity_terms() -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Os qualificadores e as exceções nomeadas, tiradas da célula "Usar" da §5.

    Os qualificadores saem dos dois termos canônicos em backtick
    (`CommercialOpportunity`, `ImprovementOpportunity`); as exceções saem das três
    frases em negrito, que a §5 chama de "rótulos de artefato — nomes de entregável,
    não entidades". Nada digitado: se o documento mudar as exceções, a regra muda com
    ele, que é a razão de a ADR 0082 ter deixado esta palavra **fora** do contrato de
    visibilidade de propósito ("se esta guarda a banisse por identificador, ela e o
    lint colidiriam").
    """
    row = _banned_row("Opportunity` sem qualificador")
    qualifiers = tuple(
        sorted(
            {
                tokens(name)[0]
                for name in _backticked(row[2])
                if len(tokens(name)) == 2 and tokens(name)[1] == "opportunity"
            }
        )
    )
    exceptions = tuple(tokens(label) for label in _bolded(row[2]))
    return qualifiers, exceptions


def find_opportunity(declaration: Declaration) -> Finding | None:
    qualifiers, exceptions = opportunity_terms()
    parts = tokens(declaration.name)
    for position, token in enumerate(parts):
        if token != "opportunity":
            continue
        if position and parts[position - 1] in qualifiers:
            continue
        if any(has_sequence(parts, exception) for exception in exceptions):
            continue
        return Finding(
            declaration.path,
            declaration.line,
            R1,
            declaration.name,
            "`opportunity` sem `"
            + "`/`".join(qualifiers)
            + "` ao lado: a palavra colide entre venda e melhoria operacional",
        )
    return None


@cache
def client_token() -> str:
    """O token que a §5 bane como nome de modelo. Sai do documento, não daqui."""
    row = _banned_row("Client` como nome de modelo")
    return tokens(_backticked(row[0])[0])[0]


def find_client(declaration: Declaration, exempt: str | None) -> Finding | None:
    if exempt is not None and declaration.name == exempt:
        return None
    if client_token() not in tokens(declaration.name):
        return None
    return Finding(
        declaration.path,
        declaration.line,
        R2,
        declaration.name,
        "a organização é `Account` desde prospect (§5); `client` só sobrevive onde "
        "nomeia a pessoa, o protocolo ou a chave persistida, e isso se escreve na allowlist",
    )


@cache
def gate_outcome_sequence() -> tuple[str, ...]:
    row = _banned_row("GateOutcome")
    return tokens(_backticked(row[0])[0])


def find_gate_outcome(declaration: Declaration) -> Finding | None:
    if not has_sequence(tokens(declaration.name), gate_outcome_sequence()):
        return None
    return Finding(
        declaration.path,
        declaration.line,
        R3,
        declaration.name,
        "a D7 renomeou `GateOutcome` para `GateDecision`: `Outcome` é resultado de "
        "negócio medido, e os dois na mesma palavra fariam a tela chamar de "
        "\"resultado\" uma decisão de metodologia",
    )


@cache
def portuguese_model_names() -> tuple[tuple[str, ...], ...]:
    """Os nomes em português que a §5 bane no modelo, tirados da própria linha."""
    row = _banned_row("Evidencia")
    return tuple(tokens(name) for name in _backticked(row[0]))


def find_portuguese_model(declaration: Declaration) -> Finding | None:
    if declaration.kind != "class":
        return None
    if not any(
        declaration.path.startswith(prefix) for prefix in CORE_MODEL_PREFIXES
    ):
        return None
    parts = tokens(declaration.name)
    banned = [
        name for name in portuguese_model_names() if has_sequence(parts, name)
    ]
    if not banned:
        # O outro sinal, e ele é estrutural em vez de lexical: um identificador com
        # letra fora do ASCII não é inglês. Pega `Reunião` e `Solução`, e **não** pega
        # `Evidencia` — daí ele somar com a lista da §5 em vez de substituí-la. O que
        # sobra sem portão (português sem acento e não nomeado na §5) é item aberto
        # declarado na ADR, e não promessa não cumprida.
        if all(character.isascii() for character in declaration.name):
            return None
    return Finding(
        declaration.path,
        declaration.line,
        R4,
        declaration.name,
        "nome de modelo em português: os termos canônicos são em inglês nas quatro "
        "superfícies (§1), e traduz-se o texto em volta do termo, nunca o termo",
    )


@dataclass(frozen=True)
class Phrase:
    text: str
    rule: str
    use: str

    @property
    @cache
    def pattern(self) -> re.Pattern[str]:
        # Sigla (tudo em maiúscula no mapa) casa com distinção de caixa; frase em
        # prosa, não. É o recorte que `tests/rendered-html.test.mjs` já usa desde a
        # fatia da #88 — `/\bPOC\b/` contra `/piloto/i` —, e é o que impede `POC` de
        # casar dentro de "pocket".
        flags = 0 if self.text.isupper() else re.IGNORECASE
        return re.compile(rf"\b{re.escape(self.text)}\b", flags)


@cache
def product_name_phrases() -> tuple[Phrase, ...]:
    """As duas linhas da §5 que trocam o nome do produto por um genérico."""
    found: list[Phrase] = []
    for fragment in ("Cockpit", "portal Biahflow"):
        row = _banned_row(fragment)
        use = (_bolded(row[2]) or [row[2]])[0]
        found.extend(Phrase(text, R5, use) for text in _quoted(row[0]))
    return tuple(found)


@cache
def prove_phrases() -> tuple[Phrase, ...]:
    """O que o PROVE não é, das duas metades do mapa que o dizem.

    A §5 nomeia "POC" e "piloto"; o **MVP** só aparece na coluna "Nunca chamar de" da
    §2, na linha do `ProveExperiment`. As duas metades entram, e é por isso que a
    regra alcança os três termos que a fatia da #88 já apagava da tela.
    """
    row = _banned_row("para o PROVE")
    use = (_bolded(row[2]) or [row[2]])[0]
    found = {text.lower(): Phrase(text, R6, use) for text in _quoted(row[0])}
    for line in master_table():
        if tokens(re.sub(r"\*+", "", line[0])) == ("prove", "experiment"):
            for term in line[5].split(","):
                term = term.strip()
                if term:
                    # Chaveado em minúsculas: a §5 escreve "piloto" e a §2 escreve
                    # "Piloto", e duas entradas para a mesma palavra fariam a regra
                    # acusar a mesma linha duas vezes.
                    found.setdefault(term.lower(), Phrase(term, R6, use))
    return tuple(found[key] for key in sorted(found))


@cache
def visible_text_phrases() -> tuple[Phrase, ...]:
    return product_name_phrases() + prove_phrases()


def find_phrases(path: str, line: int, snippet: str) -> list[Finding]:
    return [
        Finding(
            path,
            line,
            phrase.rule,
            phrase.text,
            f"texto visível ao cliente diz {phrase.text!r}; o termo é {phrase.use}",
        )
        for phrase in visible_text_phrases()
        if phrase.pattern.search(snippet)
    ]


# --- o ROI que não diz qual ROI é -------------------------------------------
#
# A §5 bane `"ROI" como resultado` com a razão escrita ao lado: *"ROI projetado não é
# resultado medido"*. Este repositório projeta **dois** ROIs — o do snapshot do
# Biahflow (`RoiOut`, que a origem afirma) e o apurado na leitura pela premissa
# vigente no dia do evento (`ResultsOut`, ADR 0013) —, e o identificador está certo
# dos dois lados. O que falta é o **rótulo**: um número sem ele deixa o cliente ler
# uma promessa como se fosse medição.
#
# Daí a regra ser sobre texto visível e **não** caber em `find_phrases`: lá a
# presença da frase reprova, e aqui reprova a presença **sem** o qualificador.

#: O segundo qualificador não sai do mapa, e a razão de ele ser decisão deste
#: repositório fica escrita aqui, no padrão de `UNLINTABLE` e do `NOT_AN_ALERT` da
#: ADR 0034. Chave → por que ela não é derivável, em prosa contestável.
LOCAL_QUALIFIERS: dict[str, str] = {
    "apurado": (
        "O mapa só nomeia o lado projetado porque, nos termos dele, o lado medido é "
        "`Outcome` — e `Outcome` não tem produtor neste repositório: o Pulse tem o "
        "modelo `Measurement` e não o emite no snapshot. `apurado` é o nome "
        "pré-`Outcome` que a ADR 0013 deu ao lado medido, e ele deixa de ser "
        "necessário no dia em que o `Outcome` atravessar."
    ),
}

#: Prefixo de caminho → por que o que se lê ali **não** é a tela do cliente. A regra
#: é sobre o que o cliente lê: uma tela do time que diz "ROI" sem qualificar está
#: falando com quem sabe qual dos dois é. Exclusão sem razão escrita é allowlist
#: disfarçada (ADR 0082), e a asserção de obsolescência é o vencimento desta.
INTERNAL_SURFACES: dict[str, str] = {
    "app/admin/": (
        "Superfície interna, e é o mesmo recorte que o `one-visibility.json` já usa e "
        "registra (\"`/api/v1/admin/*` é superfície interna\"): quem abre `/admin` é "
        "membro do time, não o cliente."
    ),
    "apps/api/src/portal_api/onboarding.py": (
        "O funil, cujo aviso é `_INTERNAL_ONLY` desde a ADR 0040 — o primeiro do "
        "produto a nunca chegar ao cliente. O leitor das frases com \"ROI\" ali é "
        "quem vai ligar para o cliente travado, e o que ele precisa saber é que o "
        "número não foi visto."
    ),
}


def internal_surface(path: str) -> str | None:
    """O prefixo de `INTERNAL_SURFACES` que cobre este caminho, se houver."""
    for prefix in INTERNAL_SURFACES:
        if path.startswith(prefix):
            return prefix
    return None


_INFLECTION = re.compile(r"[oa]s?$")


def _stem(word: str) -> str:
    """O radical de um particípio português, para a regra alcançar as flexões.

    `projetado` → `projetad`, `apurado` → `apurad`. É o que faz "ROI projetada" e
    "ROI apurados" passarem sem que a guarda precise de uma lista de flexões digitada
    — lista digitada é o defeito das ADRs 0033 e 0035.

    **Só a desinência sai, e o corte foi medido.** Cortar o sufixo inteiro do
    particípio (`-ado`) daria o radical `projet`, que casa com **"projeto"** — e
    "ROI do projeto", a manchete que esta fatia existe para rotular, passaria verde
    dizendo-se qualificada pela palavra "projeto". Um radical curto demais não é
    tolerância, é o `.priority` da ADR 0033: a guarda nasceria verde em cima do
    defeito exato que ela existe para pegar.
    """
    return _INFLECTION.sub("", word.lower())


@cache
def roi_term() -> str:
    """O termo que a §5 bane. Sai do documento, entre aspas, como os do `R5`/`R6`."""
    row = _banned_row('"ROI" como resultado')
    quoted = _quoted(row[0])
    assert len(quoted) == 1, (
        "a linha do ROI na §5 devia nomear exatamente um termo entre aspas, e nomeia "
        f"{quoted}. O documento mudou de forma — decida o que a regra passa a fazer."
    )
    return quoted[0]


@cache
def roi_qualifiers() -> tuple[str, ...]:
    """O que precisa estar ao lado do termo para o texto dizer **qual** ROI é.

    O primeiro sai da própria célula "Por quê" da §5 — *"ROI projetado não é
    resultado medido"*, e a palavra imediatamente depois do termo é o qualificador.
    O segundo é `LOCAL_QUALIFIERS`, com a razão escrita lá.
    """
    row = _banned_row('"ROI" como resultado')
    match = re.search(rf"\b{re.escape(roi_term())}\s+(\w+)", row[1])
    assert match is not None, (
        f"a célula \"Por quê\" da linha do ROI não diz {roi_term()!r} seguido do "
        f"qualificador, e é de lá que ele sai: {row[1]!r}"
    )
    return (match.group(1), *LOCAL_QUALIFIERS)


@cache
def _roi_patterns() -> tuple[re.Pattern[str], tuple[re.Pattern[str], ...]]:
    return (
        # Sensível a caixa, e a estreiteza é deliberada: é sigla, o mesmo recorte que
        # `Phrase.pattern` já usa ("Sigla (tudo em maiúscula no mapa) casa com
        # distinção de caixa"). `roi` minúsculo é o campo `roiMonth` e o `roi_ratio`
        # do read model — identificador, que esta regra não julga —, e `ROIs` não
        # casa por `\b`.
        re.compile(rf"\b{re.escape(roi_term())}\b"),
        tuple(
            re.compile(rf"\b{_stem(qualifier)}\w*", re.IGNORECASE)
            for qualifier in roi_qualifiers()
        ),
    )


def mentions_roi(snippet: str) -> bool:
    term, _ = _roi_patterns()
    return term.search(snippet) is not None


def _roi_is_bare(snippet: str) -> bool:
    """O termo está no texto e nenhum qualificador diz qual dos dois ROIs ele é."""
    _, qualifiers = _roi_patterns()
    if not mentions_roi(snippet):
        return False
    return not any(qualifier.search(snippet) for qualifier in qualifiers)


def find_bare_roi(path: str, line: int, snippet: str) -> Finding | None:
    if internal_surface(path) is not None:
        return None
    if not _roi_is_bare(snippet):
        return None
    return Finding(
        path,
        line,
        R7,
        roi_term(),
        f"texto visível ao cliente diz {roi_term()!r} sem dizer **qual** dos dois é "
        "(falta o rótulo `" + "`/`".join(roi_qualifiers()) + "`): o projetado é a "
        "promessa da origem e não resultado medido (§5), e o apurado nasce dos "
        "eventos pela premissa vigente no dia do evento (ADR 0013)",
    )


@cache
def findings() -> list[Finding]:
    """Tudo que as sete regras acham, nos dois deployables."""
    found: list[Finding] = []
    for source, declared in declarations():
        exempt = (
            default_client_component(source)
            if source.path.endswith((".ts", ".tsx"))
            else None
        )
        for declaration in declared:
            found.append(find_opportunity(declaration))
            found.append(find_client(declaration, exempt))
            found.append(find_gate_outcome(declaration))
            found.append(find_portuguese_model(declaration))
    result = [finding for finding in found if finding is not None]
    for source, snippets in visible_text():
        for line, snippet in snippets:
            result.extend(find_phrases(source.path, line, snippet))
            bare = find_bare_roi(source.path, line, snippet)
            if bare is not None:
                result.append(bare)
    return result


# --- a allowlist ------------------------------------------------------------


@dataclass(frozen=True)
class Exemption:
    key: tuple[str, str, str]
    count: int
    line: int
    reason: str


@cache
def read_allowlist() -> list[Exemption]:
    """`caminho::regra::identificador::contagem`, e a razão na linha de comentário acima.

    A razão é obrigatória e a asserção que a cobra tem piso, no argumento que a ADR
    0082 escreveu para a lista positiva de visibilidade: **uma isenção cuja razão
    ninguém consegue escrever é uma isenção que não devia existir.**
    """
    exemptions: list[Exemption] = []
    reason: list[str] = []
    after_entry = False
    for number, raw in enumerate(
        ALLOWLIST.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            reason = []
            after_entry = False
            continue
        if line.startswith("#"):
            if after_entry:
                # Comentário depois de uma entrada abre um bloco de razão novo; um
                # bloco cobre a corrida de entradas que vem logo abaixo dele, que é
                # o que permite duas credenciais do mesmo par dividirem a frase que
                # explica as duas.
                reason = []
                after_entry = False
            reason.append(line.lstrip("#").strip())
            continue
        parts = line.split("::")
        assert len(parts) == 4, (
            f"{ALLOWLIST.name}:{number}: a linha não tem as quatro partes de "
            f"`caminho::regra::identificador::contagem`: {raw!r}"
        )
        path, rule, identifier, count = (part.strip() for part in parts)
        assert count.isdigit(), (
            f"{ALLOWLIST.name}:{number}: a contagem precisa ser um inteiro, e é {count!r}"
        )
        exemptions.append(
            Exemption(
                key=(path, rule, identifier),
                count=int(count),
                line=number,
                reason=" ".join(reason).strip(),
            )
        )
        after_entry = True
    return exemptions


def _counted(found: list[Finding]) -> dict[tuple[str, str, str], list[Finding]]:
    grouped: dict[tuple[str, str, str], list[Finding]] = {}
    for finding in found:
        grouped.setdefault(finding.key, []).append(finding)
    return grouped


# --- as regras cobrem o documento, e o documento cobre as regras -------------

#: Linha da §5 → por que ela **não** vira regra deste repositório, em prosa
#: contestável. Exclusão sem razão escrita é allowlist disfarçada (ADR 0082), e o
#: corpus é fail-closed nos dois sentidos: linha da §5 que ninguém reivindicou nem
#: excluiu reprova, e exclusão de linha que sumiu da §5 reprova também.
UNLINTABLE: dict[str, str] = {
    '"Opportunity Score" de uma venda': (
        "É afirmação sobre **a que entidade** um rótulo foi aplicado, não sobre o "
        "léxico: o mesmo identificador está certo sobre uma ImprovementOpportunity e "
        "errado sobre uma venda. Nenhuma varredura de fonte decide isso, e as duas "
        "entidades da frase não existem neste repositório — quem as terá é a Issue #90."
    ),
    "`Lead.ai_score` como qualificação": (
        "Campo do Pulse. `Lead` é a primeira linha da §3 (\"nunca no One\") e já tem "
        "portão próprio aqui: `forbidden_resources` do `one-visibility.json` reprova "
        "qualquer esquema ou campo de cliente que o nomeie (ADR 0082). Repetir a "
        "proibição nesta guarda seriam duas guardas sobre a mesma afirmação, que é o "
        "defeito que a ADR 0034 nomeou."
    ),
    "`Project.ai_opportunity` como prioridade": (
        "Campo do Pulse, e a confusão que a linha desfaz é entre maturidade de IA da "
        "conta e prioridade de melhoria — semântica de um campo que não existe aqui. "
        "O que **é** deste repositório na mesma palavra é a regra "
        f"`{R1}`, e ela está implementada."
    ),
}

#: Regra → as linhas da §5 que ela cobre.
CLAIMS: dict[str, tuple[str, ...]] = {
    R1: ("`Opportunity` sem qualificador",),
    R2: ("`Client` como nome de modelo",),
    R3: ("`GateOutcome`",),
    R4: ("`Evidencia`, `Processo`, `ProcessoEtapa`",),
    R5: ('"Cockpit", "portal do cliente"', '"portal Biahflow", "o CRM"'),
    R6: ('"POC", "piloto" para o PROVE',),
    R7: ('"ROI" como resultado',),
}


def rule_terms() -> dict[str, tuple[str, ...]]:
    """Os termos que cada regra bane, já derivados do mapa."""
    qualifiers, _ = opportunity_terms()
    return {
        R1: ("Opportunity",) + tuple(q.capitalize() + "Opportunity" for q in qualifiers),
        R2: (client_token().capitalize(),),
        R3: ("".join(part.capitalize() for part in gate_outcome_sequence()),),
        R4: tuple(
            "".join(part.capitalize() for part in name)
            for name in portuguese_model_names()
        ),
        R5: tuple(phrase.text for phrase in product_name_phrases()),
        R6: tuple(phrase.text for phrase in prove_phrases()),
        R7: (roi_term(),),
    }


# --- as asserções -----------------------------------------------------------


def test_the_corpus_covers_both_deployables_and_no_glob_comes_back_empty() -> None:
    """Fail-closed: um glob vazio reprova, em vez de deixar a guarda verde por omissão.

    É o precedente do `test_supply_chain_pins.py`, e o defeito que ele nomeia é o
    `dependency-review` da ADR 0023: verde por não ter olhado. Vale aqui com força
    dobrada, porque esta guarda nasce verde de propósito — sem esta asserção, um
    diretório renomeado a transformaria numa suíte que não afirma nada.
    """
    python = python_sources()
    web = web_sources()

    assert python, f"nenhum `.py` sob {PYTHON_ROOT}: o corpus da API sumiu"
    assert web, "nenhum `.ts`/`.tsx` no corpus do BFF"
    for name in WEB_FILES_AT_THE_ROOT:
        assert (REPO_ROOT / name).exists(), (
            f"`{name}` é nomeado no corpus e não existe. Ele saiu do repositório? "
            "Decida — não deixe a guarda deixar de olhá-lo em silêncio."
        )
    for root in WEB_ROOTS:
        assert any(
            source.path.startswith(root.name + "/") for source in web
        ), f"nenhum arquivo sob `{root.name}/`"
    assert master_table(), "a §2 do Language Map não produziu linha nenhuma"
    assert banned_table(), "a §5 do Language Map não produziu linha nenhuma"
    assert any(
        declared for _, declared in declarations()
    ), "nenhuma declaração foi extraída: o extrator parou de enxergar o repositório"


def test_the_client_surface_still_mentions_roi_at_all() -> None:
    """Fail-closed do `R7`: zero menção significa que o casador parou de olhar.

    A regra é a única que nasce **verde por correção do texto** em vez de por ausência
    do termo: as menções continuam lá, agora qualificadas. Se elas sumirem da
    varredura — porque o extrator de JSX mudou, porque a tela virou outra coisa —, a
    regra passa a não afirmar nada e a suíte fica verde por não ter olhado, que é o
    `dependency-review` da ADR 0023.
    """
    mentioned = [
        f"{source.path}:{line}"
        for source, snippets in visible_text()
        if internal_surface(source.path) is None
        for line, snippet in snippets
        if mentions_roi(snippet)
    ]
    assert mentioned, (
        f"nenhum texto visível da superfície do cliente menciona {roi_term()!r}. A "
        "regra continua carregada e não olha para nada: ou o produto deixou de "
        "mostrar o número, ou a varredura parou de alcançá-lo. Decida qual."
    )


def test_every_internal_surface_exclusion_still_exempts_an_occurrence() -> None:
    """A exclusão por superfície tem o mesmo vencimento que a allowlist: virar inútil.

    Precedente de `test_the_allowlist_does_not_keep_a_line_that_stopped_being_needed`.
    Um prefixo que não isenta mais nada é allowlist disfarçada esperando a próxima
    ocorrência passar de carona.
    """
    counted = {prefix: 0 for prefix in INTERNAL_SURFACES}
    for source, snippets in visible_text():
        prefix = internal_surface(source.path)
        if prefix is None:
            continue
        for _, snippet in snippets:
            if _roi_is_bare(snippet):
                counted[prefix] += 1

    idle = sorted(prefix for prefix, hits in counted.items() if hits == 0)
    assert idle == [], (
        "estes prefixos de `INTERNAL_SURFACES` não isentam mais nenhuma ocorrência:\n  "
        + "\n  ".join(idle)
        + "\nApague-os. A exclusão não tem prazo de propósito, e esta asserção é o "
        "único vencimento que ela tem."
    )


def test_no_banned_term_enters_either_deployable() -> None:
    """A asserção central: nenhum termo fora do vocabulário canônico, nos dois lados.

    A comparação é por **contagem** e não por presença. Uma chave já isenta que ganha
    uma ocorrência a mais reprova — sem isso, a primeira sobrevivência legítima de um
    arquivo abriria carona para todas as seguintes, que é a forma da allowlist que só
    cresce (ADR 0029).
    """
    allowed = {exemption.key: exemption.count for exemption in read_allowlist()}
    grouped = _counted(findings())

    offending: list[str] = []
    for key in sorted(grouped):
        occurrences = grouped[key]
        budget = allowed.get(key, 0)
        if len(occurrences) <= budget:
            continue
        path, rule, identifier = key
        lines = ", ".join(str(finding.line) for finding in sorted(
            occurrences, key=lambda finding: finding.line
        ))
        offending.append(
            f"{path}:{lines} [{rule}] `{identifier}` — {occurrences[0].detail}"
            + (f" (a allowlist isenta {budget}, e há {len(occurrences)})" if budget else "")
        )

    assert offending == [], (
        "estes nomes estão fora do vocabulário canônico do Language Map:\n  "
        + "\n  ".join(offending)
        + "\nUse o termo canônico. Se a ocorrência for uma sobrevivência decidida, "
        f"escreva a razão e a linha em `{ALLOWLIST.relative_to(REPO_ROOT)}` — e a "
        "razão é o portão de verdade."
    )


def test_every_allowlist_line_carries_a_reason() -> None:
    """Isenção sem razão escrita é allowlist disfarçada (ADR 0082)."""
    unexplained = [
        f"{ALLOWLIST.name}:{exemption.line}: "
        + "::".join(exemption.key)
        for exemption in read_allowlist()
        if len(exemption.reason) < 40
    ]
    assert unexplained == [], (
        "estas linhas isentam um termo sem dizer por quê (ou dizendo em menos de 40 "
        "caracteres):\n  " + "\n  ".join(unexplained)
        + "\nEscreva a razão numa linha de comentário imediatamente acima. Uma "
        "sobrevivência cuja razão ninguém consegue escrever é uma sobrevivência que "
        "não devia existir."
    )


def test_the_allowlist_does_not_keep_a_line_that_stopped_being_needed() -> None:
    """A isenção não tem prazo, e esta asserção é o único vencimento que ela tem.

    Duas formas de morrer: o termo saiu daquele arquivo, ou saiu **em parte** — a
    contagem caiu. A segunda importa tanto quanto a primeira: uma contagem alta
    demais é orçamento sobrando, e orçamento sobrando é exatamente a carona que o
    campo de contagem existe para fechar.
    """
    grouped = _counted(findings())

    obsolete: list[str] = []
    for exemption in sorted(read_allowlist(), key=lambda item: item.line):
        occurrences = grouped.get(exemption.key, [])
        label = f"{ALLOWLIST.name}:{exemption.line} " + "::".join(exemption.key)
        if not occurrences:
            obsolete.append(f"{label}: o termo não aparece mais ali")
        elif len(occurrences) < exemption.count:
            obsolete.append(
                f"{label}: são {len(occurrences)} ocorrências, e a linha isenta "
                f"{exemption.count}"
            )

    assert obsolete == [], (
        "estas linhas da allowlist deixaram de descrever o repositório:\n  "
        + "\n  ".join(obsolete)
        + "\nApague-as ou baixe a contagem. A isenção não tem `review_by` de "
        "propósito — dívida de vocabulário não caduca por calendário, ela some "
        "quando o termo sai do código (ADR 0063, ADR 0054)."
    )


def test_every_rule_bans_in_the_name_of_a_term_the_map_knows() -> None:
    """A guarda não pode banir em nome de um termo que o documento normativo não tem.

    Duas metades, e a primeira é a que importa: **nenhuma regra pode ficar sem
    termo**. Se alguém reformatar as tabelas do `language-map.md` e o casador parar
    de casar, as sete regras passariam a não banir nada e a suíte ficaria verde — o
    `dependency-review` da ADR 0023 outra vez. A segunda metade pega a direção
    inversa: um termo digitado à mão dentro da guarda, que o mapa não conhece.
    """
    text = _map_text()
    empty = [rule for rule, terms in rule_terms().items() if not terms]
    assert empty == [], (
        "estas regras não derivaram termo nenhum do Language Map: "
        + ", ".join(empty)
        + ". Uma regra sem termo não bane nada e não reprova nada — o documento mudou "
        "de forma, e a decisão é de quem o mudou."
    )

    unknown = [
        f"{rule}: {term}"
        for rule, terms in sorted(rule_terms().items())
        for term in terms
        if term.lower() not in text.lower()
    ]
    assert unknown == [], (
        "estes termos são banidos por uma regra e não aparecem no Language Map:\n  "
        + "\n  ".join(unknown)
        + f"\nO termo entra primeiro em `{LANGUAGE_MAP.relative_to(REPO_ROOT)}` "
        "(§8, regra de manutenção), depois vira portão."
    )


def test_every_banned_row_of_the_map_is_claimed_or_excluded_with_a_reason() -> None:
    """Bidirecional, no precedente da guarda de eventos da ADR 0034.

    As duas direções já falharam neste repositório em outros arquivos: runbook
    nomeando evento que ninguém emitia, e doze eventos emitidos que runbook nenhum
    conhecia. Aqui: linha da §5 que nenhuma regra cobre e nenhuma exclusão explica
    reprova, e exclusão que sobreviveu à linha reprova também.
    """
    rows = {row[0] for row in banned_table()}
    claimed = {claim for claims in CLAIMS.values() for claim in claims}

    orphan_rows = sorted(rows - claimed - set(UNLINTABLE))
    assert orphan_rows == [], (
        "estas linhas da §5 do Language Map não têm regra nem exclusão escrita:\n  "
        + "\n  ".join(orphan_rows)
        + "\nEscreva a regra, ou a razão de ela não ser lintável aqui, em `UNLINTABLE`."
    )

    orphan_claims = sorted((claimed | set(UNLINTABLE)) - rows)
    assert orphan_claims == [], (
        "estas entradas apontam para uma linha que a §5 não tem mais:\n  "
        + "\n  ".join(orphan_claims)
        + "\nO documento mudou. Decida o que a regra passa a fazer — não reescreva o "
        "casador para o vermelho sumir."
    )


# --- as amostras que fazem cada ramo ser percorrido -------------------------
#
# A lição do `_TEMPLATE_SAMPLE` (ADR 0038): **a cobertura de um portão é a dos ramos
# que a amostra percorre**. Seis das sete regras nascem verdes sobre o repositório,
# então sem amostra elas seriam código que nada executa. A sétima nasceu **vermelha**
# nas quatro linhas da tela e ficou verde quando elas ganharam o rótulo — o que a
# devolve à mesma condição das outras. Cada caso traz o par completo — o que reprova
# e o quase-acerto que passa —, porque só o par prova que a regra é estreita.

_TS_COMPONENT = '"use client";\n\nexport default function FunnelClient() {\n  %s\n  return null;\n}\n'


def _web_findings(name: str, text: str) -> list[Finding]:
    source = Source(name, text)
    exempt = default_client_component(source)
    stripped = strip_typescript(text)
    found: list[Finding] = []
    for declaration in web_declarations(source):
        for finding in (
            find_opportunity(declaration),
            find_client(declaration, exempt),
            find_gate_outcome(declaration),
        ):
            if finding is not None:
                found.append(finding)
    for line, snippet in list(stripped.literals) + list(stripped.jsx):
        found.extend(find_phrases(name, line, snippet))
        bare = find_bare_roi(name, line, snippet)
        if bare is not None:
            found.append(bare)
    return found


def _python_findings(name: str, text: str) -> list[Finding]:
    source = Source(name, text)
    found: list[Finding] = []
    for declaration in python_declarations(source):
        for finding in (
            find_opportunity(declaration),
            find_client(declaration, None),
            find_gate_outcome(declaration),
            find_portuguese_model(declaration),
        ):
            if finding is not None:
                found.append(finding)
    for line, snippet in python_visible_text(source):
        found.extend(find_phrases(name, line, snippet))
        bare = find_bare_roi(name, line, snippet)
        if bare is not None:
            found.append(bare)
    return found


def test_the_opportunity_rule_catches_the_bare_word_and_lets_the_named_labels_through() -> None:
    core = "apps/api/src/portal_api/schemas.py"
    caught = _python_findings(core, "class OpportunityOut:\n    score: int\n")
    assert [finding.rule for finding in caught] == [R1]

    for green in (
        "class CommercialOpportunityOut:\n    pass\n",
        "class ImprovementOpportunityOut:\n    pass\n",
        # Os três rótulos de entregável que a §5 nomeia como únicas exceções.
        "OPPORTUNITY_SCORE = 1\n",
        "OPPORTUNITY_MAP = {}\n",
        "IMPROVEMENT_OPPORTUNITY_BACKLOG = []\n",
    ):
        assert _python_findings(core, green) == [], green


def test_the_client_exemption_is_by_identifier_and_not_by_file() -> None:
    """A armadilha, medida como asserção.

    `stuckOnClient` mora **dentro** de `FunnelClient.tsx`. A isenção por arquivo o
    perdoaria junto; a isenção por identificador não. As duas linhas abaixo são a
    mesma medição que a tabela de mutações da ADR registra.
    """
    path = "app/admin/funnel/FunnelClient.tsx"

    # O componente é isento: o nome é o `export default function` e o basename.
    assert _web_findings(path, _TS_COMPONENT % "const rows = [];") == []

    # Um vizinho no mesmo arquivo, não.
    caught = _web_findings(path, _TS_COMPONENT % "const clientRows = [];")
    assert [(finding.rule, finding.identifier) for finding in caught] == [
        (R2, "clientRows")
    ]

    # E a isenção não vale para um módulo que só *se chama* assim: sem `"use client"`
    # o nome não é um React Client Component, e sem o casamento com o basename
    # tampouco.
    assert _web_findings(
        path, "export default function FunnelClient() { return null; }\n"
    ), "sem `use client` o nome deixa de ser vocabulário do React"
    assert _web_findings(
        path, '"use client";\nexport default function ClientPanel() { return null; }\n'
    ), "o nome que não é o basename não é o componente que o módulo publica"


def test_the_gate_rule_is_narrow_enough_to_leave_the_event_outcome_alone() -> None:
    core = "apps/api/src/portal_api/models/project.py"
    caught = _python_findings(core, "class GateOutcome:\n    pass\n")
    assert [finding.rule for finding in caught] == [R3]
    assert [finding.rule for finding in _python_findings(core, "gate_outcome = 1\n")] == [R3]

    # Os dois legítimos: resultado do evento, não decisão de gate.
    assert _python_findings(core, "class AgentEventOutcome:\n    outcome: str\n") == []


def test_the_portuguese_rule_covers_the_named_names_and_the_accent() -> None:
    core = "apps/api/src/portal_api/models/process.py"
    for red in ("class Evidencia:\n    pass\n", "class ProcessoEtapa:\n    pass\n"):
        assert [finding.rule for finding in _python_findings(core, red)] == [R4], red

    # O sinal estrutural: letra fora do ASCII num nome de classe.
    assert [finding.rule for finding in _python_findings(core, "class Reunião:\n    pass\n")] == [R4]

    for green in ("class Evidence:\n    pass\n", "class ProcessStep:\n    pass\n"):
        assert _python_findings(core, green) == [], green

    # E o alcance é o núcleo: uma classe de mesmo nome fora dele não é batismo de modelo.
    assert _python_findings(
        "apps/api/src/portal_api/worker.py", "class Evidencia:\n    pass\n"
    ) == []


def test_the_product_name_rule_reads_visible_text_and_not_comments() -> None:
    path = "app/DashboardClient.tsx"
    assert [f.rule for f in _web_findings(path, "const t = <p>o portal do cliente</p>;")] == [R5]
    assert [f.rule for f in _web_findings(path, 'const t = "Cockpit";')] == [R5]
    assert [f.rule for f in _web_findings(path, 'const t = "o CRM da Biahflow";')] == [R5]
    assert _web_findings(path, "const t = <p>o One</p>;") == []

    # O comentário sai por construção — é o que mantém a nota histórica fora do alcance.
    assert _web_findings(path, "// o Cockpit era o nome antigo\nconst t = 1;") == []
    assert _web_findings(path, "/* portal do cliente */\nconst t = 1;") == []


def test_the_prove_rule_covers_the_three_terms_and_skips_the_docstring() -> None:
    path = "app/DashboardClient.tsx"
    for red in ("<p>o piloto entrou no ar</p>", '"POC"', '"MVP"'):
        assert [f.rule for f in _web_findings(path, f"const t = {red};")] == [R6], red

    assert _web_findings(path, "const t = <p>o PROVE entrou no ar</p>;") == []
    assert _web_findings(path, 'const t = "pocket";') == [], "`POC` não casa dentro de palavra"

    # Na API, a mesma frase num docstring é prosa histórica e não texto de tela —
    # `models/meeting.py` tem uma, e sem o recorte a regra nasceria vermelha nela.
    core = "apps/api/src/portal_api/models/meeting.py"
    assert _python_findings(core, '"""transcription is out of the MVP."""\n') == []
    assert [f.rule for f in _python_findings(core, 'TITLE = "MVP"\n')] == [R6]


def test_the_roi_rule_demands_the_qualifier_and_names_which_roi_it_is() -> None:
    """O par completo, e o segundo par é o que carrega a fatia: a isenção é por
    **superfície**, não pelo literal.

    O termo e o primeiro qualificador saem da §5 (célula do termo e célula "Por quê");
    o segundo é decisão local com a razão em `LOCAL_QUALIFIERS`.
    """
    assert roi_term() == "ROI"
    assert roi_qualifiers()[0] == "projetado", "o qualificador sai da §5, não daqui"
    assert all(len(reason) >= 40 for reason in LOCAL_QUALIFIERS.values()), (
        "um qualificador que não sai do mapa precisa da razão escrita ao lado"
    )
    assert all(len(reason) >= 40 for reason in INTERNAL_SURFACES.values()), (
        "uma superfície excluída precisa da razão escrita ao lado"
    )

    path = "app/DashboardClient.tsx"
    # A primeira é a manchete, e ela é também a medição do radical: com o corte no
    # sufixo inteiro do particípio (`projet`), a palavra "projeto" a qualificaria e
    # esta linha nasceria verde. Ver `_stem`.
    for red in ("<p>ROI do projeto</p>", '"ROI/mês"', '"Fórmula do ROI"'):
        assert [f.rule for f in _web_findings(path, f"const t = {red};")] == [R7], red

    for green in (
        '"ROI projetado"',
        '"ROI apurado"',
        '"Fórmula do ROI apurado"',
        '"ROI projetado/mês"',
        # A flexão, que é a razão de o casamento ser por radical.
        '"as duas linhas de ROI apuradas"',
        # Sem o token não há o que rotular: a frase já é sobre a ausência do número.
        '"Sem projeção no Biahflow"',
    ):
        assert _web_findings(path, f"const t = {green};") == [], green

    # A estreiteza é deliberada, e é a mesma do `R6`: sigla casa com distinção de
    # caixa, e `\b` a impede de casar dentro de palavra.
    assert _web_findings(path, 'const t = "o roi do mês";') == []
    assert _web_findings(path, 'const t = "dois ROIs";') == []

    # O par que carrega a fatia: o **mesmo literal** reprova na tela do cliente e
    # passa na tela do time. A isenção por superfície não é sobre o texto.
    literal = 'const t = "premissas de ROI";'
    assert _web_findings("app/admin/MembersClient.tsx", literal) == []
    assert [f.rule for f in _web_findings(path, literal)] == [R7]

    # E o mesmo par do lado Python, onde a exclusão é um arquivo e não um diretório.
    frase = 'AVISO = "Há ROI no dashboard e o cliente não voltou para vê-lo."\n'
    assert _python_findings("apps/api/src/portal_api/onboarding.py", frase) == []
    assert [
        f.rule for f in _python_findings("apps/api/src/portal_api/results.py", frase)
    ] == [R7]
