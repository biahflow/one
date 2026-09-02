"""O KPI do projeto e o Value Ledger do mandato (Language Map v1.1, ADR 0085).

Cinco coisas são provadas aqui, e as cinco são sobre **não afirmar o que não foi
medido**:

1. o KPI e o razão atravessam o snapshot e chegam à projeção;
2. as **duas nulidades** da medição sobrevivem, e nenhuma delas vira zero — é o
   critério (4) da issue #89, escrito como asserção;
3. o **invariante 11** do Language Map ("todo texto voltado ao cliente que diga
   Outcome aponta para um Measurement com Baseline comparável") vale deste lado,
   ainda que o produtor o garanta;
4. o **invariante 12** ("``ValueLedgerEntry`` aponta para um Outcome e registra
   método de atribuição") é conferido na ingestão, e a entrada sem método não
   entra;
5. o razão é escopado por **Engagement** e não por projeto: dois projetos do mesmo
   mandato veem a mesma entrada, e um sync sem programa não apaga o que outro
   gravou.

A isolação entre tenants tem casa própria em ``test_rls_isolation.py``: aqui o
``db_session`` roda sob ``portal_system``, que é ``BYPASSRLS`` por desenho — o
mesmo recorte que ``test_engagement.py`` declara.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api.integrations import biahflow
from portal_api.models import DigitalEmployee, Kpi, ValueLedgerEntry
from test_biahflow_integration import _snapshot
from test_engagement import _with_engagement


def _kpi(payload: dict[str, Any], external_id: int) -> dict[str, Any]:
    """O item de ``kpis[]`` com aquele id — os testes editam a fixture pelo id."""
    return next(item for item in payload["kpis"] if item["id"] == external_id)


def _projected(dashboard: dict[str, Any], external_id: int) -> dict[str, Any]:
    return next(item for item in dashboard["kpis"] if item["id"] == external_id)


# --- unidade: a normalização da medição -------------------------------------
#
# Puras, sem banco: `_measurement` é a função que decide se há objeto, e é ela que
# carrega a distinção que o resto da fatia depende de preservar.


def test_a_medicao_ausente_e_a_medicao_sem_numero_sao_coisas_diferentes() -> None:
    """As duas nulidades do produtor, no único ponto em que elas se decidem.

    ``None`` é "não definida" e some; ``{"value": None, …}`` é "a janela existe e
    ninguém mediu ainda" e **sobrevive** com o valor nulo dentro. Colapsar as duas
    aqui faria toda a fatia acima perder a distinção sem nada ficar vermelho.
    """
    assert biahflow._measurement(None) is None
    assert biahflow._measurement({}) is None

    window = biahflow._measurement(
        {"value": None, "period_start": "2026-07-01", "period_end": None,
         "measured_at": None, "confidence": None}
    )
    assert window is not None
    assert window["value"] is None  # e **não** Decimal("0")


def test_uma_data_ilegivel_apaga_a_medicao_e_nao_derruba_o_sync() -> None:
    """A data da medição tolera lixo, e ``_parse_date`` **não** — a diferença é o uso.

    Onde a data é o fato (``decided_on`` de uma decisão), uma ilegível é defeito de
    contrato e falhar alto é a resposta. Aqui ela é a **condição de existência** da
    medição, e a resposta melhor é a mesma de "a origem não mandou": o KPI atravessa
    sem aquela leitura, em vez de o snapshot inteiro do projeto morrer por causa dela.
    """
    assert biahflow._measurement({"value": 1, "period_start": "31/07/2026"}) is None
    legivel = biahflow._measurement(
        {"value": 1, "period_start": "2026-07-01", "measured_at": "ontem"}
    )
    assert legivel is not None
    assert legivel["measured_at"] is None  # a hora ruim cai, a janela fica


def test_o_numero_da_medicao_nunca_e_zero_por_omissao() -> None:
    """Valor ilegível é lacuna, não zero — o critério (4) da issue #89 na raiz."""
    assert biahflow._decimal(None) is None
    assert biahflow._decimal("") is None
    assert biahflow._decimal("nao-e-numero") is None
    assert biahflow._decimal(True) is None  # `bool` é `int` em Python, e não é medida
    assert biahflow._decimal(0) is not None  # zero medido continua sendo zero


