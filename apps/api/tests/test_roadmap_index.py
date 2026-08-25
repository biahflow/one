"""O índice canônico e as decisões que ele não conhecia (ADR 0054).

O `AGENTS.md` chama o `ROADMAP.md` de "índice canônico de descoberta de trabalho",
e entre 07 e 13/08/2026 dez ADRs foram aceitas sem que ele soubesse de nenhuma —
a implantação inteira na nuvem, da 0044 à 0053. O conserto foi à mão, junto de uma
regra escrita no `AGENTS.md` mandando atualizar o arquivo no mesmo commit. É
exatamente a forma da ADR 0034: lá o `alerts.md` foi corrigido à mão, ficou sem
portão, e **em dois dias divergiu de novo pelo outro lado**. Esta guarda é o portão
que faltou.

Medido com o predicado deste arquivo, e os números importam por motivos diferentes:

- contra `git show HEAD:ROADMAP.md` (o estado pré-conserto, com o corpus de 53 ADRs
  daquele momento): **14** aceitas sem citação — 1, 2, 3, 4, 5, 44, 45, 46, 47, 48,
  50, 51, 52, 53. É o vermelho de nascença sobre o defeito literal, e não sobre um
  caso construído: dez das catorze são a implantação;
- contra o `ROADMAP.md` do disco, antes de a ADR 0003 ganhar citação na Fase 1:
  **5**; depois: **4**, idênticas à allowlist abaixo.

**Duas formas de citação, e a segunda foi paga em allowlist antes de ser reconhecida.**
A primeira versão desta guarda lia só a forma em prosa (`ADR 0009`) e isentava a ADR
0009 por uma linha de allowlist com motivo bem escrito — motivo **falso**: o roadmap
tem a seção "Migração do runtime web (04/08/2026)" inteira sobre aquela decisão e
aponta para `docs/adr/0009` desde antes desta fatia. Allowlist onde bastava
reconhecer a citação é sedimento (ADR 0029). Com a forma de caminho no casador a
medida de `HEAD` cai de 15 para **14** e a do disco de 5 para **4**, e a asserção de
obsolescência prova sozinha que a entrada morreu: devolvendo o `9` à lista, ela acusa
*"ADR 0009: o roadmap passou a citá-la"*.

E o casamento **apertado** é medido, não deduzido: trocando as duas formas por quatro
dígitos em qualquer lugar, as faltantes caem de **4 para 1** — sobra só a ADR 0001.
Somem 0002, 0004 e 0005, comidas pelos tokens nus de migração Alembic que o arquivo
cita entre crases (`0002`, `0004`, `0005`, ao lado de `0003_journey_and_roi` e
`0006_portal_sync_fields`). Contra `HEAD` a mesma troca leva 14 a **11**, somindo
0003, 0004 e 0005. Três das quatro isenções desta guarda desapareceriam sem que
ninguém as tivesse decidido: é o `.priority` da ADR 0033 outra vez, a guarda frouxa
nascendo verde sobre o defeito que ela existe para pegar.

A cláusula que separa a ADR 0003 daqui da ADR 0003 do `biahflow-portal` mede-se
contra `HEAD`, e não contra o texto de hoje: no texto de hoje a ADR 0003 já é citada
de verdade, na Fase 1, e devolver uma menção *cross-repo* à forma nua não moveria
nada. Contra `HEAD` move: as faltantes caem de 14 para **13**, e a ADR 0003 sai da
lista **pelo motivo errado**. E ela continua indispensável pela direção inversa, também
medido: `ADR 0060 de lá` acrescentado ao texto não pendura nada, e `ADR 0060` nu
pendura `{60}`, cobrando deste repositório um arquivo que ele não tem por que ter.

A cláusula foi ainda medida contra si mesma, e a primeira versão reprovou: o roadmap
escreve `ADR 0003 **do `biahflow-portal`**`, e aceitar só espaço entre o número e o
"do" fazia os asteriscos de ênfase quebrarem o casamento.

**E o número de cada decisão passou a ser alocado aqui do lado (ADR 0072).** As
asserções sobre o `ROADMAP.md` perguntam se o índice conhece a decisão; as do fim
deste arquivo perguntam se o **número** dela foi reivindicado num ponto de
coordenação — `docs/adr/number-registry.tsv`, um arquivo ordenado a que toda ADR
acrescenta uma linha no fim, de modo que duas branches concorrentes conflitem no
git. `test_no_two_adr_files_share_the_same_number` fica onde está e continua sendo
o backstop: ela detecta a colisão depois de ela existir, e detecção não fecha
corrida.

Nenhuma asserção aqui precisa de banco: são sobre arquivos. E os auxiliares recebem
`text: str`, nunca `Path` — só as funções `test_*` abrem arquivo —, que é o que
permitiu medir contra `HEAD` sem tocar no working tree.
"""

from __future__ import annotations

import os
import re
from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ROADMAP = REPO_ROOT / "ROADMAP.md"
ADR_DIR = REPO_ROOT / "docs" / "adr"
ADR_GLOB = "[0-9][0-9][0-9][0-9]-*.md"

