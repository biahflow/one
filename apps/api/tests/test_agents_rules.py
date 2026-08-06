"""As regras que todo o repositório cita, e a guarda de que elas existem (ADR 0035).

Toda fatia deste projeto deixa uma guarda derivada da fonte para a promessa que
consertou. Esta é sobre a fonte de todas as outras: as regras inegociáveis do
`AGENTS.md`, citadas **por número** em vinte lugares — ADRs, FDDs, docstrings de
teste e até no artefato publicado `docs/api/openapi.json`.

O que se encontrou ao contá-las: o `AGENTS.md` tinha cinco princípios numerados e
o `CLAUDE.md` publicava seis "from `AGENTS.md`", renumerados — promovendo uma
convenção e um item de checklist de pull request a princípio, e descartando o
princípio 5 (segredos em commits, fixtures, logs e documentação). A numeração que
circulava era a da cópia: seis lugares citavam uma "regra 6" que não existia com
esse número, e "regra 5" queria dizer uma coisa em `docs/adr/0018` e outra em
`docs/adr/0025`.

Nenhuma das duas asserções aqui precisa de banco: são sobre arquivos.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTS = REPO_ROOT / "AGENTS.md"
CLAUDE = REPO_ROOT / "CLAUDE.md"

#: Onde uma citação por número pode aparecer. O `openapi.json` entra porque as
#: descrições das rotas são docstrings copiadas para o artefato publicado — uma
#: citação errada ali sai do repositório junto com o contrato.
_CITING_GLOBS = ("docs/**/*.md", "apps/api/tests/*.py", "docs/api/openapi.json")

#: `regra 4 do AGENTS.md`, `AGENTS.md #3`, `AGENTS regra 3`. O número é o grupo.
_CITATION = re.compile(
    r"(?:regra\s+(\d+)\s+d[oe]\s+`?AGENTS(?:\.md)?`?"
    r"|AGENTS(?:\.md)?\s*#\s*(\d+)"
    r"|AGENTS\s+regra\s+(\d+))",
    re.IGNORECASE,
)

#: A nota histórica é registro do erro, não instrução — a mesma leitura que a
#: guarda de eventos faz do `alerts.md` (ADR 0034). Sem isto, a nota que o
#: próprio `AGENTS.md` carrega sobre a renumeração seria lida como citação.
_HISTORICAL_NOTE = re.compile(r"\*(Corrigido|Acrescentado|A regra) [\s\S]*?\*(?!\*)")

_NUMBERED_ITEM = re.compile(r"^(\d+)\.\s+(.+)$", re.MULTILINE)


def _principles(text: str) -> dict[int, str]:
    """Os itens numerados da seção de princípios, até a primeira quebra de seção.

    A seção é reconhecida pelo **título**, e não pelo corpo. A primeira versão
    procurava a palavra no texto inteiro da seção, e a própria fatia que escreveu
    esta guarda a derrubou: o parágrafo de abertura do `CLAUDE.md` passou a
    descrever "as regras inegociáveis" ao narrar a ADR 0035, e casou primeiro.
    """
    for section in text.split("\n## "):
        title = section.split("\n", 1)[0]
        if "inegociáveis" in title or "Non-negotiable" in title:
            return {
                int(number): item.strip()
                for number, item in _NUMBERED_ITEM.findall(section)
            }
    raise AssertionError("nenhuma seção de princípios encontrada")


def test_the_two_lists_of_rules_are_the_same_list() -> None:
    """O `CLAUDE.md` publica a lista do `AGENTS.md`, e não uma cópia renumerada.

    A cópia é o que produziu o resto: cinco princípios de um lado, seis do outro,
    com significados diferentes para o mesmo número. Só a **contagem** e a
    numeração são cobradas, não o texto — os dois arquivos falam idiomas
    diferentes por convenção do projeto (produto em PT-BR, `CLAUDE.md` em inglês).
    """
    agents = _principles(AGENTS.read_text(encoding="utf-8"))
    claude = _principles(CLAUDE.read_text(encoding="utf-8"))

    assert sorted(agents) == sorted(claude), (
        f"`AGENTS.md` numera {sorted(agents)} e `CLAUDE.md` numera {sorted(claude)}."
        " A segunda lista é a primeira — se uma regra nasce, nasce nas duas, com o"
        " mesmo número (ADR 0035)."
    )
    assert list(agents) == list(range(1, len(agents) + 1)), (
        f"os princípios do `AGENTS.md` não são 1..n: {sorted(agents)}."
    )


def test_every_numbered_citation_points_at_a_rule_that_exists() -> None:
    """Uma citação `regra N` resolve, ou não deveria ter sido escrita.

    Nasceu vermelha com seis citações de uma "regra 6" inexistente, em
    `docs/adr/0024`, `docs/adr/0029`, `docs/fdd/012` e em três arquivos de teste
    deste diretório — inclusive no docstring de abertura do `test_authorization.py`,
    que é o arquivo cuja razão de existir é justamente essa regra.
    """
    agents = _principles(AGENTS.read_text(encoding="utf-8"))
    dangling: list[str] = []

    for pattern in _CITING_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if not path.is_file():
                continue
            text = _HISTORICAL_NOTE.sub("", path.read_text(encoding="utf-8"))
            for match in _CITATION.finditer(text):
                number = int(next(group for group in match.groups() if group))
                if number not in agents:
                    relative = path.relative_to(REPO_ROOT).as_posix()
                    dangling.append(f"{relative}: regra {number}")

    assert dangling == [], (
        "estas citações apontam para um princípio que o `AGENTS.md` não tem: "
        + ", ".join(sorted(set(dangling)))
        + ". Corrija o número, ou escreva a regra — uma citação que não resolve é"
        " uma instrução que manda o leitor para lugar nenhum (ADR 0035)."
    )