# --- integração: a ingestão -------------------------------------------------


@pytest.mark.integration
def test_o_snapshot_cria_os_kpis_do_projeto(db_session: Session) -> None:
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=8501, client_id=8500)
    )

    indicators = {
        row.external_id: row
        for row in db_session.execute(
            select(Kpi).where(Kpi.project_id == project.id)
        ).scalars()
    }
    assert set(indicators) == {12, 15}

    horas = indicators[12]
    assert horas.name == "Horas de conciliação"
    assert horas.unit == "hours"
    assert horas.direction == "down"
    assert horas.cadence == "monthly"
    assert float(horas.target) == 20.0
    assert float(horas.baseline_value) == 72.0
    assert horas.baseline_confidence == 80
    assert float(horas.outcome_value) == 21.5
    assert horas.outcome_period_end is not None
    assert len(horas.monitoring) == 1

    # A prosa vazia vira `None`, e não `""` — o padrão de `description` e
    # `rationale` nesta função.
    assert indicators[15].definition is None
    assert indicators[15].formula is None
    assert indicators[15].monitoring == []


@pytest.mark.integration
def test_a_lacuna_de_medicao_chega_como_lacuna_e_nunca_como_zero(
    db_session: Session,
) -> None:
    """O critério (4) da issue #89, ponta a ponta.

    O KPI 15 traz o Outcome com **janela e sem número**: a janela existe, ninguém
    mediu. Na projeção isso é um objeto com ``value: null`` — e não a ausência do
    objeto, que significaria "não há Outcome definido", nem ``0.0``, que seria a
    tela afirmando uma medição que ninguém fez.
    """
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=8503, client_id=8502)
    )
    dashboard = biahflow.build_dashboard(db_session, project)

    divergencias = _projected(dashboard, 15)
    assert divergencias["outcome"] is not None
    assert divergencias["outcome"]["value"] is None
    assert divergencias["outcome"]["period_start"] == "2026-07-01"
    # Janela ainda aberta: `period_end` nulo dentro de um objeto que existe.
    assert divergencias["outcome"]["period_end"] is None
    # Sem meta é `None`, nunca 0.0.
    assert divergencias["target"] is None

    # E o KPI medido continua trazendo número — sem isto a asserção acima passaria
    # com a projeção zerando tudo.
    assert _projected(dashboard, 12)["outcome"]["value"] == 21.5
    assert _projected(dashboard, 12)["baseline"]["value"] == 72.0


@pytest.mark.integration
def test_a_baseline_ausente_e_a_baseline_sem_numero_chegam_diferentes(
    db_session: Session,
) -> None:
    """As duas nulidades, agora na Baseline e atravessando o banco.

    Sem esta asserção a coluna ``baseline_period_start`` seria só mais uma data, e
    a regra "o objeto existe **sse** há janela" — que é o que dispensa uma coluna
    booleana — não teria prova executada.
    """
    payload = _snapshot(biahflow_project_id=8505, client_id=8504)
    # (a) baseline nunca definida: a chave vem nula, e com ela cai o Outcome (ver o
    # teste do invariante 11 abaixo — aqui só interessa a Baseline).
    _kpi(payload, 15)["baseline"] = None
    _kpi(payload, 15)["outcome"] = None
    # (b) baseline com janela e sem número.
    _kpi(payload, 12)["baseline"] = {
        "value": None, "period_start": "2026-03-01", "period_end": "2026-03-31",
        "measured_at": None, "confidence": None,
    }
    project = biahflow.sync_snapshot(db_session, payload)
    dashboard = biahflow.build_dashboard(db_session, project)

    assert _projected(dashboard, 15)["baseline"] is None
    medida = _projected(dashboard, 12)["baseline"]
    assert medida is not None and medida["value"] is None
    assert medida["period_start"] == "2026-03-01"