#: Só a **primeira palavra** depois de `**Status:**`. A data que vem depois aparece
#: em quatro formatos neste diretório (ausente, `— 04/08/2026`, `**Data:**` em linha
#: própria, e as variações de travessão), e ler só a palavra dispensa conhecê-los.
_STATUS = re.compile(r"^\*\*Status:\*\*\s*(\w+)", re.MULTILINE)

_ACCEPTED = {"aceito", "aceita"}

#: **Sem ocupante hoje**, e é de propósito: existe para que a primeira ADR recusada
#: não caia num `else` silencioso. Uma palavra fora dos dois vocabulários reprova em
#: `test_every_adr_status_is_a_word_this_guard_knows`.
_NOT_ACCEPTED = {
    "rejeitado",
    "rejeitada",
    "revogado",
    "revogada",
    "substituído",
    "substituída",
    "obsoleto",
    "obsoleta",
    "proposto",
    "proposta",
}

#: A citação em prosa, nas quatro formas que o arquivo de fato usa: `ADR 0044`,
#: `ADRs 0042 e 0043`, `ADR 0006/0008` e `ADR 0010/0011/0012`. O prefixo `ADR`/`ADRs`
#: é **obrigatório**, e isso é o que separa esta guarda de um falso verde — ver o
#: docstring do módulo. A outra forma é `_PATH_CITATION`, logo abaixo.
#: Uma faixa (`ADRs 0044 a 0053`) deliberadamente **não** casa: o que a regra do
#: `AGENTS.md` pede é uma linha por decisão, não um parágrafo dizendo que elas
#: existem.
_CITATION = re.compile(r"\bADRs?\s+(\d{4}(?:\s*/\s*\d{4}|,?\s+e\s+\d{4})*)")

_FOUR_DIGITS = re.compile(r"\d{4}")

#: A segunda forma que o arquivo usa, duas vezes e desde antes desta fatia:
#: ``Ver `docs/adr/0009` `` e ``Ver também `docs/adr/0008` ``. É citação, e **mais
#: apertada** que a forma em prosa — não há como um nome de migração Alembic se
#: disfarçar atrás de um caminho. O slug e a extensão não entram no casador porque
#: nada depende deles; um link markdown `[…](docs/adr/0009-...md)` casa igual.
#:
#: Não passa pela cláusula `_ELSEWHERE`, e não por descuido: um caminho
#: `docs/adr/NNNN` é um ponteiro para **este** repositório, e a ADR do outro só é
#: citável em prosa. Em compensação a direção inversa passa a cobrar que o caminho
#: resolva para arquivo existente, que é ganho e não custo.
_PATH_CITATION = re.compile(r"docs/adr/(\d{4})")

#: `mais emenda na ADR 0003 de lá` e ``mais emenda na ADR 0003 do `biahflow-portal` ``
#: eram, antes desta fatia, as **duas únicas** ocorrências de "ADR 0003" no arquivo,
#: e as duas apontam para o outro repositório. Sem esta cláusula a ADR 0003 local —
#: Identidade — passaria por citada por um documento que não é dela, e o item da
#: Fase 1 que **é** aquela decisão continuaria sem citá-la.
#:
#: O casamento é por **posição no texto** (`_ELSEWHERE.match(text, match.end())`) e
#: não sobre uma fatia de N caracteres, porque o markdown quebra a linha no meio das
#: duas ocorrências (`ADR 0003 de\n      lá.`).
#:
#: `[\s*]*` engole os marcadores de ênfase, e isso foi medido: a linha que esta
#: própria fatia escreveu no roadmap diz `ADR 0003 **do `biahflow-portal`**`, e a
#: primeira versão da cláusula — que só aceitava espaço — a lia como citação da ADR
#: 0003 **local**, dando a medição como 5 onde ela é 6.
_ELSEWHERE = re.compile(
    r"[\s*]*(?:de\s+l[áa]\b|d[oe]\s+[\s*`\"]*biahflow-portal)",
    re.IGNORECASE,
)

# Ao contrário do `test_agents_rules.py` e da guarda de eventos do
# `test_telemetry.py`, aqui **não** há `_HISTORICAL_NOTE`. No `alerts.md` a nota
# histórica é instrução que deixou de valer, e lê-la como instrução faria a guarda
# cobrar o que o repositório corrigiu. Aqui o texto do roadmap é **conhecimento**:
# uma ADR citada dentro de "*Fechados, para não serem reabertos por leitura de
# ADR:*" continua sendo o índice sabendo dela, que é a única coisa que esta guarda
# pergunta.

