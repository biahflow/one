"""Os enums da jornada e o documento que os define (ADR 0081).

O `Language Map v1.1` é **normativo**: a §4 dele é a tabela dos enums canônicos, e as
issues desta fase o citam como fonte. Até esta fatia nada ligava aquele documento ao
código — `journey_phase.canonical_stage` estava escrito lá com a observação "já existe
no Pulse", e deste lado não existia coluna, enum, contrato nem tela.

O que esta guarda faz é o que o repositório já faz com telemetria (`alerts.md` ↔
eventos emitidos) e com o contrato (`openapi.json` ↔ leitores do BFF): **derivar os dois
lados de artefatos e cobrar o elo**. O corpus sai da tabela §4, não de uma lista
digitada aqui — uma lista digitada é o defeito que a ADR 0033 mediu, e envelheceria
igual: o dia em que a D7 acrescentar um quinto desfecho de gate, é o documento que muda,
e é o documento que esta guarda lê.

**Fail-closed.** Se a linha da tabela não for encontrada — porque o documento mudou de
formato, foi renomeado ou sumiu —, o teste **reprova**; não pula. Verde por não ter
olhado é o modo de falha do `dependency-review` da ADR 0023, e uma guarda que se
autopula quando o alvo some é a mesma coisa com outro nome.

Sem banco e sem rede: lê um arquivo e dois enums.
"""

from __future__ import annotations

import re
from pathlib import Path

from portal_api.integrations.biahflow import CANONICAL_STAGE_MAP, GATE_DECISION_MAP
from portal_api.models import CanonicalStage, GateDecision

REPO_ROOT = Path(__file__).resolve().parents[3]
LANGUAGE_MAP = REPO_ROOT / "docs" / "ontology" / "language-map.md"

#: O que cada linha da tabela §4 governa deste lado. A chave é o **nome do campo como
#: o documento o escreve**, na primeira coluna e entre crases; o valor é o enum Python
#: que tem de dizer exatamente a mesma coisa.
GOVERNED_BY_THE_MAP = {
    "journey_phase.canonical_stage": CanonicalStage,
    "gate_decision": GateDecision,
}

#: Cada mapa da ingestão, com o enum de que ele traduz. Um mapa é a fronteira: se ele
#: esquecer um valor, aquele degrau chega da origem e vira ``None`` **em silêncio** —
#: a fase aparece sem degrau e nada fica vermelho, que é exatamente o desfecho que a
#: tolerância a vocabulário desconhecido torna possível de propósito. A tolerância é
#: para o valor que ninguém combinou, não para o que já está combinado.
INGESTION_MAPS = (
    ("CANONICAL_STAGE_MAP", CANONICAL_STAGE_MAP, CanonicalStage),
    ("GATE_DECISION_MAP", GATE_DECISION_MAP, GateDecision),
)

#: Uma linha de tabela markdown: `| campo | valores | observação |`.
_ROW = re.compile(r"^\|(?P<field>[^|]+)\|(?P<values>[^|]+)\|", re.MULTILINE)
_BACKTICKED = re.compile(r"`([^`]+)`")


def _documented_values(field: str) -> list[str]:
    """Os valores que a tabela §4 do Language Map dá ao campo, na ordem em que os escreve.

    Reprova quando a linha não existe — ver o docstring do módulo sobre fail-closed.
    """
    assert LANGUAGE_MAP.exists(), (
        f"{LANGUAGE_MAP} não existe. Ele é o documento normativo do vocabulário "
        "(ADR 0079 o versionou); sem ele esta guarda não tem de onde derivar corpus, e "
        "passar verde seria afirmar que os enums batem com um documento que ninguém leu."
    )
    text = LANGUAGE_MAP.read_text(encoding="utf-8")
    for row in _ROW.finditer(text):
        names = _BACKTICKED.findall(row.group("field"))
        if field not in names:
            continue
        values = _BACKTICKED.findall(row.group("values"))
        assert values, (
            f"a linha de `{field}` na tabela de enums do Language Map não lista valor "
            "nenhum entre crases. O corpus desta guarda sai dali; uma linha sem valores "
            "a deixaria comparando dois conjuntos vazios."
        )
        return values
    raise AssertionError(
        f"não achei a linha de `{field}` na tabela de enums canônicos de "
        f"{LANGUAGE_MAP.relative_to(REPO_ROOT)}. O documento é normativo e esta guarda "
        "deriva o corpus dele: se o campo foi renomeado, renomeie aqui junto; se a "
        "tabela mudou de formato, conserte o casador. O que não pode é o teste passar "
        "sem ter olhado nada (ADR 0023)."
    )


