"""A superfície de Discovery que o cliente lê (Language Map v1.1, ADR 0086).

Seis coisas são provadas aqui, e a linha que as une é **não afirmar mais do que a
origem afirmou**:

1. os cinco agregados atravessam o snapshot e chegam à projeção, com os ids da
   origem ligando as quatro listas;
2. o **invariante 9** do Language Map ("`Finding` com `epistemic_status=fact` tem ao
   menos uma `Evidence` viva") vale deste lado: um fato sem evidência é rebaixado a
   hipótese, e o achado continua visível;
3. um vocabulário epistêmico que este lado não conhece cai em ``unknown``, e **nunca**
   em ``fact`` — o degrau seguro é a lacuna;
4. o que os dois JSONB carregam é **lista branca**: um campo novo do produtor não
   atravessa por omissão, que é onde o guard de visibilidade (ADR 0082) não alcança;
5. o Discovery é escopado por **conta**: dois projetos da mesma conta veem o mesmo
   conjunto, e o segundo sync não duplica linha;
6. **ausência das quatro chaves é silêncio, lista vazia é afirmação** — sem essa
   distinção, despublicar no Pulse não teria como chegar até aqui, e um Biahflow
   anterior à fatia apagaria o Discovery de todo cliente.

A isolação entre tenants tem casa própria em ``test_rls_isolation.py``: aqui o
``db_session`` roda sob ``portal_system``, que é ``BYPASSRLS`` por desenho — o mesmo
recorte que ``test_engagement.py`` e ``test_kpi_and_value_ledger.py`` declaram. O que
**é** afirmado aqui é a outra metade daquela fronteira: o filtro explícito por
organização na projeção, que é o que protege o produtor, porque ele roda sem policy.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api.integrations import biahflow
from portal_api.models import (
    EpistemicStatus,
    Finding,
    ImprovementOpportunity,
    PainPoint,
    Process,
    ProcessStep,
    SolutionHypothesis,
)
from test_biahflow_integration import _snapshot


def _finding(payload: dict[str, Any], external_id: int) -> dict[str, Any]:
    return next(item for item in payload["findings"] if item["id"] == external_id)


def _pain(payload: dict[str, Any], external_id: int) -> dict[str, Any]:
    return next(item for item in payload["pain_points"] if item["id"] == external_id)


def _opportunity(payload: dict[str, Any], external_id: int) -> dict[str, Any]:
    return next(
        item for item in payload["improvement_opportunities"] if item["id"] == external_id
    )


def _projected(dashboard: dict[str, Any], key: str, external_id: int) -> dict[str, Any]:
    return next(item for item in dashboard[key] if item["id"] == external_id)


# --- unidade: as duas listas brancas e a ordem declarada --------------------
#
# Puras, sem banco. São as funções em que a fatia decide **o que atravessa**, e é
# nelas que a proteção mora: o guard de visibilidade da ADR 0082 classifica campo de
# esquema e não enxerga dentro de um JSONB, então quem nega por omissão ali é a
# ingestão.


def test_a_evidencia_so_atravessa_com_as_quatro_chaves_da_lista_branca() -> None:
    """Um campo novo do produtor não passa — nem o trecho bruto, nem o hash.

    É a asserção que sustenta a frase do ADR: a lista branca é o equivalente, dentro
    do JSONB, da negação por omissão que o ``one-visibility.json`` faz fora dele.
    """
    passou = biahflow._evidences(
        [
            {
                "id": 5001,
                "kind": "observation",
                "reference": "Sessão de 12/08",
                "captured_at": "2026-08-12T15:00:00+00:00",
                # Os três que a issue #90 nomeia como "nunca pedir/expor".
                "raw_excerpt": "trecho bruto da transcrição",
                "content_hash": "sha256:...",
                "transcript": "texto corrido da sessão",
            }
        ]
    )

    assert passou == [
        {
            "id": 5001,
            "kind": "observation",
            "reference": "Sessão de 12/08",
            "captured_at": "2026-08-12T15:00:00+00:00",
        }
    ]


def test_a_evidencia_sem_identidade_ou_sem_especie_cai_sem_derrubar_o_achado() -> None:
    """Sem ``id`` não há o que endereçar; sem ``kind`` não há o que rotular."""
    assert biahflow._evidences([{"kind": "observation"}, {"id": 1, "kind": "  "}]) == []
    # E a prosa vazia vira `None`, nunca `""` — o padrão desta função.
    assert biahflow._evidences([{"id": 1, "kind": "doc", "reference": ""}]) == [
        {"id": 1, "kind": "doc", "reference": None, "captured_at": None}
    ]


def test_a_prioridade_sem_nota_nao_existe_e_o_racional_nunca_entra() -> None:
    """Duas afirmações numa, porque as duas são sobre o mesmo objeto.

    **Sem ``score`` não há avaliação**: as três colunas saem nulas juntas, porque a
    versão de uma nota que não existe não diz nada. E o ``rationale`` — par proibido
    da §3 — não atravessa nem quando vem **dentro** de ``dimensions``, que é o único
    lugar onde o guard de contrato não o veria.
    """
    assert biahflow._priority({"version": 2, "dimensions": {"impact": 5}}) == (
        None,
        None,
        None,
    )
    assert biahflow._priority(None) == (None, None, None)

    version, score, dimensions = biahflow._priority(
        {
            "version": 2,
            "score": 82,
            "rationale": "o time acha que dá para vender junto",
            "dimensions": {
                "impact": 5,
                "evidence_strength": 4,
                "feasibility": 3,
                "time_to_value": 4,
                "economics": 5,
                "rationale": "não deveria estar aqui",
            },
        }
    )
    assert (version, score) == (2, 82)
    assert dimensions == {
        "impact": 5,
        "evidence_strength": 4,
        "feasibility": 3,
        "time_to_value": 4,
        "economics": 5,
    }


def test_a_posicao_zero_da_origem_vence_o_indice_do_laco() -> None:
    """``or fallback`` seria errado, e o caso é real: zero é posição legítima."""
    assert biahflow._position(0, 7) == 0
    assert biahflow._position(None, 7) == 7
    assert biahflow._position("", 7) == 7


# --- integração: a ingestão -------------------------------------------------


@pytest.mark.integration
def test_o_snapshot_cria_o_discovery_da_conta(db_session: Session) -> None:
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=9001, client_id=9000)
    )

    processo = db_session.execute(
        select(Process).where(Process.organization_id == project.organization_id)
    ).scalar_one()
    assert processo.external_id == 301
    assert processo.name == "Conciliação de contas a pagar"
    assert processo.source_updated_at is not None

    etapas = {
        row.external_id: row
        for row in db_session.execute(
            select(ProcessStep).where(ProcessStep.process_id == processo.id)
        ).scalars()
    }
    assert set(etapas) == {3101, 3102}
    assert etapas[3101].pessoas == "2 analistas"
    assert etapas[3101].retrabalho == "Refazer o lançamento"
    # Prosa vazia vira `None`, e não `""` — o padrão desta função.
    assert etapas[3102].erro is None

    achados = {
        row.external_id: row
        for row in db_session.execute(
            select(Finding).where(Finding.organization_id == project.organization_id)
        ).scalars()
    }
    assert achados[401].epistemic_status is EpistemicStatus.fact
    assert achados[401].process_id == processo.id
    assert achados[401].step_id == etapas[3102].id
    assert achados[401].evidences[0]["kind"] == "observation"
    # A lacuna declarada atravessa e não é omitida — é o que o cliente precisa ver
    # para saber o que **ainda não se sabe** sobre o próprio processo.
    assert achados[402].epistemic_status is EpistemicStatus.unknown
    assert achados[402].confidence is None
    assert achados[402].evidences == []

    hipotese = db_session.execute(
        select(SolutionHypothesis).where(
            SolutionHypothesis.organization_id == project.organization_id
        )
    ).scalar_one()
    assert hipotese.external_id == 701
    assert hipotese.expected_effect == "70% das notas sem toque humano"


@pytest.mark.integration
def test_a_projecao_liga_as_quatro_listas_pelos_ids_da_origem(
    db_session: Session,
) -> None:
    """O casamento entre as listas é pelo id **da origem**, como em ``KpiOut``.

    É o que dispensa uma tabela de tradução no navegador — e o que faz o uuid local,
    que é recriado a cada webhook, não sair daqui.
    """
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=9003, client_id=9002)
    )
    dashboard = biahflow.build_dashboard(db_session, project)

    achado = _projected(dashboard, "findings", 401)
    assert achado["process_id"] == 301
    assert achado["step_id"] == 3102
    assert achado["epistemic_status"] == "fact"

    dor = _projected(dashboard, "pain_points", 501)
    assert dor["finding_ids"] == [401, 402]
    assert dor["impact_estimate"] == 32000.0

    # Impacto **não quantificado** é `None`, e nunca zero: "R$ 0" seria a tela
    # afirmando um tamanho que ninguém mediu (a regra do `target` do KPI).
    assert _projected(dashboard, "pain_points", 502)["impact_estimate"] is None

    oportunidade = _projected(dashboard, "improvement_opportunities", 601)
    assert oportunidade["pain_point_ids"] == [501]
    assert oportunidade["priority_assessment"] == {
        "version": 2,
        "score": 82,
        "dimensions": {
            "impact": 5,
            "evidence_strength": 4,
            "feasibility": 3,
            "time_to_value": 4,
            "economics": 5,
        },
    }
    assert oportunidade["solution_hypotheses"][0]["id"] == 701

    processo = _projected(dashboard, "processes", 301)
    assert [step["id"] for step in processo["steps"]] == [3101, 3102]
    assert processo["steps"][0]["sistema"] == "ERP"


@pytest.mark.integration
def test_o_backlog_vem_ordenado_por_score_e_quem_nao_tem_nota_vai_para_o_fim(
    db_session: Session,
) -> None:
    """A ordem nasce na API, e ``NULLS LAST`` não é zero.

    Sem o ``NULLS LAST``, quem ninguém avaliou apareceria **antes** de quem tirou 82
    num ``ORDER BY ... DESC`` do Postgres (nulo é o maior por padrão) — o backlog
    abriria pelo item sobre o qual não há juízo nenhum.
    """
    payload = _snapshot(biahflow_project_id=9005, client_id=9004)
    # A não avaliada vem **primeiro** no payload, para a ordem não passar por
    # acidente de ordem de chegada.
    payload["improvement_opportunities"].reverse()
    project = biahflow.sync_snapshot(db_session, payload)
    dashboard = biahflow.build_dashboard(db_session, project)

    assert [item["id"] for item in dashboard["improvement_opportunities"]] == [601, 602]
    assert dashboard["improvement_opportunities"][1]["priority_assessment"] is None


@pytest.mark.integration
def test_um_fato_sem_evidencia_e_rebaixado_a_hipotese(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """O **invariante 9** do Language Map, conferido deste lado (ADR 0086).

    O produtor garante que um ``fact`` tem evidência revisada. Esta asserção existe
    apesar disso, e não por desconfiança: um fato sem lastro na tela do cliente é a
    afirmação sem evidência que a regra 3 do `AGENTS.md` proíbe ao assistente, aqui
    na voz do levantamento — e a regressão do outro lado chegaria aqui em silêncio.

    Cai o **rótulo**, não o achado: o cliente vê a afirmação como hipótese, que é o
    que ela comprovadamente é. É o desenho do ``outcome_without_baseline`` da ADR
    0085 aplicado ao Discovery.
    """
    payload = _snapshot(biahflow_project_id=9007, client_id=9006)
    _finding(payload, 401)["evidences"] = []

    with caplog.at_level(logging.WARNING, logger="portal_api.integrations.biahflow"):
        project = biahflow.sync_snapshot(db_session, payload)
    dashboard = biahflow.build_dashboard(db_session, project)

    achado = _projected(dashboard, "findings", 401)
    assert achado["epistemic_status"] == "hypothesis"
    assert achado["statement"] == "A conferência é feita duas vezes pela mesma pessoa."

    assert [
        record.reason
        for record in caplog.records
        if record.getMessage() == "projection.discovery_rejected"
    ] == ["fact_without_evidence"]


@pytest.mark.integration
def test_um_estado_epistemico_desconhecido_vira_lacuna_e_nunca_fato(
    db_session: Session,
) -> None:
    """Vocabulário novo do outro lado não derruba o sync **e não vira afirmação**.

    É a regra do ``PROJECT_STATUS_MAP`` com o padrão invertido de propósito: lá cair
    em ``discovery`` é um palpite barato; aqui cair em ``fact`` faria o portal
    promover a fato o que ninguém revisou, que é a regra 1 da §3 ao contrário.
    """
    payload = _snapshot(biahflow_project_id=9009, client_id=9008)
    _finding(payload, 401)["epistemic_status"] = "corroborated"

    project = biahflow.sync_snapshot(db_session, payload)
    dashboard = biahflow.build_dashboard(db_session, project)

    assert _projected(dashboard, "findings", 401)["epistemic_status"] == "unknown"


@pytest.mark.integration
def test_um_vinculo_que_nao_resolve_grava_nulo_e_nao_derruba_o_sync(
    db_session: Session,
) -> None:
    """Resolução parcial: o produtor publica os agregados separadamente.

    Um achado pode apontar para um processo que ninguém publicou, e uma dor pode
    citar um achado que não veio. Nos dois casos o vínculo cai e a **linha fica** —
    perder a proveniência é melhor que perder o conteúdo, que é o argumento do
    ``SET NULL`` de ``Decision.meeting_id``.
    """
    payload = _snapshot(biahflow_project_id=9011, client_id=9010)
    _finding(payload, 401)["process_id"] = 999  # processo não publicado
    _finding(payload, 401)["step_id"] = 9999
    _pain(payload, 501)["finding_ids"] = [401, 888]  # 888 não veio no payload
    _opportunity(payload, 601)["pain_point_ids"] = [501, 777]

    project = biahflow.sync_snapshot(db_session, payload)
    dashboard = biahflow.build_dashboard(db_session, project)

    achado = _projected(dashboard, "findings", 401)
    assert achado["process_id"] is None
    assert achado["step_id"] is None
    assert achado["statement"]  # o achado continua de pé

    assert _projected(dashboard, "pain_points", 501)["finding_ids"] == [401]
    assert _projected(dashboard, "improvement_opportunities", 601)["pain_point_ids"] == [
        501
    ]


@pytest.mark.integration
def test_um_id_repetido_na_lista_de_vinculos_nao_duplica_a_ligacao(
    db_session: Session,
) -> None:
    """A chave primária do par recusaria, e a desduplicação é o que a antecede.

    Sem ela um payload com id repetido derrubaria o snapshot inteiro do projeto por
    causa de uma lista mal formada — que é o oposto do que esta ingestão faz com
    tudo o mais que chega torto.
    """
    payload = _snapshot(biahflow_project_id=9013, client_id=9012)
    _pain(payload, 501)["finding_ids"] = [401, 401, 402]

    project = biahflow.sync_snapshot(db_session, payload)
    dashboard = biahflow.build_dashboard(db_session, project)

    assert _projected(dashboard, "pain_points", 501)["finding_ids"] == [401, 402]


@pytest.mark.integration
def test_uma_linha_malformada_nao_derruba_o_sync(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """Sem identidade, sem rótulo ou sem estado, a linha não é a coisa que ela diz ser.

    Recusar **a linha** é melhor que 500 no webhook, que derrubaria o snapshot
    inteiro do projeto por causa dela — a regra que ``value_ledger`` já escreveu.
    """
    payload = _snapshot(biahflow_project_id=9015, client_id=9014)
    payload["pain_points"].append(
        {"id": 503, "title": "Sem estado", "status": "", "finding_ids": []}
    )
    payload["improvement_opportunities"].append({"id": None, "title": "Sem identidade"})

    with caplog.at_level(logging.WARNING, logger="portal_api.integrations.biahflow"):
        project = biahflow.sync_snapshot(db_session, payload)
    dashboard = biahflow.build_dashboard(db_session, project)

    assert [item["id"] for item in dashboard["pain_points"]] == [501, 502]
    assert [item["id"] for item in dashboard["improvement_opportunities"]] == [601, 602]
    assert sorted(
        record.scope
        for record in caplog.records
        if record.getMessage() == "projection.discovery_rejected"
    ) == ["improvement_opportunity", "pain_point"]


# --- o escopo é a conta -----------------------------------------------------


@pytest.mark.integration
def test_os_dois_projetos_da_mesma_conta_veem_o_mesmo_discovery(
    db_session: Session,
) -> None:
    """O fan-out, e a razão de a substituição ser escopada por organização.

    O produtor lê o Discovery por Account e manda a lista completa no snapshot de
    **todo** projeto dela. Se a substituição fosse por projeto, a mesma dor existiria
    uma vez por irmão e o backlog contaria a mesma oportunidade duas vezes.
    """
    primeiro = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=9017, client_id=9016)
    )
    segundo = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=9018, client_id=9016)
    )
    assert primeiro.id != segundo.id
    assert primeiro.organization_id == segundo.organization_id

    # Uma linha por agregado, e não duas: o segundo sync substituiu o primeiro.
    for model in (Process, Finding, PainPoint, ImprovementOpportunity):
        linhas = db_session.execute(
            select(model.external_id)
            .where(model.organization_id == primeiro.organization_id)
            .order_by(model.external_id)
        ).scalars().all()
        assert len(linhas) == len(set(linhas)), model.__tablename__

    de_um = biahflow.build_dashboard(db_session, primeiro)
    do_outro = biahflow.build_dashboard(db_session, segundo)
    for key in biahflow.DISCOVERY_KEYS:
        assert de_um[key] == do_outro[key], key
    assert [item["id"] for item in de_um["pain_points"]] == [501, 502]


@pytest.mark.integration
def test_a_projecao_nao_alcanca_o_discovery_de_outra_conta(
    db_session: Session,
) -> None:
    """O filtro explícito por organização, que é o que protege o **produtor**.

    A policy da 0041 guarda o caminho de requisição; esta consulta roda sob
    ``portal_system``, que é ``BYPASSRLS``, e sem o ``where`` por organização — e sem
    o ``in_`` sobre os uuids da conta nas duas tabelas de ligação — o dashboard de um
    cliente listaria o Discovery de outro. É a regra 1 do `AGENTS.md` no lugar em que
    a segunda barreira não está de pé.
    """
    acme = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=9021, client_id=9020)
    )
    outra = _snapshot(biahflow_project_id=9023, client_id=9022)
    for item in outra["processes"]:
        item["id"] += 1000
    for item in outra["findings"]:
        item["id"] += 1000
    for item in outra["pain_points"]:
        item["id"] += 1000
        item["finding_ids"] = [value + 1000 for value in item["finding_ids"]]
    for item in outra["improvement_opportunities"]:
        item["id"] += 1000
        item["pain_point_ids"] = [value + 1000 for value in item["pain_point_ids"]]
    globex = biahflow.sync_snapshot(db_session, outra)
    assert acme.organization_id != globex.organization_id

    dashboard = biahflow.build_dashboard(db_session, acme)

    assert [item["id"] for item in dashboard["processes"]] == [301]
    assert [item["id"] for item in dashboard["findings"]] == [401, 402]
    assert [item["id"] for item in dashboard["pain_points"]] == [501, 502]
    assert _projected(dashboard, "pain_points", 501)["finding_ids"] == [401, 402]
    assert [item["id"] for item in dashboard["improvement_opportunities"]] == [601, 602]
    assert _projected(dashboard, "improvement_opportunities", 601)["pain_point_ids"] == [
        501
    ]


# --- silêncio e afirmação ---------------------------------------------------


@pytest.mark.integration
def test_um_biahflow_anterior_a_fatia_nao_quebra_e_nao_apaga_nada(
    db_session: Session,
) -> None:
    """**A ausência das quatro chaves é silêncio**, e é a metade que mais custa errar.

    Um Biahflow anterior a esta fatia manda um corpo sem elas. Tratar isso como lista
    vazia apagaria o Discovery de toda conta a cada webhook antigo — e o cliente veria
    a aba esvaziar sem que ninguém tivesse despublicado nada.
    """
    payload = _snapshot(biahflow_project_id=9025, client_id=9024)
    project = biahflow.sync_snapshot(db_session, payload)
    assert biahflow.build_dashboard(db_session, project)["processes"]

    antigo = _snapshot(biahflow_project_id=9025, client_id=9024)
    for key in biahflow.DISCOVERY_KEYS:
        antigo.pop(key)
    biahflow.sync_snapshot(db_session, antigo)

    dashboard = biahflow.build_dashboard(db_session, project)
    assert [item["id"] for item in dashboard["processes"]] == [301]
    assert [item["id"] for item in dashboard["improvement_opportunities"]] == [601, 602]


@pytest.mark.integration
def test_uma_lista_vazia_e_afirmacao_e_despublica(db_session: Session) -> None:
    """A outra metade: presente e vazia é o produtor dizendo que nada está publicado.

    Sem esta distinção, despublicar no Pulse não teria como chegar até aqui — o que
    saiu de lá continuaria na tela do cliente para sempre, que é o defeito da ADR
    0036 na direção do Discovery.
    """
    payload = _snapshot(biahflow_project_id=9027, client_id=9026)
    project = biahflow.sync_snapshot(db_session, payload)
    assert biahflow.build_dashboard(db_session, project)["findings"]

    despublicado = _snapshot(biahflow_project_id=9027, client_id=9026)
    for key in biahflow.DISCOVERY_KEYS:
        despublicado[key] = []
    biahflow.sync_snapshot(db_session, despublicado)

    dashboard = biahflow.build_dashboard(db_session, project)
    for key in biahflow.DISCOVERY_KEYS:
        assert dashboard[key] == [], key


@pytest.mark.integration
def test_o_dashboard_de_um_projeto_sem_discovery_traz_as_quatro_listas_vazias(
    db_session: Session,
) -> None:
    """O estado normal de hoje, e ele não é falha.

    O Pulse ainda não tem tela de publicar, então nada atravessa até alguém publicar
    à mão. As quatro chaves existem e são listas vazias — nunca ``null`` —, porque
    "nada publicado ainda" e "não sei" dizem coisas diferentes e só a primeira a tela
    sabe desenhar.
    """
    payload = _snapshot(biahflow_project_id=9029, client_id=9028)
    for key in biahflow.DISCOVERY_KEYS:
        payload.pop(key)

    project = biahflow.sync_snapshot(db_session, payload)
    dashboard = biahflow.build_dashboard(db_session, project)

    for key in biahflow.DISCOVERY_KEYS:
        assert dashboard[key] == [], key