#: Decisões de fundação que o roadmap não cita, em nenhuma das duas formas.
#:
#: Quatro entradas, e a quinta que houve aqui é a razão de o casador ter duas
#: formas: a ADR 0009 estava nesta lista com um motivo bem escrito, e o motivo era
#: falso — o roadmap **conhece** aquela decisão, tem a seção "Migração do runtime
#: web (04/08/2026)" inteira sobre ela e aponta para `docs/adr/0009` desde antes
#: desta fatia. Allowlist onde bastava reconhecer a citação é sedimento (ADR 0029),
#: e a resposta certa não era o motivo, era o predicado.
#:
#: O motivo é **contestável de propósito** e descreve aquela decisão: quem discordar
#: escreve a linha no roadmap, e aí
#: `test_the_roadmap_allowlist_does_not_keep_a_line_that_stopped_being_needed`
#: cobra a remoção da entrada. **Sem `review_by`**, ao contrário do
#: `docs/security/advisories.json` (ADR 0023): decisão de fundação não caduca por
#: prazo — o vencimento dela é a asserção de obsolescência.
FOUNDATION_WITHOUT_A_LINE: dict[int, str] = {
    1: "Monorepo e stack: Next.js + FastAPI + Postgres/pgvector + Redis/Celery + "
    "MinIO. É a forma do repositório, não um item de entrega — a seção "
    "'Fundação local' descreve o compose que ela produziu, e cada fase abaixo "
    "só existe dentro dessa escolha.",
    2: "Isolamento multitenant: organização e projeto em todo registro, "
    "autorização na API e RLS como segunda barreira. Não tem linha porque é o "
    "**aceite** da Fase 1 e de toda fase seguinte, e não um trabalho que se "
    "conclui — a ADR 0010, que a implementa por transação, essa sim tem linha.",
    4: "RAG e contexto: chunk com organização, projeto, fonte e localização, e "
    "resposta que exige fonte. É o princípio 3 do `AGENTS.md` na forma de "
    "decisão de arquitetura; quem tem linha é a ADR 0014, que construiu o "
    "índice, e a ADR 0038, que datou a citação.",
    5: "Jobs assíncronos em Celery/Redis, idempotentes e carregando tenant. A "
    "linha da Fase 4 é sobre o `beat` que faltava (ADR 0016), e a ADR 0045 é "
    "sobre onde o worker roda — a decisão de haver fila é anterior às duas e "
    "não é entregável de nenhuma.",
}


def _adr_number(name: str) -> int:
    """O número que o nome do arquivo declara.

    Mora numa função porque **duas** asserções dependem dele e precisam concordar:
    `_adrs()`, que chaveia o corpus por número, e
    `test_no_two_adr_files_share_the_same_number`, que existe justamente para achar
    dois arquivos que produzam a mesma chave. Se as duas extraíssem o número cada uma
    por conta própria, uma divergência entre elas deixaria a segunda cega para
    exatamente o caso que ela procura — e nada ficaria vermelho.
    """
    return int(name.split("-", 1)[0])


def _adrs(files: dict[str, str]) -> dict[int, str]:
    """Número da ADR → a palavra de status, em minúsculas.

    **Fail-closed, e este é o ponto mais importante do arquivo:** ausência de linha
    `**Status:**` devolve `""`, e `""` conta como aceita. Um predicado
    `status == "aceito"` encolheria o corpus em **três ADRs, em silêncio** (das 53
    de então sobrariam 50), porque `0021`, `0022` e `0023` não têm essa linha (o
    cabeçalho delas é
    `Data: 2026-08-05 · Fase 5 · FDD 015`) — que é a ADR 0033 cometida dentro da
    guarda que a cita. Só uma palavra do vocabulário de recusa isenta uma ADR.

    Consertar aqueles três cabeçalhos ficou fora do recorte de propósito: o desenho
    fail-closed já os cobre, e uma asserção "toda ADR tem linha de status" nasceria
    vermelha com três ADRs por motivo alheio a esta guarda.
    """
    statuses: dict[int, str] = {}
    for name, text in files.items():
        found = _STATUS.search(text)
        statuses[_adr_number(name)] = found.group(1).lower() if found else ""
    return statuses


def _accepted(statuses: dict[int, str]) -> set[int]:
    """As ADRs que valem como aceitas — tudo que não foi recusado por escrito."""
    return {number for number, word in statuses.items() if word not in _NOT_ACCEPTED}


def _adrs_the_roadmap_knows(text: str) -> set[int]:
    """Os números de ADR **deste** repositório que o texto cita."""
    known = {int(number) for number in _PATH_CITATION.findall(text)}
    for match in _CITATION.finditer(text):
        if _ELSEWHERE.match(text, match.end()):
            continue
        known.update(int(number) for number in _FOUR_DIGITS.findall(match.group(1)))
    return known


def _read_adrs() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(ADR_DIR.glob(ADR_GLOB))
    }


