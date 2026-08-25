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

Nenhuma asserção aqui precisa de banco: são sobre arquivos. E os auxiliares recebem
`text: str`, nunca `Path` — só as funções `test_*` abrem arquivo —, que é o que
permitiu medir contra `HEAD` sem tocar no working tree.
"""

from __future__ import annotations

import re
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
        number = int(name.split("-", 1)[0])
        found = _STATUS.search(text)
        statuses[number] = found.group(1).lower() if found else ""
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

    `_adrs()` chaveia por `int(name.split("-", 1)[0])`: um número repetido faz o
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
        number = int(name.split("-", 1)[0])
        by_number.setdefault(number, []).append(name)

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