def test_a_tabela_de_enums_do_language_map_e_alcancavel() -> None:
    """Fail-closed: as duas linhas existem e trazem valores.

    Primeira asserção do arquivo de propósito. Sem ela, um documento renomeado deixaria
    as comparações abaixo verdes por vacuidade — que é o modo de falha que esta guarda
    existe para não repetir.
    """
    for field in GOVERNED_BY_THE_MAP:
        assert _documented_values(field), field


def test_os_enums_python_dizem_o_que_o_documento_normativo_diz() -> None:
    for field, enum in GOVERNED_BY_THE_MAP.items():
        documented = _documented_values(field)
        implemented = [member.value for member in enum]
        assert implemented == documented, (
            f"`{field}` vale {documented} no Language Map §4 e {implemented} em "
            f"{enum.__name__}. O documento é normativo: quem muda primeiro é ele, e o "
            "código o segue (Language Map §8). A ordem também importa — ela é a ordem "
            "da escada da FDE, e é o que a tela usa para ler a jornada."
        )


def test_a_ingestao_traduz_todo_valor_que_o_documento_nomeia() -> None:
    for name, mapping, enum in INGESTION_MAPS:
        assert set(mapping) == {member.value for member in enum}, (
            f"{name} não cobre exatamente os valores de {enum.__name__}. O valor que "
            "falta chega da origem e vira `None` em silêncio: a fase aparece sem "
            "degrau, o sync não morre e nada fica vermelho. A tolerância a vocabulário "
            "desconhecido é para a palavra que ninguém combinou — não para a que está "
            "escrita no documento normativo."
        )
        for value, member in mapping.items():
            assert member.value == value, (
                f"{name} traduz {value!r} para {member!r}. A chave do mapa é o valor "
                "que a origem manda e o enum é o mesmo vocabulário: uma tradução "
                "cruzada aqui renomearia o dado no meio do caminho."
            )


def test_o_prove_nao_e_piloto_poc_nem_mvp() -> None:
    """O §5 bane três palavras para o PROVE, e a lista sai do próprio documento.

    Não é asserção sobre a tela — essa é a de `tests/rendered-html.test.mjs`, sobre o
    HTML renderizado. Esta é sobre a **fonte da regra**: se a linha sair do Language
    Map, o teste do web perde o fundamento e alguém tem de reabrir a decisão em vez de
    a proibição evaporar. É a forma do `NOT_AN_ALERT` do `test_telemetry.py`.
    """
    rows = [
        line.lower()
        for line in LANGUAGE_MAP.read_text(encoding="utf-8").splitlines()
        if line.startswith("|") and "prove" in line.lower() and "poc" in line.lower()
    ]
    assert rows, (
        "sumiu do Language Map a linha que bane POC/piloto/MVP para o PROVE. Ela é o "
        "que fundamenta a asserção de HTML renderizado do lado web; sem ela, aquela "
        "guarda estaria proibindo palavras por conta própria."
    )
    for term in ("piloto", "mvp"):
        assert any(term in row for row in rows), (
            f"o Language Map deixou de banir {term!r} para o PROVE. São duas linhas que "
            "dizem isso — a tabela mestra (§2, coluna 'Nunca chamar de') e a de termos "
            "banidos (§5) —, e a guarda aceita qualquer uma: o que ela cobra é que a "
            f"proibição continue escrita em algum lugar do documento normativo. Rows: {rows}"
        )