def test_every_accepted_adr_has_a_line_in_the_roadmap() -> None:
    """Uma ADR aceita que o índice canônico não conhece é estado sem dono.

    Nasceu vermelha com **catorze** contra `HEAD` — dez delas a implantação na nuvem
    inteira, aceita entre 07 e 13/08/2026 sem que este arquivo soubesse.
    """
    statuses = _adrs(_read_adrs())
    cited = _adrs_the_roadmap_knows(ROADMAP.read_text(encoding="utf-8"))

    missing = sorted(_accepted(statuses) - cited - set(FOUNDATION_WITHOUT_A_LINE))

    assert missing == [], (
        "estas ADRs foram aceitas e o `ROADMAP.md` não as conhece: "
        + ", ".join(f"ADR {number:04d}" for number in missing)
        + ". Escreva a linha no mesmo commit da fatia, ou declare em"
        " `FOUNDATION_WITHOUT_A_LINE` por que aquela decisão não mudou estado"
        " publicado. O roadmap é o índice canônico de descoberta (`AGENTS.md`);"
        " decisão que ele não indexa é estado sem dono, e foi assim que dez"
        " ficaram de fora entre 07 e 13/08/2026 (ADR 0054)."
    )


def test_every_adr_the_roadmap_cites_exists() -> None:
    """A direção inversa: o roadmap não aponta para uma ADR que não existe.

    **Nasce verde**, e pela ADR 0033 verde de nascença não prova nada — então foi
    medida por duas vias, uma por forma de citação: trocando `ADR 0053` por
    `ADR 0099` ela acusa `{99}`, e acrescentando um ``Ver `docs/adr/0098` `` ela acusa
    `{98}` — esta segunda é ganho da forma de caminho, porque um link para ADR que não
    existe passa a reprovar. Existe pelo precedente da ADR 0034, onde as duas direções já falharam em
    documentos diferentes: o runbook nomeava um evento que ninguém emitia, e doze
    emitidos não tinham runbook. Reusa `_adrs_the_roadmap_knows` **inteiro**, que é
    o que impede as duas direções de divergirem sobre o que é uma citação.
    """
    existing = set(_adrs(_read_adrs()))
    cited = _adrs_the_roadmap_knows(ROADMAP.read_text(encoding="utf-8"))

    dangling = sorted(cited - existing)

    assert dangling == [], (
        "o `ROADMAP.md` cita ADRs que não existem em `docs/adr/`: "
        + ", ".join(f"ADR {number:04d}" for number in dangling)
        + ". Corrija o número — e se a decisão é do outro repositório, escreva-o"
        " ('de lá', ou o nome do repo), que é como as duas citações da ADR 0003"
        " do `biahflow-portal` se distinguem da ADR 0003 daqui (ADR 0054)."
    )


def test_no_two_adr_files_share_the_same_number() -> None:
    """Duas ADRs com o mesmo número são uma decisão que a outra apaga em silêncio.

    `_adrs()` chaveia por `_adr_number()`: um número repetido faz o
    arquivo que ordena depois sobrescrever o que ordena antes dentro do dicionário,
    e as duas podem dizer `aceito` sem que `test_every_accepted_adr_has_a_line_in_the_roadmap`
    veja a duplicata — ela só enxerga o número, nunca o nome do arquivo. Foi
    exatamente isto que aconteceu com `0067-one-como-projecao-client-facing.md` e
    `0067-a-flag-que-o-casador-nao-conhecia.md`: duas decisões, um número, e a guarda
    de índice passava verde por cima da colisão (ADR 0054). Esta asserção lê o
    corpus de `_read_adrs()` **antes** de `_adrs()` perder a informação, e é onde ela
    tem de morar: um segundo casador sobre o mesmo dicionário divergiria da forma
    que `_adrs()` já usa para extrair o número.

    Fail-closed: corpus vazio reprova, na mesma forma que o `dependency-review` da
    ADR 0023 — verde por não ter conseguido olhar não é verde.
    """
    files = _read_adrs()
    assert files, (
        "nenhum arquivo de ADR foi encontrado em `docs/adr/` — o glob quebrou, e"
        " uma guarda que não olha nada não pode dizer que está tudo certo."
    )

    by_number: dict[int, list[str]] = {}
    for name in files:
        by_number.setdefault(_adr_number(name), []).append(name)

    duplicated = {
        number: sorted(names) for number, names in by_number.items() if len(names) > 1
    }

    assert duplicated == {}, (
        "estes números de ADR têm mais de um arquivo em `docs/adr/`, e o que ordena"
        " depois sobrescreve o outro em silêncio dentro de `_adrs()`: "
        + "; ".join(
            f"ADR {number:04d}: {' e '.join(names)}"
            for number, names in sorted(duplicated.items())
        )
        + ". Renumere um dos dois arquivos para o próximo número livre — `git mv` mais"
        " a linha 1 do arquivo — e atualize toda citação dele no repositório e no"
        " `ROADMAP.md` (ADR 0054)."
    )


def test_every_adr_status_is_a_word_this_guard_knows() -> None:
    """Um status fora dos dois vocabulários reprova, em vez de virar 'aceita'.

    O fail-closed de `_adrs` é o que mantém `0021`, `0022` e `0023` no corpus; sem
    esta asserção ele também engoliria um `**Status:** superseded` — e a ADR
    silenciosamente voltaria a ser cobrada, ou deixaria de ser, sem ninguém decidir.
    """
    unknown = {
        f"ADR {number:04d}: {word!r}"
        for number, word in _adrs(_read_adrs()).items()
        if word and word not in _ACCEPTED and word not in _NOT_ACCEPTED
    }

    assert unknown == set(), (
        "estas ADRs declaram um status que esta guarda não sabe ler: "
        + ", ".join(sorted(unknown))
        + ". Acrescente a palavra a `_ACCEPTED` ou a `_NOT_ACCEPTED` — decidindo,"
        " no ato, se uma ADR nesse estado ainda precisa de linha no roadmap"
        " (ADR 0054)."
    )


