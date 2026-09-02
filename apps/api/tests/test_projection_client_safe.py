"""A fronteira da projeção deixa de ser prosa e vira portão (Fase 7, ADR 0067/0076).

A ADR 0067 decidiu que One é **projeção client-facing** do estado de Delivery e escreveu a
lista do que *não* atravessa: IDs de Issue/PR do GitHub, internals de branch/CI, custom
fields internos do ClickUp, estado bruto de LangGraph, prompts e traces de LangSmith, e
custos/margens comerciais internos. Até esta fatia isso era **só convenção em prosa** — a
ADR 0076 nomeia a lacuna: "não há guarda que impeça um campo internal-only de atravessar".

O que esta guarda faz é o que o repositório já faz com telemetria e consumo de contrato:
derivar os dois lados de artefatos e cobrar o elo entre eles.

1. **O que a projeção emite** sai do AST de ``build_dashboard`` e das funções que compõem a
   resposta dele — não de uma lista escrita à mão, que é o defeito que a ADR 0033 mediu.
2. **O que o contrato publica** sai de ``docs/api/openapi.json``, seguindo os ``$ref`` a
   partir das operações que respondem o dashboard.
3. O elo: os dois conjuntos têm de ser **o mesmo** no topo. Sem ele, um campo novo em
   ``build_dashboard`` sem esquema regenerado escaparia da metade que olha o contrato, e um
   campo declarado sem produtor escaparia da metade que olha o código.

Roda **sem rede e sem banco**: lê dois arquivos e um AST. Não é `integration` de propósito —
acoplar a fronteira de dados a um Postgres de pé a tornaria a primeira coisa a ser pulada.

*Sobre a mutação:* a asserção de vocabulário é exercitada aqui contra uma projeção sintética
(``test_o_vocabulario_pega_um_campo_interno_injetado``), e a guarda inteira foi medida à mão
injetando ``github_pr_id`` no ``return`` de ``build_dashboard``: sem a injeção, verde; com
ela, dois vermelhos (o elo com o contrato e o vocabulário sobre o emitido). Uma guarda que
nunca reprovou é a que a ADR 0033 existe para pegar.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import portal_api

SOURCE_ROOT = Path(portal_api.__file__).parent
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = REPO_ROOT / "docs" / "api" / "openapi.json"

#: Os esquemas de resposta que carregam o dashboard. São os dois nomes que ancoram a guarda
#: no contrato, e a asserção de que eles existem é o que impede um rename de deixá-la verde
#: por não ter olhado nada — o modo de falha do `dependency-review` da ADR 0023.
DASHBOARD_SCHEMAS = ("DashboardOut", "MyDashboardOut")

#: As funções que **produzem** a resposta do dashboard, com o módulo em que moram. Um nome
#: que não resolve reprova: renomear um produtor sem atualizar esta lista tiraria metade da
#: projeção do alcance da guarda sem nada ficar vermelho.
PROJECTION_PRODUCERS = (
    ("integrations/biahflow.py", "build_dashboard"),
    ("integrations/biahflow.py", "_journey_projection"),
    ("integrations/biahflow.py", "_discovery_projection"),
    ("integrations/biahflow.py", "_results_projection"),
    ("results.py", "to_payload"),
)

#: Os campos que ``main.py`` acrescenta **depois** de ``build_dashboard``, em
#: ``MyDashboardOut`` e não em ``DashboardOut``. Não são exceção à fronteira: são
#: client-safe e declarados — só não nascem no produtor que esta guarda lê.
ADDED_BY_THE_ROUTE = {"organization", "project_id"}

ADR_0067 = REPO_ROOT / "docs" / "adr" / "0067-one-como-projecao-client-facing.md"

#: O vocabulário proibido, **por linha da ADR 0067**. A chave é a linha literal do documento
#: e a asserção de obsolescência confere que ela continua lá: se a fronteira mudar na ADR,
#: esta guarda fica vermelha e alguém tem de reabrir a decisão em vez de a lista envelhecer
#: em silêncio. É a forma do `NOT_AN_ALERT`/`PROSE_IS_FINE` do `test_telemetry.py`.
#:
#: Dois casadores, e a diferença foi **medida** contra os campos que o dashboard publica
#: hoje:
#:
#: - ``tokens`` casa um pedaço inteiro do nome em ``snake_case`` (``pr`` casa ``pr_id`` e
#:   não casa ``priority``). É o que impede a família de defeitos que este repositório já
#:   viu quatro vezes — o ``.priority`` da ADR 0033, o ``date``/``dated_at`` da 0038.
#: - ``substrings`` é para os nomes próprios e compostos que não têm como colidir.
#:
#: E há uma fronteira que **precisou de medição** para ficar certa: o dashboard publica
#: ``avoided_cost_cents``, ``investment_cents``, ``hourly_rate_cents`` e
#: ``labor_savings_cents``. É dinheiro **do cliente** — a economia dele, o investimento
#: dele —, e a própria ADR 0067 lista "resultados, ROI e próximos passos" como client-safe.
#: O que ela proíbe é o **nosso** custo e a **nossa** margem. Um casador por ``cost`` nasceria
#: vermelho sobre quatro campos legítimos, e afrouxá-lo depois é como allowlist vira
#: sedimento; por isso o vocabulário de dinheiro nomeia margem, markup e lucro, não "custo".
INTERNAL_ONLY = {
    "GitHub Issue/PR IDs": {
        "tokens": {"pr", "prs", "issue", "issues"},
        "substrings": {"github", "pull_request", "issue_number", "issue_id", "pr_number"},
    },
    "branch/CI internals": {
        "tokens": {"branch", "sha", "ci", "pipeline", "runner", "workflow"},
        "substrings": {"commit_sha", "workflow_run", "ci_status", "build_number", "job_url"},
    },
    "ClickUp custom fields internos": {
        "tokens": {"clickup"},
        "substrings": {"clickup", "custom_field", "list_id", "space_id", "folder_id"},
    },
    "estado bruto de LangGraph": {
        "tokens": {"checkpoint", "thread"},
        "substrings": {"langgraph", "graph_state", "node_state"},
    },
    "prompts e traces de LangSmith": {
        "tokens": {"prompt", "prompts", "trace", "traces", "span"},
        "substrings": {"langsmith", "trace_id", "system_prompt", "run_tree"},
    },
    "custos/margens comerciais internos": {
        "tokens": {"margin", "markup", "profit", "mrr", "arr"},
        "substrings": {"gross_margin", "internal_cost", "cost_to_serve", "contract_value"},
    },
}


def _offending(field: str) -> str | None:
    """A linha da ADR 0067 que este nome de campo viola, ou ``None``."""
    lowered = field.lower()
    parts = set(lowered.split("_"))
    for line, vocabulary in INTERNAL_ONLY.items():
        if parts & vocabulary["tokens"]:
            return line
        if any(needle in lowered for needle in vocabulary["substrings"]):
            return line
    return None


def _function(module: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((SOURCE_ROOT / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(
        f"{module} não tem mais a função {name}, que esta guarda lê para saber o que a "
        "projeção emite. Renomeou? Atualize PROJECTION_PRODUCERS — sem isso metade da "
        "projeção sai do alcance da guarda sem nada ficar vermelho (ADR 0033)."
    )


def emitted_fields() -> set[str]:
    """Toda chave de dicionário literal que os produtores da projeção escrevem."""
    names: set[str] = set()
    for module, name in PROJECTION_PRODUCERS:
        for node in ast.walk(_function(module, name)):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    names.add(key.value)
    return names


def emitted_top_level() -> set[str]:
    """As chaves do ``return`` de ``build_dashboard`` — a superfície do contrato."""
    função = _function("integrations/biahflow.py", "build_dashboard")
    for node in ast.walk(função):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            return {
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    raise AssertionError("build_dashboard não devolve mais um dicionário literal")


def _schemas() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))["components"]["schemas"]


def _referenced(node: object, found: set[str] | None = None) -> set[str]:
    found = set() if found is None else found
    if isinstance(node, list):
        for item in node:
            _referenced(item, found)
    elif isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            found.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _referenced(value, found)
    return found


def contract_fields() -> set[str]:
    """Todo campo que o contrato publica no dashboard, seguindo os ``$ref``."""
    schemas = _schemas()
    reachable = set(DASHBOARD_SCHEMAS)
    grew = True
    while grew:
        grew = False
        for name in list(reachable):
            for nested in _referenced(schemas.get(name, {})):
                if nested not in reachable:
                    reachable.add(nested)
                    grew = True
    return {key for name in reachable for key in schemas[name].get("properties", {})}


# --------------------------------------------------------------------------- #
# Fail-closed: a guarda tem de estar olhando alguma coisa
# --------------------------------------------------------------------------- #


def test_os_dois_corpora_existem_e_nao_estao_vazios() -> None:
    """Corpus vazio reprova, porque verde por não ter olhado é o defeito da ADR 0023."""
    schemas = _schemas()
    faltando = [name for name in DASHBOARD_SCHEMAS if name not in schemas]
    assert faltando == [], f"o contrato não define {faltando}"
    assert len(emitted_fields()) > 20
    assert len(contract_fields()) > 20


# --------------------------------------------------------------------------- #
# O elo entre o que se emite e o que se declara
# --------------------------------------------------------------------------- #


def test_a_projecao_e_o_contrato_declaram_os_mesmos_campos_no_topo() -> None:
    """O elo, e é ele que fecha as duas fugas possíveis.

    Sem esta asserção, um campo acrescentado a ``build_dashboard`` **sem** regenerar o
    ``openapi.json`` escaparia da metade da guarda que lê o contrato; e um campo declarado
    no contrato sem produtor — o defeito exato da ADR 0033 — escaparia da que lê o código.

    Os dois campos que ``main.py`` acrescenta depois estão nomeados, e não descontados por
    conveniência: eles são de ``MyDashboardOut``, e é isso que a linha diz.
    """
    declarados = set(_schemas()["DashboardOut"].get("properties", {}))

    assert emitted_top_level() == declarados
    assert set(_schemas()["MyDashboardOut"].get("properties", {})) == (
        declarados | ADDED_BY_THE_ROUTE
    )


# --------------------------------------------------------------------------- #
# A fronteira da ADR 0067
# --------------------------------------------------------------------------- #


def test_nenhum_campo_interno_e_emitido_pela_projecao() -> None:
    """A metade que olha o **código**, e a que a mutação derruba primeiro."""
    infratores = sorted(
        f"{field} ({_offending(field)})"
        for field in emitted_fields()
        if _offending(field) is not None
    )

    assert infratores == [], (
        "estes campos atravessam a fronteira client-facing e a ADR 0067 diz que não devem: "
        + ", ".join(infratores)
        + ". One é projeção do estado de Delivery, não a ferramenta interna com outra"
        " roupa — o que sai daqui vai para a tela de um cliente."
    )


def test_nenhum_campo_interno_esta_declarado_no_contrato() -> None:
    """A metade que olha o **artefato publicado**.

    Não é redundante com a de cima: o contrato é o que outro time lê para integrar, e um
    campo declarado é uma promessa mesmo antes de alguém o preencher — foi assim que a ADR
    0033 achou um painel publicado sobre um campo que nunca teve escritor.
    """
    infratores = sorted(
        f"{field} ({_offending(field)})"
        for field in contract_fields()
        if _offending(field) is not None
    )

    assert infratores == [], (
        "o contrato publica estes campos e a ADR 0067 os põe do lado de dentro: "
        + ", ".join(infratores)
    )


def test_o_vocabulario_pega_um_campo_interno_injetado() -> None:
    """A guarda nasce **capaz de reprovar**, e isto é a medição dentro do arquivo.

    Um teste que só afirma o verde não distingue "a fronteira está limpa" de "o casador não
    casa nada" — que é literalmente a allowlist vazia da ADR 0033. Cada linha da ADR 0067
    tem aqui um campo que a viola, e todos precisam ser pegos.
    """
    injetados = {
        "github_pr_id": "GitHub Issue/PR IDs",
        "issue_number": "GitHub Issue/PR IDs",
        "branch": "branch/CI internals",
        "commit_sha": "branch/CI internals",
        "clickup_custom_field_7": "ClickUp custom fields internos",
        "langgraph_checkpoint": "estado bruto de LangGraph",
        "langsmith_trace_url": "prompts e traces de LangSmith",
        "system_prompt": "prompts e traces de LangSmith",
        "gross_margin_cents": "custos/margens comerciais internos",
        "margin": "custos/margens comerciais internos",
    }

    assert {field: _offending(field) for field in injetados} == injetados
    # E a linha da ADR que cada um viola está coberta: nenhuma regra do vocabulário existe
    # sem um caso que a exercite.
    assert set(injetados.values()) == set(INTERNAL_ONLY)


def test_o_vocabulario_nao_confunde_dinheiro_do_cliente_com_margem_nossa() -> None:
    """A fronteira que só apareceu ao medir, e que teria feito a guarda nascer errada.

    ``avoided_cost_cents``, ``investment_cents``, ``hourly_rate_cents`` e
    ``labor_savings_cents`` são a economia e o investimento **do cliente**, e a ADR 0067
    lista "resultados, ROI e próximos passos" entre o que a projeção deve expor. Um casador
    por ``cost`` nasceria vermelho sobre eles — e um vermelho falso é como uma guarda vira
    exceção e depois vira nada.
    """
    for field in (
        "avoided_cost_cents",
        "investment_cents",
        "monthly_investment_cents",
        "hourly_rate_cents",
        "labor_savings_cents",
        "benefit_cents",
        "net_cents",
        "roi_ratio",
        "roi_month",
        "priority",
        "project_id",
        "observed_at",
        "projection_version",
    ):
        assert _offending(field) is None, f"falso positivo em {field}"


def test_o_vocabulario_ainda_descreve_a_fronteira_que_a_adr_0067_escreveu() -> None:
    """A lista não pode envelhecer em silêncio.

    Cada chave de ``INTERNAL_ONLY`` é a linha literal da ADR. Se a decisão mudar de texto —
    ou se alguém acrescentar uma sétima categoria —, este teste fica vermelho e a mudança
    passa por aqui em vez de a guarda continuar cobrando a fronteira antiga. É a mesma
    obsolescência que o `NOT_AN_ALERT` e o `advisories.json` já cobram.
    """
    texto = ADR_0067.read_text(encoding="utf-8")
    ausentes = sorted(line for line in INTERNAL_ONLY if f"- {line}" not in texto)

    assert ausentes == [], (
        "estas linhas não estão mais na lista da ADR 0067: "
        + ", ".join(ausentes)
        + ". A fronteira é decisão de arquitetura: mude a ADR primeiro, e traga esta lista"
        " junto — não o contrário."
    )
