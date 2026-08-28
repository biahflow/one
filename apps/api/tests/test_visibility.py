"""A fronteira do que o One expõe, com negação por omissão (ADR 0082).

Esta é a metade de **cobertura** do guard de visibilidade. A outra metade — as
nove proibições da §3 do Language Map — vive em `tests/api-contract.test.mjs`,
e as duas leem **um artefato só**, `docs/contracts/one-visibility.json`.

A divisão não é arbitrária, e não é o defeito que a ADR 0034 nomeou. Lá o
problema eram duas guardas afirmando **a mesma coisa** sobre o `alerts.md`, que
divergem. Aqui há duas afirmações distintas sobre um dado só:

- aqui: *todo campo que sai para o cliente está classificado*. É uma pergunta
  sobre o contrato inteiro, e ela mora do lado da API porque é a API quem
  decide o que sai — as seis rotas de `app/api/**` do BFF são **passagem crua**
  (`Response.json(await response.json())`, nenhuma filtra campo), e filtrar lá
  seria criar uma segunda autoridade sobre a mesma pergunta;
- lá: *o que sai não é nenhuma das nove coisas proibidas*, afirmado também
  sobre as fixtures do BFF, que é onde uma resposta forjada poderia mentir.

O que esta guarda acrescenta ao `extra="forbid"` da ADR 0020: aquilo fecha o
contrato **por construção** — um campo que o modelo não declara estoura em vez
de sumir. Não diz nada sobre um campo que alguém *declarou*. Esta guarda é a
revisão humana de cada campo declarado, e o mecanismo é a **omissão**: campo
que ninguém classificou não passa.

Lê o **artefato publicado** (`docs/api/openapi.json`), e não `openapi.schema()`
como o vizinho `test_openapi_contract.py`. Dois motivos, e o segundo é o que
manda: o gate de deriva daquele arquivo já prova que publicado == código, então
não há o que se perca; e é o mesmo arquivo que a metade JS lê, o que faz as duas
metades enxergarem **o mesmo corpus** e permite medir a guarda mutando um
arquivo só.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from portal_api import openapi

# Reusados, nunca recopiados — o precedente do `_SECRET_HINTS` em
# `test_openapi_contract.py`. `response_schemas` de lá não serve porque fecha
# sobre **todas** as rotas, e a pergunta daqui é sobre as de cliente.
from test_openapi_contract import _operations, _refs, _security_schemes

VISIBILITY = openapi.REPO_ROOT / "docs" / "contracts" / "one-visibility.json"

#: Razão curta demais é razão que ninguém escreveu. Não é medida de qualidade:
#: é o piso que separa uma frase de um `""` posto para calar a guarda.
_MINIMUM_REASON = 15


@pytest.fixture(scope="module")
def artifact() -> dict[str, Any]:
    return json.loads(VISIBILITY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    return json.loads(openapi.ARTIFACT.read_text(encoding="utf-8"))


def _excluded(path: str, rules: dict[str, Any]) -> str | None:
    """A razão escrita pela qual ``path`` não é superfície de cliente."""
    for entry in rules["excluded_paths"]:
        if entry["path"] == path:
            return entry["reason"]
    for entry in rules["excluded_prefixes"]:
        if path.startswith(entry["prefix"]):
            return entry["reason"]
    return None


def client_paths(document: dict[str, Any], rules: dict[str, Any]) -> set[str]:
    """As rotas 'do One': as publicadas menos as excluídas com razão escrita."""
    return {path for path in document["paths"] if _excluded(path, rules) is None}


def client_response_schemas(
    document: dict[str, Any], rules: dict[str, Any]
) -> set[str]:
    """Só o que **sai** de uma rota de cliente, fechado transitivamente.

    Mesma travessia de `response_schemas` do teste de contrato, com o corpus
    recortado: um esquema que só aparece em `/admin/*` não é o que o cliente vê,
    e classificá-lo aqui misturaria duas perguntas diferentes.
    """
    inside = client_paths(document, rules)
    reachable: set[str] = set()
    for _, path, operation in _operations(document):
        if path not in inside:
            continue
        reachable |= _refs(operation.get("responses", {}))

    definitions = document["components"]["schemas"]
    pending = list(reachable)
    while pending:
        current = pending.pop()
        for name in _refs(definitions.get(current, {})):
            if name not in reachable:
                reachable.add(name)
                pending.append(name)
    return reachable


# --- fail-closed -------------------------------------------------------------


def test_the_corpus_is_not_empty(
    document: dict[str, Any], artifact: dict[str, Any]
) -> None:
    """Verde por não ter olhado é o defeito, não o estado desejado.

    O `dependency-review` da ADR 0023 *parecia* varredura e olhava o diff de um
    PR; o `for` sobre oito nomes da ADR 0033 mantinha a allowlist vazia porque
    nada a consultava. Uma regex que deixasse de casar, um prefixo de exclusão
    escrito largo demais, e esta guarda passaria a afirmar nada — em verde.
    """
    rules = artifact["corpus"]
    paths = client_paths(document, rules)
    assert paths, "o corpus de rotas de cliente saiu vazio; a guarda não está olhando nada"
    schemas = client_response_schemas(document, rules)
    assert schemas, "nenhuma rota de cliente devolve esquema; o corpus não está olhando nada"


def test_every_published_route_is_client_surface_or_has_a_written_reason(
    document: dict[str, Any], artifact: dict[str, Any]
) -> None:
    """Exclusão sem razão escrita é allowlist disfarçada."""
    rules = artifact["corpus"]
    scheme = rules["security_scheme"]

    silent = []
    for path in sorted(document["paths"]):
        reason = _excluded(path, rules)
        if reason is None:
            continue
        if len(reason.strip()) < _MINIMUM_REASON:
            silent.append(path)
    assert silent == [], f"rotas excluídas do corpus sem razão escrita: {silent}"

    # E o outro lado: quem ficou no corpus é mesmo superfície de cliente.
    unauthenticated = sorted(
        f"{method.upper()} {path}"
        for method, path, operation in _operations(document)
        if path in client_paths(document, rules)
        and scheme not in _security_schemes(operation)
    )
    assert unauthenticated == [], (
        "estas rotas estão no corpus de cliente e não pedem o Bearer humano: "
        f"{unauthenticated}. Ou elas não são superfície de cliente — e aí a"
        " exclusão vai para `corpus` com a razão escrita — ou o contrato está errado."
    )


def test_the_exclusions_are_still_real(
    document: dict[str, Any], artifact: dict[str, Any]
) -> None:
    """A linha some quando o motivo some — a regra do `NOT_CALLED` (ADR 0033)."""
    rules = artifact["corpus"]

    gone = sorted(
        entry["path"]
        for entry in rules["excluded_paths"]
        if entry["path"] not in document["paths"]
    )
    assert gone == [], f"`excluded_paths` guarda rotas que o contrato não publica mais: {gone}"

    empty = sorted(
        entry["prefix"]
        for entry in rules["excluded_prefixes"]
        if not any(path.startswith(entry["prefix"]) for path in document["paths"])
    )
    assert empty == [], f"`excluded_prefixes` guarda prefixos que não casam com rota nenhuma: {empty}"


# --- cobertura: negação por omissão ------------------------------------------


def test_every_client_response_schema_is_classified(
    document: dict[str, Any], artifact: dict[str, Any]
) -> None:
    """Esquema novo numa rota de cliente nasce vermelho."""
    declared = set(artifact["schemas"])
    reachable = client_response_schemas(document, artifact["corpus"])

    missing = sorted(reachable - declared)
    assert missing == [], (
        f"estes esquemas saem para o cliente e ninguém os classificou: {missing}."
        " Acrescente cada campo a `docs/contracts/one-visibility.json` com a razão"
        " escrita — o que o campo é e de onde vem. Campo cuja razão não dá para"
        " escrever é campo que não devia estar saindo (ADR 0082)."
    )


def test_every_field_that_reaches_the_client_is_classified(
    document: dict[str, Any], artifact: dict[str, Any]
) -> None:
    """A afirmação central: **campo que ninguém classificou não sai.**

    O `extra="forbid"` da ADR 0020 fecha o contrato por construção, e não diz
    nada sobre um campo que alguém declarou de propósito. Um campo novo do Pulse
    que atravesse o snapshot, entre na projeção e ganhe linha no `schemas.py`
    chega à tela do cliente sem que nada pergunte se ele podia chegar. Daqui em
    diante, chega vermelho.
    """
    definitions = document["components"]["schemas"]
    declared = artifact["schemas"]

    unclassified = []
    thin = []
    for name in sorted(client_response_schemas(document, artifact["corpus"])):
        classified = declared.get(name, {})
        for field in definitions[name].get("properties", {}):
            reason = classified.get(field)
            if reason is None:
                unclassified.append(f"{name}.{field}")
            elif len(str(reason).strip()) < _MINIMUM_REASON:
                thin.append(f"{name}.{field}")

    assert unclassified == [], (
        f"estes campos saem para o cliente e ninguém os classificou: {unclassified}."
        " Negação por omissão: classifique-os no artefato, ou tire-os do contrato."
    )
    assert thin == [], f"campos classificados sem razão escrita de verdade: {thin}"


def test_the_artifact_does_not_keep_a_line_that_left_the_contract(
    document: dict[str, Any], artifact: dict[str, Any]
) -> None:
    """A outra direção, e é ela que impede o artefato de virar sedimento.

    **Não é append-only**, ao contrário do `prompt-registry.json`, e pela razão
    inversa: lá a história é o portão; aqui uma linha que já não descreve o
    contrato é justamente o que se quer fora. É a regra do `advisories.json` e
    do `NOT_CONSUMED` — só que **sem prazo**: pino de visibilidade não caduca
    por calendário, e quem o vence é esta asserção (precedente do
    `PINNED_BY_EXCEPTION`, ADR 0063).
    """
    definitions = document["components"]["schemas"]
    reachable = client_response_schemas(document, artifact["corpus"])

    orphans = []
    for name, fields in sorted(artifact["schemas"].items()):
        if name not in reachable:
            orphans.append(name)
            continue
        published = definitions[name].get("properties", {})
        orphans.extend(f"{name}.{field}" for field in sorted(fields) if field not in published)

    assert orphans == [], (
        f"o artefato guarda linhas que saíram do contrato: {orphans}. Apague-as —"
        " uma classificação que já não descreve campo nenhum afrouxa a guarda"
        " sozinha (ADR 0023/0033)."
    )


# --- as listas de proibição existem e apontam para algo -----------------------
#
# As proibições em si são afirmadas em `tests/api-contract.test.mjs`, sobre o
# contrato **e** sobre as fixtures do BFF. O que se afirma aqui é só a
# integridade do artefato que as duas metades leem: um `forbidden_pairs` com
# chave errada de digitação passaria despercebido em JavaScript, onde um
# `undefined` não estoura.


def test_the_forbidden_lists_are_well_formed(artifact: dict[str, Any]) -> None:
    for entry in artifact["forbidden_resources"]:
        assert entry["term"] == entry["term"].lower()
        assert len(entry["reason"].strip()) >= _MINIMUM_REASON
    for entry in artifact["forbidden_pairs"]:
        assert entry["resource"] and entry["field"]
        assert len(entry["reason"].strip()) >= _MINIMUM_REASON
    for entry in artifact["forbidden_field_names"]:
        assert entry["name"] == entry["name"].lower()
        assert len(entry["reason"].strip()) >= _MINIMUM_REASON
    for key in ("epistemic_resources", "reviewed_resources"):
        block = artifact[key]
        assert block["field"], f"{key} sem o campo que ele exige"
        assert isinstance(block["members"], list)
    assert artifact["account_identifier_inputs"]["forbidden_parameter_names"]