def test_the_roadmap_allowlist_does_not_keep_a_line_that_stopped_being_needed() -> None:
    """Entrada de allowlist tem três formas de morrer, e todas reprovam aqui.

    A ADR ganhou linha no roadmap, foi recusada por escrito, ou o arquivo dela sumiu.
    O precedente é o `_CANNOT_ANSWER_404` do `test_authorization.py` e o `stale` do
    `scripts/audit.mjs`: uma allowlist que só cresce deixa de descrever o
    repositório, e uma entrada obsoleta é uma isenção que ninguém decidiu manter.
    """
    statuses = _adrs(_read_adrs())
    cited = _adrs_the_roadmap_knows(ROADMAP.read_text(encoding="utf-8"))

    obsolete: list[str] = []
    for number in sorted(FOUNDATION_WITHOUT_A_LINE):
        if number in cited:
            obsolete.append(f"ADR {number:04d}: o roadmap passou a citá-la")
        elif number not in statuses:
            obsolete.append(f"ADR {number:04d}: não há arquivo em `docs/adr/`")
        elif statuses[number] in _NOT_ACCEPTED:
            obsolete.append(
                f"ADR {number:04d}: está `{statuses[number]}`, e a guarda já não a cobra"
            )

    assert obsolete == [], (
        "estas linhas de `FOUNDATION_WITHOUT_A_LINE` deixaram de ser necessárias: "
        + "; ".join(obsolete)
        + ". Apague-as — a isenção que sobrevive ao motivo é a lista escrita à mão"
        " que a ADR 0033 descreve (ADR 0054)."
    )


# --- o registro de números (ADR 0072) ---------------------------------------
#
# As asserções acima são sobre o **índice** conhecer as decisões. As de baixo são
# sobre o **número** de cada decisão ser alocado num ponto de coordenação, em vez
# de escolhido à mão quando a branch nasce e reivindicado só no merge — janela em
# que duas branches levam o mesmo número, o que aconteceu três vezes em 25/08/2026.
#
# `test_no_two_adr_files_share_the_same_number` continua acima e continua sendo o
# backstop: ela **detecta** a colisão. Detecção não fecha corrida — o número livre
# de dez minutos atrás não é o número livre de agora —, e quem a fecha é o arquivo
# ordenado a que toda ADR acrescenta uma linha no fim, no mecanismo do `schema.rb`
# do Rails e do `max_migration.txt` do django-linear-migrations: dois appends na
# mesma posição conflitam no git, e o conflito é a coordenação.

REGISTRY = ADR_DIR / "number-registry.tsv"

#: Uma linha do registro: quatro dígitos, TAB, slug em kebab-case. O casador é
#: **apertado** de propósito, e o TAB literal é parte disso: uma linha com espaços
#: no lugar do TAB não vira "linha quase certa que a guarda deixa passar", vira
#: linha malformada — e malformada reprova, em vez de sumir do corpus em silêncio,
#: que seria a guarda ficando verde por não ter conseguido ler (ADR 0023).
_REGISTRY_LINE = re.compile(r"^(\d{4})\t([a-z0-9]+(?:-[a-z0-9]+)*)$")


def _adr_slug(name: str) -> str:
    """O slug que o nome do arquivo declara — `0071-a-flag-….md` → `a-flag-…`.

    Par de `_adr_number()`, e mora aqui pelo mesmo motivo: duas asserções
    dependem dele e precisam concordar sobre onde o número acaba e o slug começa.
    """
    return name.split("-", 1)[1].removesuffix(".md")


def _registry(text: str) -> tuple[list[tuple[int, str]], list[str]]:
    """As linhas do registro **na ordem em que estão**, mais as malformadas.

    A ordem é devolvida como lista, e não como dicionário, porque duas das
    asserções são sobre ela: ordenação crescente e ausência de número repetido.
    Um dicionário perderia as duas — é exatamente o que `_adrs()` faz com o
    corpus de arquivos, e é a razão de existir
    `test_no_two_adr_files_share_the_same_number`.

    Comentário (`#`) e linha em branco são ignorados; **qualquer outra coisa** que
    não case `_REGISTRY_LINE` volta na segunda lista para reprovar por nome.
    """
    rows: list[tuple[int, str]] = []
    malformed: list[str] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        found = _REGISTRY_LINE.match(line)
        if found is None:
            malformed.append(line)
            continue
        rows.append((int(found.group(1)), found.group(2)))
    return rows, malformed


