"""O contrato publicado, e o que ele tem de afirmar (ADR 0020).

O nível 6 da pirâmide de `docs/testing-strategy.md` — "Contrato: OpenAPI e
payloads da API de eventos" — estava listado e não existia. Este arquivo é ele.

Dois tipos de asserção aqui, e a diferença importa:

- o **gate de deriva** (:func:`test_the_published_schema_matches_the_code`), que
  é mecânico: o artefato versionado tem de ser o que o código produz;
- as **propriedades**, que são o contrato de verdade. Elas não conferem se um
  campo mudou de nome; conferem que as regras deste projeto — 404 e nunca 403,
  401 opaco, uma credencial por superfície, nenhum segredo no corpo — continuam
  verdadeiras para *toda* rota, inclusive a que alguém acrescentar amanhã sem
  ler nada disto.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy.orm import Session

from portal_api import openapi, results, schemas
from portal_api.integrations import biahflow
from portal_api.repositories import TenantContext
from portal_api.telemetry import _SECRET_ALLOWLIST, _SECRET_HINTS

# O snapshot que o teste de integração do Biahflow já mantém. Importado em vez
# de recopiado porque um segundo snapshot divergiria do primeiro, e aí o teste
# de contrato passaria a descrever um dashboard que ninguém produz.
from test_biahflow_integration import _snapshot

BEARER = "OIDCBearer"
AGENT_KEY = "AgentKey"

#: As duas rotas de cliente que legitimamente **não** respondem 404, e por quê.
#: A lista é curta de propósito: cada entrada é uma exceção que alguém teve de
#: justificar, e é isso que a impede de crescer por descuido.
NO_TENANT_SCOPE = {
    # Autenticar não é autorizar: quem não tem vínculo recebe 200 com
    # `projects` vazio, para o portal poder dizer "você ainda não tem projeto".
    ("get", "/api/v1/me"),
    # Escreve na própria linha de `user`; não depende de projeto nenhum.
    ("patch", "/api/v1/me/preferences"),
}


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    return openapi.schema()


def _operations(document: dict[str, Any]):
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            yield method, path, operation


def _security_schemes(operation: dict[str, Any]) -> set[str]:
    return {name for entry in operation.get("security", []) for name in entry}


def _refs(node: Any) -> set[str]:
    """Os nomes de `components.schemas` alcançáveis a partir de ``node``."""
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[1])
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for value in node:
            found |= _refs(value)
    return found


def response_schemas(document: dict[str, Any]) -> set[str]:
    """Só o que **sai** do servidor, fechado transitivamente.

    A distinção não é decorativa: o único campo da API cujo nome parece segredo
    e não é fica do lado da requisição (ver
    :func:`test_the_field_that_looks_like_a_secret_and_is_not`).
    """
    reachable: set[str] = set()
    for _, _, operation in _operations(document):
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


# --- o gate ------------------------------------------------------------------


def test_the_published_schema_matches_the_code() -> None:
    """O artefato versionado é o que o código produz. Igual ao `alembic check`."""
    published = openapi.ARTIFACT.read_text(encoding="utf-8")
    current = openapi.render()
    assert published == current, (
        "docs/api/openapi.json está desatualizado. Regenere com:\n"
        "    PYTHONPATH=apps/api/src python -m portal_api.openapi --write\n"
        "e revise o diff — ele é a mudança de contrato."
    )


def test_the_artifact_is_valid_json_and_says_which_api_it_is() -> None:
    document = json.loads(openapi.ARTIFACT.read_text(encoding="utf-8"))
    assert document["info"]["title"] == "Portal Labs API"
    assert document["openapi"].startswith("3.")


# --- as propriedades ---------------------------------------------------------


def test_every_route_declares_the_shape_of_its_answer(document: dict[str, Any]) -> None:
    """Nenhuma rota de esquema vazio pode voltar.

    Era o estado de todas as dezesseis de `main.py` antes desta fatia: o
    `/docs` mostrava a rota, o método e nenhum campo — e `docs/api-contracts.md`
    dizia que o contrato completo era publicado automaticamente.
    """
    untyped = []
    for method, path, operation in _operations(document):
        success = [code for code in operation["responses"] if code.startswith("2")]
        assert success, f"{method.upper()} {path} não declara resposta de sucesso"
        for code in success:
            body = operation["responses"][code]
            if code == "204":  # sem corpo, e é o contrato
                continue
            schema = body.get("content", {}).get("application/json", {}).get("schema")
            if not schema:
                untyped.append(f"{method.upper()} {path} ({code})")
    assert untyped == [], f"rotas sem esquema de resposta: {untyped}"


def test_the_api_never_promises_a_403(document: dict[str, Any]) -> None:
    """A regra mais repetida do projeto, agora legível por máquina.

    Um 403 confirmaria a existência do recurso a quem não deveria saber dela,
    e é por isso que `access.py` devolve `None` → 404 em toda negação. Quem
    gerar um cliente a partir deste esquema não tem como tratar um 403 que a
    API não dá.
    """
    offenders = [
        f"{method.upper()} {path}"
        for method, path, operation in _operations(document)
        if "403" in operation["responses"]
    ]
    assert offenders == [], f"rotas declarando 403: {offenders}"


def test_every_authenticated_route_documents_the_opaque_401(
    document: dict[str, Any],
) -> None:
    missing = [
        f"{method.upper()} {path}"
        for method, path, operation in _operations(document)
        if _security_schemes(operation) and "401" not in operation["responses"]
    ]
    assert missing == [], f"rotas autenticadas sem 401 documentado: {missing}"


def test_every_tenant_scoped_route_documents_the_404(document: dict[str, Any]) -> None:
    """404 é a resposta a "não é seu", e toda rota escopada tem de declará-la."""
    missing = [
        f"{method.upper()} {path}"
        for method, path, operation in _operations(document)
        if BEARER in _security_schemes(operation)
        and (method, path) not in NO_TENANT_SCOPE
        and "404" not in operation["responses"]
    ]
    assert missing == [], f"rotas escopadas sem 404 documentado: {missing}"


def test_the_events_route_is_the_only_one_authenticated_by_key(
    document: dict[str, Any],
) -> None:
    """A ADR 0013 em forma de esquema.

    Um agente não tem sessão de usuário, então o Bearer humano não vale nesta
    rota — e ela é a única assim. Até aqui isso vivia em prosa no
    `docs/api-contracts.md`, onde nada o verificava.
    """
    by_key = {
        path
        for _, path, operation in _operations(document)
        if AGENT_KEY in _security_schemes(operation)
    }
    assert by_key == {"/api/v1/agent-events"}

    events = document["paths"]["/api/v1/agent-events"]["post"]
    assert _security_schemes(events) == {AGENT_KEY}
    assert BEARER not in _security_schemes(events)
    # 429 é a única recusa que não é opaca: o produtor precisa distinguir
    # "seu ritmo" de "sua credencial" para saber se deve tentar de novo.
    assert "429" in events["responses"]


def test_no_response_field_is_named_like_a_secret(document: dict[str, Any]) -> None:
    """Regra 5 do `AGENTS.md` aplicada ao contrato, e não só ao log.

    Reusa a lista de `telemetry.py` de propósito: uma segunda lista divergiria
    da primeira, e aí um dos dois controles passaria a proteger outra coisa.
    A exceção é `key`, de `AgentKeyCreatedOut` — a chave em claro devolvida uma
    única vez na criação, que é justamente o único lugar onde um segredo *tem*
    de estar no corpo (ADR 0013).
    """
    allowed = set(_SECRET_ALLOWLIST) | {"key"}
    definitions = document["components"]["schemas"]
    offenders = []
    for name in sorted(response_schemas(document)):
        for field in definitions[name].get("properties", {}):
            if field in allowed:
                continue
            if any(hint in field.lower() for hint in _SECRET_HINTS):
                offenders.append(f"{name}.{field}")
    assert offenders == [], f"campos com nome de segredo no corpo de resposta: {offenders}"


def test_the_field_that_looks_like_a_secret_and_is_not(document: dict[str, Any]) -> None:
    """`AgentEventIn.agent_key` é o **rótulo** do agente, não a credencial.

    Achado ao escrever o teste acima, e é por isso que ele varre só o que sai:
    o campo entra no corpo do evento para dizer *qual* agente executou, e a
    credencial de verdade viaja no header `X-Agent-Key`, nunca no corpo. Os dois
    nomes quase iguais são um convite a confundi-los, e este teste é o lugar
    onde a diferença fica escrita.
    """
    assert "agent_key" in document["components"]["schemas"]["AgentEventIn"]["properties"]
    assert "AgentEventIn" not in response_schemas(document)


def test_the_only_secret_in_a_body_is_the_key_returned_once(
    document: dict[str, Any],
) -> None:
    """E ela está onde deve: só na criação e na rotação, nunca na listagem."""
    created = document["components"]["schemas"]["AgentKeyCreatedOut"]
    assert "key" in created["properties"]
    assert "key" not in document["components"]["schemas"]["AgentKeyOut"]["properties"]


# --- nenhuma chave se perde --------------------------------------------------
#
# `response_model` **filtra** o que o modelo não declara. Sem estes dois, um
# campo novo em `build_dashboard` sumiria do corpo em silêncio e a tela
# simplesmente pararia de mostrar algo, sem nada ficar vermelho. É o modo de
# falha que esta fatia acrescentaria se parasse no esquema.


@pytest.mark.integration
def test_the_dashboard_model_describes_the_dashboard_exactly(
    db_session: Session,
) -> None:
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=90, client_id=90)
    )
    payload = biahflow.build_dashboard(db_session, project)
    payload["organization"] = "Acme Brasil"

    model = schemas.MyDashboardOut.model_validate(payload)

    # Ida e volta, e não só validação: o `extra="forbid"` pega a chave a mais,
    # e a comparação abaixo pega a chave a menos **e** o valor que o Pydantic
    # teria reserializado num formato diferente do que a tela recebe hoje.
    assert model.model_dump(by_alias=True) == payload


@pytest.mark.integration
def test_the_results_model_describes_the_measurement_exactly(
    db_session: Session,
) -> None:
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=91, client_id=91)
    )
    ctx = TenantContext(
        organization_id=project.organization_id, project_id=project.id
    )
    payload = results.to_payload(results.compute_results(db_session, ctx))

    model = schemas.ResultsOut.model_validate(payload)
    assert model.model_dump(by_alias=True) == payload
    # `from` é palavra reservada em Python e não no JSON. Sem o alias, o campo
    # sairia como `from_` e a aba Resultados perderia o período.
    assert "from" in model.model_dump(by_alias=True)["period"]


def test_an_undeclared_field_is_refused_instead_of_dropped() -> None:
    """A decisão do `extra="forbid"`, executada.

    Sem ela o Pydantic descarta a chave desconhecida e devolve 200: o contrato
    continuaria "válido" enquanto a tela perde um dado. Com ela a resposta
    falha alto, e o teste acima é quem a encontra antes da produção.
    """
    with pytest.raises(Exception):
        schemas.PreferencesOut.model_validate(
            {"notify_by_email": True, "campo_que_ninguem_declarou": 1}
        )
