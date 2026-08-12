"""O instrumento de comando/hora do Upstash (ADR 0045, ADR 0048).

A ADR 0045 fixou "comando/hora com a fila vazia" como condição para HML ser declarada
pronta e não deixou com o que medir. `scripts/redis_rate.py` é o instrumento; estes
casos exercitam o **núcleo puro** dele — a aritmética e as notas —, que é onde mora a
parte que decide se um número pode ser citado.

Nada aqui toca Redis. O que precisa de servidor é o smoke de ponta a ponta, que roda
contra o compose e cuja função é a mesma do smoke de 15 s do `loadtest.py` no CI: a
ferramenta não apodrecer. Uma medição de verdade não cabe num teste — ela leva quinze
minutos e depende do ambiente que veio medir.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_harness():
    """Importa `scripts/redis_rate.py`, que não é pacote e nem deve ser.

    Mesma razão do `test_loadtest_harness.py`: é operação (ADR 0019), mora em
    `scripts/`, não é importado por nada em produção, e transformá-lo em módulo de
    `portal_api` só para o teste alcançá-lo trocaria a arrumação certa por
    conveniência de teste.
    """

    spec = importlib.util.spec_from_file_location(
        "redis_rate", REPO_ROOT / "scripts" / "redis_rate.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["redis_rate"] = module
    spec.loader.exec_module(module)
    return module


harness = _load_harness()


def _amostra(comandos: int | None, filas: dict[str, int] | None = None):
    return harness.Amostra(
        momento=0.0, comandos=comandos, filas=filas if filas is not None else {"celery": 0}
    )


# --- o valor copiado do worker ------------------------------------------------


def test_the_polling_interval_did_not_drift_from_the_worker() -> None:
    """O intervalo é copiado do `worker.py`, e uma cópia sem guarda diverge.

    Copiado e não importado porque `worker.py` roda `preflight(settings)` no topo do
    módulo: um instrumento que **recusa subir** por causa do ambiente que veio medir
    seria o pior dos dois mundos. O preço da cópia é este caso — a forma do
    `test_seed_matches_realm.py`, que existe pela mesma razão.

    Se ele reprovar, o número que o relatório chama de "previsto pela ADR 0045" passou
    a descrever outro laço, e a comparação inteira deixa de valer.
    """
    fonte = (REPO_ROOT / "apps" / "api" / "src" / "portal_api" / "worker.py").read_text()
    achado = re.search(r'"polling_interval":\s*([\d.]+)', fonte)
    assert achado, "`polling_interval` sumiu do worker.py — o instrumento ficou sem referência"

    assert float(achado.group(1)) == harness.POLLING_INTERVAL_SEGUNDOS


# --- a aritmética -------------------------------------------------------------


def test_the_rate_extrapolates_the_window_to_an_hour() -> None:
    assert harness.comandos_por_hora(600, 60) == 36000.0
    assert harness.comandos_por_hora(0, 900) == 0.0


def test_a_window_that_did_not_pass_yields_no_number() -> None:
    """Zero segundos não é "zero comandos por hora": é ausência de medição."""
    assert harness.comandos_por_hora(10, 0) is None
    assert harness.comandos_por_hora(10, -1) is None


def test_a_counter_that_went_backwards_yields_no_number() -> None:
    """O Upstash pode reiniciar o contador, e um delta negativo não é uma taxa.

    Devolver um número negativo aqui seria pior que devolver nenhum: ele passaria pelo
    `is not None` de quem lê e apareceria no relatório como se fosse medição.
    """
    assert harness.comandos_por_hora(-5, 900) is None


def test_a_restarted_counter_is_not_a_quiet_window() -> None:
    """O defeito que a primeira versão deste script tinha, e que a medição pegou.

    O cálculo aparava o delta em zero. Um reinício do Upstash no meio da janela —
    contador voltando a um número menor — sairia como **zero comando por hora**, que
    passa pelo `is not None` de quem lê e vira, no relatório, a melhor notícia
    possível sobre o pior dado possível. São duas ausências diferentes e o relatório
    precisa distingui-las: sem `INFO` não há contador; andando para trás, houve
    reinício.
    """
    assert harness.delta_descontado(_amostra(9000), _amostra(12), proprios=4) is None

    # E o aparo em zero fica onde é honesto: servidor ocioso, bruto menor que os
    # nossos próprios comandos.
    assert harness.delta_descontado(_amostra(1000), _amostra(1002), proprios=4) == 0

    assert harness.delta_descontado(_amostra(1000), _amostra(2000), proprios=4) == 996


def test_no_info_is_told_apart_from_a_restart() -> None:
    assert harness.delta_descontado(_amostra(None), _amostra(None), proprios=4) is None

    notas = _notas(por_hora=None, contador_reiniciou=True)
    assert any("andou para trás" in n and "não é o mesmo" in n for n in notas)
    assert not any("recusou `INFO`" in n for n in notas)


def test_the_adr_budget_is_one_command_per_cycle_per_instance() -> None:
    """86400/5 = 17280, que é o "~17 mil" que a ADR 0045 escreveu."""
    assert harness.orcamento_do_laco(1) == 17280
    assert harness.orcamento_do_laco(2) == 34560


# --- as notas: onde mora a decisão de o número poder ser citado ---------------


def _notas(**kwargs) -> list[str]:
    base = dict(
        inicio=_amostra(1000),
        fim=_amostra(2000),
        duracao=900.0,
        proprios=4,
        instancias=1,
        por_hora=4000.0,
        is_upstash=True,
    )
    base.update(kwargs)
    inicio = base.pop("inicio")
    fim = base.pop("fim")
    return harness.montar_notas(inicio, fim, **base)


def test_a_non_upstash_target_says_so_first() -> None:
    """Contra o compose o número não é o que a ADR 0045 pede, e o relatório diz."""
    notas = _notas(is_upstash=False)
    assert "não é a medição que a ADR 0045 pede" in notas[0]


def test_the_compose_only_producers_are_named_only_on_the_compose() -> None:
    """Medido: no compose ocioso o total sai ~15× a previsão, e boa parte é de sonda.

    Os dois healthchecks do `docker-compose.yml` batem no broker em intervalo fixo e
    **não existem em HML** — o módulo do Cloud Run não declara sonda nenhuma. Sem esta
    nota, alguém dividiria o número do ensaio por um fator qualquer e o citaria como
    estimativa de HML, que é exatamente o uso que o relatório existe para impedir.
    """
    local = _notas(is_upstash=False)
    assert any("celery inspect ping" in n and "não extrapola" in n for n in local)

    upstash = _notas(is_upstash=True)
    assert not any("celery inspect ping" in n for n in upstash)


def test_a_refused_info_declares_the_absence_instead_of_inventing() -> None:
    """`skipped` não é `clean` (ADR 0017): sem `INFO`, não há número.

    O Upstash publica um subconjunto de comandos. O relatório precisa dizer que o
    número **não** foi produzido, senão a ausência dele parece um zero.
    """
    notas = _notas(inicio=_amostra(None), fim=_amostra(None), por_hora=None)
    assert any("recusou `INFO`" in n and "Nenhum número" in n for n in notas)


def test_a_queue_that_was_not_empty_invalidates_the_condition() -> None:
    """"Com a fila vazia" é a condição da ADR 0045, não um detalhe do procedimento."""
    notas = _notas(fim=_amostra(2000, {"celery": 3}))
    assert any("não** estava vazia" in n for n in notas)


def test_a_short_window_is_named_as_short() -> None:
    curta = _notas(duracao=60.0)
    assert any("curta" in n and "12 ciclos" in n for n in curta)

    media = _notas(duracao=600.0)
    assert any("sync do Drive" in n for n in media)

    longa = _notas(duracao=900.0)
    assert not any("curta" in n for n in longa)


def test_the_other_producers_are_always_named() -> None:
    """A nota que mais importa, e a que o instrumento não tem como descobrir sozinho.

    `INFO` conta comandos, não clientes. O `biahflow-scheduler` do outro produto
    aponta para o mesmo Upstash e nenhuma ADR contabilizou os comandos dele — um
    número medido com ele junto não é o número de um worker do portal, e quem citar o
    relatório depois precisa disso ao lado.
    """
    for notas in (_notas(), _notas(is_upstash=False), _notas(por_hora=None)):
        assert any("biahflow-scheduler" in n for n in notas)


def test_the_measurement_is_compared_against_what_the_adr_predicted() -> None:
    notas = _notas(por_hora=1440.0)  # 34.560/dia = 2× os 17.280 previstos
    comparacao = next(n for n in notas if "Previsto pela ADR 0045" in n)
    assert "2.0×" in comparacao
    assert "não continha" in comparacao


def test_without_a_number_there_is_nothing_to_compare() -> None:
    assert not any("Previsto pela ADR 0045" in n for n in _notas(por_hora=None))