def _read_registry() -> tuple[list[tuple[int, str]], list[str]]:
    assert REGISTRY.is_file(), (
        f"`{REGISTRY.relative_to(REPO_ROOT).as_posix()}` não existe, e é ele que"
        " aloca o número de toda ADR nova (ADR 0072). Sem o arquivo não há ponto"
        " de coordenação: o número volta a ser escolhido à mão e duas branches"
        " voltam a levar o mesmo — restaure-o, não o contorne."
    )
    rows, malformed = _registry(REGISTRY.read_text(encoding="utf-8"))
    assert malformed == [], (
        "estas linhas do registro de números não têm a forma `NNNN<TAB>slug`: "
        + "; ".join(repr(line) for line in malformed)
        + ". O separador é um TAB literal e o slug é kebab-case; uma linha que a"
        " guarda não sabe ler sairia do corpus em silêncio, que é o verde por não"
        " ter conseguido olhar (ADR 0072)."
    )
    assert rows, (
        "o registro de números está vazio — nenhuma linha `NNNN<TAB>slug` em"
        f" `{REGISTRY.relative_to(REPO_ROOT).as_posix()}`. Ele é o corpus das duas"
        " direções abaixo, e um corpus vazio faria as duas passarem sem afirmar"
        " nada (ADR 0072)."
    )
    return rows, malformed


def test_the_adr_number_registry_is_ordered_and_claims_each_number_once() -> None:
    """O registro é ordenado e não repete número.

    Ordenado porque a alocação é um **append no fim**: uma linha fora de ordem
    significa que alguém escreveu no meio do arquivo, e escrever no meio é
    justamente o que devolve ao git a chance de auto-mesclar dois appends sem
    conflito — a coordenação evaporaria sem nada ficar vermelho. Número repetido
    é a colisão que a fatia inteira existe para não deixar acontecer, vista do
    lado do registro em vez do lado dos arquivos.
    """
    rows, _ = _read_registry()
    numbers = [number for number, _ in rows]

    assert numbers == sorted(numbers), (
        "o registro de números não está em ordem crescente — a primeira quebra é"
        f" {next(f'{b:04d} depois de {a:04d}' for a, b in zip(numbers, numbers[1:]) if b < a)}."
        " Toda linha nova vai para o **fim** do arquivo: é o append na mesma"
        " posição que faz duas branches conflitarem, e é isso que o mecanismo"
        " compra (ADR 0072)."
    )

    seen: dict[int, int] = {}
    for number in numbers:
        seen[number] = seen.get(number, 0) + 1
    repeated = sorted(number for number, count in seen.items() if count > 1)

    assert repeated == [], (
        "estes números aparecem mais de uma vez no registro: "
        + ", ".join(f"ADR {number:04d}" for number in repeated)
        + ". Duas linhas com o mesmo número são duas decisões reivindicando o"
        " mesmo lugar — renumere a mais nova com `npm run adr` (ADR 0072)."
    )


def test_every_adr_file_has_a_line_in_the_number_registry() -> None:
    """Direção 1: todo arquivo de ADR reivindicou o número dele no registro.

    Fail-closed nas duas pontas: diretório de ADR vazio reprova (o glob quebrou),
    registro ausente ou vazio reprova em `_read_registry`. Verde por não ter
    conseguido olhar é o `dependency-review` da ADR 0023, e aqui custaria a fatia
    inteira: um registro que não descreve o diretório não aloca número nenhum.
    """
    files = _read_adrs()
    assert files, (
        "nenhum arquivo de ADR foi encontrado em `docs/adr/` — o glob quebrou, e"
        " uma guarda que não olha nada não pode dizer que está tudo certo."
    )
    rows, _ = _read_registry()
    claimed = dict(rows)

    missing = sorted(name for name in files if _adr_number(name) not in claimed)
    assert missing == [], (
        "estes arquivos de ADR não têm linha no registro de números: "
        + ", ".join(missing)
        + ". A linha é escrita por `npm run adr` no mesmo commit do arquivo — sem"
        " ela o número não foi reivindicado em lugar nenhum, e a próxima branch o"
        " toma sem que nada conflite (ADR 0072)."
    )

    diverging = sorted(
        f"ADR {_adr_number(name):04d}: o arquivo diz `{_adr_slug(name)}` e o"
        f" registro diz `{claimed[_adr_number(name)]}`"
        for name in files
        if claimed[_adr_number(name)] != _adr_slug(name)
    )
    assert diverging == [], (
        "o slug do registro e o do nome do arquivo divergem: "
        + "; ".join(diverging)
        + ". O registro é onde se lê que número pertence a que decisão; um slug"
        " que não bate faz a linha apontar para uma decisão que não é aquela"
        " (ADR 0072)."
    )