@pytest.mark.integration
def test_um_outcome_sem_baseline_nao_atravessa(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """O **invariante 11** do Language Map, conferido deste lado (ADR 0085).

    O produtor garante que ``outcome`` nunca vem sem ``baseline`` do mesmo KPI.
    Esta asserção existe apesar disso, e não por desconfiança: o Outcome sozinho na
    tela é um número sem régua — "21,5h" não diz nada até estar ao lado das 72h de
    onde se partiu —, e a regressão do outro lado chegaria aqui em silêncio.

    Cai o **Outcome**, não o KPI: definição, unidade e meta continuam valendo, e o
    cliente vê o indicador sem o resultado em vez de não ver o indicador.
    """
    payload = _snapshot(biahflow_project_id=8507, client_id=8506)
    _kpi(payload, 12)["baseline"] = None

    with caplog.at_level(logging.WARNING, logger="portal_api.integrations.biahflow"):
        project = biahflow.sync_snapshot(db_session, payload)
    dashboard = biahflow.build_dashboard(db_session, project)

    horas = _projected(dashboard, 12)
    assert horas["baseline"] is None
    assert horas["outcome"] is None
    assert horas["name"] == "Horas de conciliação"  # o KPI sobreviveu
    assert horas["target"] == 20.0

    # E a queda é contada, com o motivo — a linha do `alerts.md` existe para ela.
    assert [
        record.reason
        for record in caplog.records
        if record.getMessage() == "projection.kpi_rejected"
    ] == ["outcome_without_baseline"]


@pytest.mark.integration
def test_um_kpi_sem_id_ou_sem_nome_nao_derruba_o_sync(db_session: Session) -> None:
    """Vocabulário novo do outro lado não derruba o sync — a regra do ``PROJECT_STATUS_MAP``.

    Aqui aplicada à **forma** do item e não ao valor dele: sem id não há identidade
    que sobreviva à substituição, e sem nome não há o que rotular na tela.
    """
    payload = _snapshot(biahflow_project_id=8509, client_id=8508)
    payload["kpis"] = [
        {"id": None, "name": "Sem identidade"},
        {"id": 77, "name": "   "},
        _kpi(payload, 12),
    ]

    project = biahflow.sync_snapshot(db_session, payload)

    assert [item["id"] for item in biahflow.build_dashboard(db_session, project)["kpis"]] == [12]


@pytest.mark.integration
def test_o_funcionario_digital_referencia_kpis_sem_perder_os_campos_legados(
    db_session: Session,
) -> None:
    """A lista nova é **aditiva** (ADR 0085): os quatro campos legados continuam."""
    project = biahflow.sync_snapshot(
        db_session, _snapshot(biahflow_project_id=8511, client_id=8510)
    )

    employee = db_session.execute(
        select(DigitalEmployee).where(DigitalEmployee.project_id == project.id)
    ).scalar_one()
    assert employee.kpi_external_ids == [12, 15]
    assert employee.kpi_label == "Conciliação"
    assert employee.kpi_value == "80%"
    assert float(employee.hours_saved_month) == 120.0
    assert float(employee.roi_month) == 14000.0

    projected = biahflow.build_dashboard(db_session, project)["digital_employees"][0]
    assert projected["kpi_ids"] == [12, 15]
    assert projected["kpi_label"] == "Conciliação"
    assert projected["roi_month"] == 14000.0


@pytest.mark.integration
def test_um_biahflow_anterior_a_fatia_nao_quebra_e_nao_afirma_nada(
    db_session: Session,
) -> None:
    """Chave ausente é ausência de afirmação — o padrão de todo este arquivo.

    Um Biahflow anterior a esta fatia manda o corpo sem ``kpis``, sem
    ``value_ledger`` e sem ``kpi_ids``. Nada disso pode virar erro, e nada pode
    virar valor inventado: as listas nascem vazias.
    """
    payload = _with_engagement(
        _snapshot(biahflow_project_id=8513, client_id=8512),
        engagement_id=8514,
        name="Programa sem razão",
    )
    payload.pop("kpis")
    payload.pop("value_ledger")
    payload["digital_employees"][0].pop("kpi_ids")

    project = biahflow.sync_snapshot(db_session, payload)
    dashboard = biahflow.build_dashboard(db_session, project)

    assert dashboard["kpis"] == []
    assert dashboard["value_ledger"] == []
    assert dashboard["digital_employees"][0]["kpi_ids"] == []


# --- integração: o razão do mandato -----------------------------------------


@pytest.mark.integration
def test_o_value_ledger_chega_com_metodo_de_atribuicao(db_session: Session) -> None:
    """O **invariante 12**: a entrada aponta para um Outcome e registra o método."""
    project = biahflow.sync_snapshot(
        db_session,
        _with_engagement(
            _snapshot(biahflow_project_id=8521, client_id=8520),
            engagement_id=8522,
            name="Transformação Financeira",
        ),
    )
    dashboard = biahflow.build_dashboard(db_session, project)

    entries = {entry["id"]: entry for entry in dashboard["value_ledger"]}
    assert set(entries) == {3, 4}
    economia = entries[3]
    assert economia["value_type"] == "cost_saving"
    assert economia["amount"] == 48000.0
    assert economia["quantity"] == 606.0
    assert economia["period_start"] == "2026-07-01"
    assert economia["period_end"] == "2026-07-31"
    assert economia["attribution_method"].startswith("Diferença Baseline→Outcome")
    assert economia["kpi_id"] == 12
    assert economia["outcome_measured_at"] is not None

    # A segunda aponta para um KPI que **não existe neste projeto**, e isso é o
    # caso normal: a entrada é do mandato e o indicador pode viver num irmão. A
    # projeção a entrega igual, com o id solto, para a tela decidir o que mostrar.
    assert entries[4]["kpi_id"] == 41
    assert 41 not in {item["id"] for item in dashboard["kpis"]}
    assert entries[4]["outcome_measured_at"] is None


@pytest.mark.integration
def test_uma_entrada_sem_metodo_de_atribuicao_nao_entra(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """O invariante 12 como **recusa**, e não como campo opcional.

    Uma quantia sem a conta que a atribui é um número solto na tela do cliente — a
    afirmação que a §5 do Language Map bane. Recusar a linha é melhor que gravá-la
    muda, porque uma coluna nula aqui viraria "R$ 48.000, sem explicação".
    """
    payload = _with_engagement(
        _snapshot(biahflow_project_id=8524, client_id=8523),
        engagement_id=8525,
        name="Programa com linha torta",
    )
    payload["value_ledger"][0]["attribution_method"] = "   "
    payload["value_ledger"][1]["amount"] = None

    with caplog.at_level(logging.WARNING, logger="portal_api.integrations.biahflow"):
        project = biahflow.sync_snapshot(db_session, payload)

    assert biahflow.build_dashboard(db_session, project)["value_ledger"] == []
    assert [
        record.reason
        for record in caplog.records
        if record.getMessage() == "projection.value_ledger_rejected"
    ] == ["malformed", "malformed"]


@pytest.mark.integration
def test_o_razao_e_do_mandato_e_os_dois_projetos_dele_veem_a_mesma_entrada(
    db_session: Session,
) -> None:
    """O escopo é **Engagement**, e é isto que o fan-out do produtor exige.

    O Pulse manda a lista completa do razão no snapshot de **cada** projeto do
    mandato. Guardá-la por projeto duplicaria cada real uma vez por irmão, e a soma
    do programa passaria a contar duas vezes o mesmo valor.
    """
    primeiro = biahflow.sync_snapshot(
        db_session,
        _with_engagement(
            _snapshot(biahflow_project_id=8531, client_id=8530),
            engagement_id=8532,
            name="Programa de dois projetos",
        ),
    )
    segundo = biahflow.sync_snapshot(
        db_session,
        _with_engagement(
            _snapshot(biahflow_project_id=8533, client_id=8530),
            engagement_id=8532,
            name="Programa de dois projetos",
        ),
    )
    assert primeiro.id != segundo.id
    assert primeiro.engagement_id == segundo.engagement_id

    # Duas passagens, **uma** cópia de cada entrada: o `DELETE` é por mandato.
    stored = db_session.execute(
        select(ValueLedgerEntry).where(
            ValueLedgerEntry.engagement_id == primeiro.engagement_id
        )
    ).scalars().all()
    assert sorted(entry.external_id for entry in stored) == [3, 4]

    # E os dois projetos projetam a mesma coisa, porque o valor é do programa.
    de_um = biahflow.build_dashboard(db_session, primeiro)["value_ledger"]
    do_outro = biahflow.build_dashboard(db_session, segundo)["value_ledger"]
    assert de_um == do_outro
    assert [entry["id"] for entry in de_um] == [3, 4]


@pytest.mark.integration
def test_um_sync_sem_programa_nao_apaga_o_razao_que_o_irmao_gravou(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """Ausência não é negação, e aqui ela custaria o razão inteiro do mandato.

    Um snapshot que não diz de qual Engagement o projeto é não afirma nada sobre o
    razão daquele Engagement. Como a tabela não tem ``project_id``, um ``DELETE``
    "do que veio neste sync" não teria escopo — apagaria o que o projeto irmão
    gravou corretamente, e o Value Ledger do cliente encolheria a cada webhook de
    um projeto mal configurado.
    """
    com_programa = biahflow.sync_snapshot(
        db_session,
        _with_engagement(
            _snapshot(biahflow_project_id=8541, client_id=8540),
            engagement_id=8542,
            name="Programa do irmão",
        ),
    )
    engagement_id = com_programa.engagement_id
    assert engagement_id is not None

    sem_programa = _snapshot(biahflow_project_id=8543, client_id=8540)
    sem_programa["project"].pop("engagement", None)
    with caplog.at_level(logging.WARNING, logger="portal_api.integrations.biahflow"):
        orfao = biahflow.sync_snapshot(db_session, sem_programa)

    assert orfao.engagement_id is None
    # O projeto sem programa não mostra razão nenhum — não há mandato a ler.
    assert biahflow.build_dashboard(db_session, orfao)["value_ledger"] == []
    # E o do irmão continua inteiro.
    assert [
        entry["id"]
        for entry in biahflow.build_dashboard(db_session, com_programa)["value_ledger"]
    ] == [3, 4]
    assert any(
        record.getMessage() == "projection.value_ledger_skipped"
        for record in caplog.records
    )


@pytest.mark.integration
def test_o_razao_e_substituido_por_inteiro_a_cada_passagem(db_session: Session) -> None:
    """Substituição integral, como marco e funcionário digital — só que por mandato.

    O produtor manda a lista **completa e atual**, então uma entrada que sai de lá
    tem de sair daqui: sem isto, um valor estornado continuaria somando na tela do
    cliente para sempre.
    """
    payload = _with_engagement(
        _snapshot(biahflow_project_id=8551, client_id=8550),
        engagement_id=8552,
        name="Programa que estorna",
    )
    project = biahflow.sync_snapshot(db_session, payload)
    assert len(biahflow.build_dashboard(db_session, project)["value_ledger"]) == 2

    payload["value_ledger"] = [payload["value_ledger"][0]]
    project = biahflow.sync_snapshot(db_session, payload)

    assert [
        entry["id"] for entry in biahflow.build_dashboard(db_session, project)["value_ledger"]
    ] == [3]
