"""O harness de carga, testado pelas partes que não precisam de carga (ADR 0022).

Existe pela lição que a ADR 0021 aprendeu do jeito caro: o `AnthropicResponder`
passou uma fase inteira sendo código que **nenhum teste executava**, e foi só ao
executá-lo que apareceram o `max_tokens` que truncava e o `answerFor()` que
inventava citação. Um gerador de carga que ninguém roda entre execuções de carga
está exatamente nessa posição — e a hora em que se descobre que ele quebrou é a
hora em que se precisa dele.

O que **não** se testa aqui é a carga: um teste que mede vazão em CI mede o
runner. O que se testa é a aritmética e as recusas, que é onde os defeitos deste
tipo de ferramenta moram.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_harness():
    """Importa `scripts/loadtest.py`, que não é pacote e nem deve ser.

    Ele é operação, como o `backup.sh` (ADR 0019): mora em `scripts/`, não é
    importado por nada em produção, e transformá-lo em módulo de `portal_api` só
    para o teste alcançá-lo trocaria a arrumação certa por conveniência de teste.
    """

    spec = importlib.util.spec_from_file_location(
        "loadtest", REPO_ROOT / "scripts" / "loadtest.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["loadtest"] = module
    spec.loader.exec_module(module)
    return module


harness = _load_harness()


def test_the_harness_still_imports() -> None:
    """A metade mais barata do teste, e a que teria pego mais defeitos.

    A primeira versão deste script montava o engine com um `create_engine` cru e
    não enxergava tabela nenhuma, porque quem fixa o `search_path` em
    `portal,public` é a fábrica de sessão do projeto (ADR 0010).
    """

    assert callable(harness.main)
    assert harness.QUESTIONS


def test_percentiles_are_computed_on_the_answers_and_not_on_the_refusals() -> None:
    tally = harness.Tally()
    tally.record(200, 100.0, None)
    tally.record(200, 300.0, None)
    tally.record(429, 1.0, "30")

    assert tally.ok == 2
    assert tally.rate_limited == 1
    assert harness.percentile(tally.latencies_ms, 50) == 100.0
    assert len(tally.latencies_ms) == 2, "um 429 não é uma resposta e não entra no percentil"


def test_the_two_refusals_are_told_apart_by_the_retry_after() -> None:
    """A API dá o mesmo 429 para ritmo e para teto (ADR 0021 + 0022).

    O corpo de um 429 é deliberadamente opaco no resto da API, então o que separa
    os dois é a ordem de grandeza do cabeçalho — a mesma regra que a tela usa. Se
    o harness confundisse os dois, um relatório cheio de "sem cota" pareceria um
    problema de vazão, e alguém acrescentaria máquina para resolver um teto.
    """

    tally = harness.Tally()
    tally.record(429, 1.0, "42")  # janela de um minuto
    tally.record(429, 1.0, "864000")  # o resto do mês

    assert tally.rate_limited == 1
    assert tally.quota_exhausted == 1


def test_a_429_without_a_retry_after_counts_as_the_rate_window() -> None:
    """Degrada para o caso frequente em vez de levantar. Um harness que quebra
    por causa de um cabeçalho ausente perde a execução inteira — e a execução
    custa dinheiro."""

    tally = harness.Tally()
    tally.record(429, 1.0, None)

    assert tally.rate_limited == 1
    assert tally.quota_exhausted == 0


def test_an_empty_run_does_not_divide_by_zero() -> None:
    assert harness.percentile([], 95) is None


def test_the_budget_is_fail_closed_when_a_real_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A exigência que o `ROADMAP.md` fazia ao adiar a carga, virada em código.

    Com chave configurada cada pergunta custa dinheiro, e rodar sem orçamento
    declarado é a única forma de a execução sair cara por engano. Recusar é a
    forma do `BACKUP_AGE_RECIPIENT`, que prefere não fazer backup a fazer um em
    texto claro.
    """

    import asyncio

    from portal_api.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-de-mentira")
    args = harness.parse_args(["--duration", "1"])
    assert args.budget_usd is None

    with pytest.raises(SystemExit) as raised:
        asyncio.run(harness.run(args))

    assert "--budget-usd" in str(raised.value)


def test_a_declared_budget_lets_it_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """A contraprova do anterior: sem ela, um harness quebrado de outro jeito
    passaria pelo teste acima por acidente."""

    from portal_api.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-de-mentira")
    args = harness.parse_args(["--duration", "1", "--budget-usd", "1.50"])

    assert args.budget_usd == 1.50