def test_every_line_in_the_number_registry_has_an_adr_file() -> None:
    """Direção 2: toda linha reivindicada tem arquivo.

    As duas direções, porque as duas já falharam neste repositório em documentos
    diferentes — é o argumento da ADR 0034 sobre o `alerts.md`, onde o runbook
    nomeava um evento que ninguém emitia e doze emitidos não tinham runbook. Aqui
    a linha órfã é pior que ruído: ela **queima** um número que ninguém usou, e a
    ferramenta aloca a partir do maior reivindicado.
    """
    files = _read_adrs()
    assert files, (
        "nenhum arquivo de ADR foi encontrado em `docs/adr/` — o glob quebrou, e"
        " uma guarda que não olha nada não pode dizer que está tudo certo."
    )
    existing = {_adr_number(name) for name in files}
    rows, _ = _read_registry()

    dangling = sorted(
        f"ADR {number:04d}\t{slug}" for number, slug in rows if number not in existing
    )
    assert dangling == [], (
        "estas linhas do registro não têm arquivo em `docs/adr/`: "
        + "; ".join(dangling)
        + ". Ou o arquivo foi apagado e a linha ficou (queimando um número), ou a"
        " linha foi escrita antes do arquivo — as duas se resolvem no mesmo"
        " commit (ADR 0072)."
    )


#: Atributos que desligam a mesclagem com conflito: o driver nomeado
#: (`merge=union` é o caso literal), a negação (`-merge`, `!merge`) e o macro
#: `binary`, que o próprio git expande para `-diff -merge -text`.
_MERGE_ATTRIBUTES = re.compile(r"^(?:merge(?:=|$)|[-!]merge$|binary$)")

#: Diretórios que a varredura de `.gitattributes` não atravessa: artefato de
#: instalação e de build. A mesma lista do `NOT_OURS` do `scripts/pins.mjs`.
_NOT_OURS = {".git", ".next", ".venv", "node_modules", "test-results"}


def _covers(pattern: str, relative: str) -> bool:
    """O padrão de `.gitattributes` alcança este caminho?

    `relative` é o caminho do registro **visto de dentro do diretório daquele
    `.gitattributes`**, porque é assim que o git resolve um padrão: o arquivo
    vale dali para baixo, e um `number-registry.tsv` escrito em `docs/adr/`
    alcança o registro enquanto o mesmo texto na raiz não alcança nada.

    Deliberadamente **generoso**: casa o caminho inteiro, o nome do arquivo (é o
    que um padrão sem barra faz no git) e qualquer diretório acima dele. Um
    casador exato erraria para o lado errado — deixar de reconhecer o padrão que
    desliga o mecanismo é o falso verde que esta asserção existe para não ter.
    """
    pattern = pattern.lstrip("/").rstrip("/")
    if fnmatch(relative, pattern) or fnmatch(relative.rsplit("/", 1)[-1], pattern):
        return True
    parts = relative.split("/")
    return any(fnmatch("/".join(parts[:index]), pattern) for index in range(1, len(parts)))


def _seen_from(directory: str, target: str) -> str | None:
    """O caminho de `target` visto de dentro de `directory` — `None` se está fora.

    É a metade do casador que a primeira versão desta guarda não tinha, e o
    buraco que ela produziu foi medido: a guarda olhava **um** arquivo, o
    `.gitattributes` da raiz, e um `docs/adr/.gitattributes` com quatro palavras
    desarmava o mecanismo com as nove asserções verdes — no diretório mais óbvio
    para quem fosse desarmá-lo. O git lê `.gitattributes` de qualquer diretório e
    o aplica dali para baixo; quem não faz o mesmo pergunta por um arquivo que
    não é o que decide.
    """
    if directory in ("", "."):
        return target
    prefix = directory.rstrip("/") + "/"
    return target[len(prefix) :] if target.startswith(prefix) else None


def _merge_declarations(text: str, relative: str) -> list[tuple[int, str]]:
    """As linhas daquele `.gitattributes` que declaram mesclagem para o registro.

    Recebe `text: str` pela convenção do módulo — só as funções `test_*` abrem
    arquivo —, e é o que permite exercer o casador sem escrever nada no disco.
    """
    declarations: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        pattern, *attributes = line.split()
        if not _covers(pattern, relative):
            continue
        if any(_MERGE_ATTRIBUTES.match(attribute) for attribute in attributes):
            declarations.append((number, line.strip()))
    return declarations


def _gitattributes_files() -> list[Path]:
    """Todo `.gitattributes` do repositório, menos o que não é nosso.

    A poda é a mesma do `NOT_OURS` do `scripts/pins.mjs` — artefato de
    instalação e de build —, e sem ela a varredura desceria os milhares de
    diretórios de `node_modules` para ler atributos que o git aplica a código de
    terceiro, não ao registro.
    """
    found: list[Path] = []
    for directory, subdirectories, names in os.walk(REPO_ROOT):
        subdirectories[:] = [name for name in subdirectories if name not in _NOT_OURS]
        if ".gitattributes" in names:
            found.append(Path(directory) / ".gitattributes")
    return sorted(found)


def test_the_merge_driver_matcher_reads_a_pattern_the_way_git_does() -> None:
    """O casador, exercido sem tocar no disco.

    Ele tem duas metades e as duas já erraram: o **padrão** (que o `_covers`
    resolve de forma generosa de propósito) e o **diretório** (que a primeira
    versão desta guarda simplesmente não tinha). Esta asserção fixa as duas em
    casos escritos, na forma do `_TEMPLATE_SAMPLE` do registro de prompts: a
    cobertura de um portão é a dos ramos que a amostra percorre.
    """
    registry = "docs/adr/number-registry.tsv"

    # O diretório: o mesmo texto alcança ou não alcança, conforme onde mora.
    assert _seen_from("", registry) == registry
    assert _seen_from("docs", registry) == "adr/number-registry.tsv"
    assert _seen_from("docs/adr", registry) == "number-registry.tsv"
    assert _seen_from("apps/api", registry) is None
    assert _seen_from("docs/adr-antigo", registry) is None

    # O padrão, visto da raiz e visto de `docs/adr/`.
    from_root = _seen_from("", registry)
    from_dir = _seen_from("docs/adr", registry)
    assert from_root is not None and from_dir is not None
    for pattern in ("docs/adr/number-registry.tsv", "*.tsv", "docs/adr/*", "docs/adr"):
        assert _covers(pattern, from_root), pattern
    for pattern in ("number-registry.tsv", "*.tsv", "*"):
        assert _covers(pattern, from_dir), pattern
    for pattern in ("*.json", "app/*", "docs/fdd/*"):
        assert not _covers(pattern, from_root), pattern

    # Padrão **sem barra** alcança pelo nome em qualquer profundidade abaixo do
    # `.gitattributes`, que é o que o git faz — e é o lado generoso do casador.
    assert _covers("number-registry.tsv", from_root)
    # Padrão **com barra** é ancorado no diretório do arquivo: escrito na raiz,
    # `adr/number-registry.tsv` não alcança `docs/adr/number-registry.tsv`.
    assert not _covers("adr/number-registry.tsv", from_root)

    # E o que conta como desligar a mesclagem, incluindo o macro `binary`, que o
    # git expande para `-diff -merge -text`.
    for attribute in ("merge=union", "merge=ours", "merge", "-merge", "!merge", "binary"):
        assert _MERGE_ATTRIBUTES.match(attribute), attribute
    for attribute in ("text=auto", "eol=lf", "diff=markdown", "merged"):
        assert not _MERGE_ATTRIBUTES.match(attribute), attribute

    # E o casador de linha inteiro, sobre arquivos que não existem no disco. O
    # comentário e a linha em branco saem, `*.md text=auto` não é mesclagem, e a
    # linha que importa volta com o número dela.
    sample = "# comentário\n\nnumber-registry.tsv merge=union\n*.md text=auto\n"
    assert _merge_declarations(sample, from_dir) == [
        (3, "number-registry.tsv merge=union")
    ]
    assert _merge_declarations(sample, from_root) == [
        (3, "number-registry.tsv merge=union")
    ]
    assert _merge_declarations("adr/number-registry.tsv merge=union\n", from_root) == []


def test_the_number_registry_is_not_disarmed_by_a_merge_driver() -> None:
    """Ninguém desliga o conflito em silêncio.

    O mecanismo inteiro é o git recusar mesclar dois appends na mesma posição. Um
    `.gitattributes` com `merge=union` para o registro faz o git mesclar os dois
    sem dizer nada: as duas linhas entram, as duas ADRs ficam com o mesmo número,
    e a corrida volta a existir **com o arquivo parecendo íntegro**. Não existe
    `.gitattributes` neste repositório hoje, e por isso a asserção é condicional —
    o que ela impede é o arquivo nascer já desarmando o mecanismo.

    **Varre todos**, e não o da raiz: a primeira versão olhava
    `REPO_ROOT / ".gitattributes"` e passava verde com um `docs/adr/.gitattributes`
    de quatro palavras desarmando tudo — medido, com `git check-attr merge`
    respondendo `union` e as nove asserções passando. Perguntar por um arquivo só
    é perguntar por um arquivo que não é o que decide.

    Fail-closed no espírito da casa: o mecanismo tem de ser indefensável de forma
    silenciosa. Desligá-lo continua possível, e passa a exigir apagar esta
    asserção junto — que é uma linha de diff que uma pessoa lê.
    """
    registry = REGISTRY.relative_to(REPO_ROOT).as_posix()
    offending: list[str] = []
    for path in _gitattributes_files():
        directory = path.parent.relative_to(REPO_ROOT).as_posix()
        relative = _seen_from(directory, registry)
        if relative is None:
            continue
        name = path.relative_to(REPO_ROOT).as_posix()
        offending += [
            f"{name}:{number}: `{line}`"
            for number, line in _merge_declarations(
                path.read_text(encoding="utf-8"), relative
            )
        ]

    assert offending == [], (
        "um `.gitattributes` declara mesclagem para o registro de números: "
        + "; ".join(offending)
        + f". O conflito em `{registry}` **é** o mecanismo (ADR 0072) — um driver"
        " de merge ali faz duas branches receberem o mesmo número com o arquivo"
        " parecendo íntegro. Apague o atributo; se a intenção é mesmo desligar a"
        " coordenação, isso é decisão de ADR, não de linha de configuração."
    )
