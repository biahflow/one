#!/usr/bin/env python
"""Comando/hora do Redis com a fila vazia (Fase 5, ADR 0045; instrumento na ADR 0048).

Mora em ``scripts/`` pela razão do ``backup.sh`` e do ``loadtest.py``: é
**operação**, não aplicação. Não sobe rota, não é importado pelo produto e roda
quando alguém decide rodar.

    PYTHONPATH=apps/api/src python scripts/redis_rate.py --duration 900 --out /tmp/redis.json

## Por que ele existe

A ADR 0045 pôs `polling_interval` em 5 s e escreveu, com estas palavras, que aquilo
era *"uma promessa a medir, não a acreditar"*: **o número que decide é comando/hora
com a fila vazia**, e a medição vem antes de HML ser declarada pronta. A ADR 0046
reafirmou a dívida. Até aqui não havia com o que medir — um `grep` por "comando/hora"
no repositório achava quatro linhas, todas em prosa.

## O que ele mede, e o que ele não mede

Mede o **banco inteiro**, por `INFO stats`/`total_commands_processed`, e não o nosso
processo. É deliberado, e é a única forma honesta: a conta do Upstash é por comando
do banco, e o banco tem mais produtores do que o worker do portal.

Não mede latência, não mede custo em dinheiro (o preço por comando é do painel, não
nosso) e **não substitui o painel** — corrobora-o. Se o servidor recusar `INFO`, o
relatório diz isso e não inventa um número: `skipped` não é `clean` (ADR 0017).

## A aritmética da ADR 0045 está incompleta, e é isso que este script expõe

Os ~17 mil comandos/dia por instância supõem **um comando por ciclo por instância**.
Quatro coisas ficam de fora daquela conta, e nenhum documento as contava:

1. O worker não roda com ``--without-gossip/--without-mingle/--without-heartbeat``,
   e os três falam com o broker sozinhos.
2. O **result backend é o mesmo Redis** (``worker.py``), então cada tarefa executada
   gera escrita e expiração além do consumo.
3. O **beat publica de verdade** mesmo com a fila vazia: o sync do Drive a cada
   15 min, a poda e o alerta de funil diários. "Fila vazia" não é "nada acontece".
4. O ``biahflow-scheduler`` do outro produto aponta para o **mesmo** Upstash. Nenhuma
   ADR contabilizou os comandos dele.

Por isso o relatório traz ``produtores`` e uma nota por condição: um número medido com
o scheduler do Biahflow junto não é o número de um worker do portal, e quem o citar
seis meses depois precisa disso escrito ao lado — a regra do ``loadtest.py``, que é a
do ``testing-strategy.md`` aplicada a uma medição.

## A janela

Curta demais mede ruído: com 5 s de intervalo, uma janela de 60 s contém 12 ciclos, e
um tique do beat no meio dela desloca o número em dezenas de por cento. O padrão é
15 min, que é também o período do sync do Drive — de propósito, para que a janela
contenha exatamente um daqueles tiques em vez de zero ou dois por sorteio.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import redis

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from portal_api.config import get_settings  # noqa: E402

#: A fila do Celery. Nenhuma tarefa deste projeto declara `queue=`, então todas caem
#: na default — e é o comprimento dela que "fila vazia" significa.
FILAS = ("celery",)

#: O mesmo valor de `broker_transport_options` em `apps/api/src/portal_api/worker.py`.
#: Copiado e não importado: importar `worker` roda `preflight(settings)` no topo do
#: módulo, e um instrumento de medição que **recusa subir** por causa do ambiente que
#: veio medir seria o pior dos dois mundos. `test_redis_rate.py` afirma que os dois
#: números não divergiram — é a forma do `test_seed_matches_realm.py`.
POLLING_INTERVAL_SEGUNDOS = 5.0

#: Quem fala com este Redis em HML, por `servicos.tf`. A lista é literal porque o
#: script não tem como descobri-la: `INFO` conta comandos, não clientes, e é
#: justamente essa cegueira que a nota sobre produtores existe para declarar.
PRODUTORES = (
    "portal-worker (laço ocioso + resultado das tarefas)",
    "portal-beat (publica: drive-sync 15min, poda 24h, alerta de funil 24h)",
    "portal-api (PING por chamada de /health/ready, sem pool)",
    "biahflow-scheduler (outro produto, mesmo REDIS_URL)",
)

#: Só no compose, e é por isso que o número local **não** extrapola para HML: as duas
#: sondas do `docker-compose.yml` batem no broker em intervalo fixo, e em HML não há
#: `startup_probe` nem `liveness_probe` declarados em `servico-cloudrun/`. Medido: no
#: compose ocioso o total sai uma ordem de grandeza acima do previsto, e boa parte é
#: daqui. Nomeado para ninguém citar o ensaio como se fosse a medição.
PRODUTORES_SO_DO_COMPOSE = (
    "healthcheck do worker (`celery inspect ping` a cada 30s, pela fila de controle)",
    "healthcheck da API (`/health/ready` a cada 15s, uma conexão e um PING por vez)",
)


@dataclass
class Amostra:
    """Um instante: o contador do servidor e o comprimento das filas."""

    momento: float
    comandos: int | None
    filas: dict[str, int]

    @property
    def vazia(self) -> bool:
        return all(n == 0 for n in self.filas.values())


def comandos_por_hora(delta: int, segundos: float) -> float | None:
    """Extrapola para uma hora. `None` quando não há o que extrapolar.

    Sem piso de janela aqui de propósito: quem decide se a janela foi curta demais é
    a nota, que diz o número **e** a condição. Um piso silencioso devolveria `None` e
    quem chamou acharia que o servidor recusou `INFO`, que é outra coisa.
    """
    if delta < 0 or segundos <= 0:
        return None
    return round(delta * 3600 / segundos, 1)


def delta_descontado(inicio: Amostra, fim: Amostra, proprios: int) -> int | None:
    """Os comandos da janela, sem os nossos. `None` quando não houve medição.

    **Duas ausências diferentes, e confundi-las custa caro.** Sem `INFO` não há
    contador; e um contador que **andou para trás** é um reinício do servidor, não uma
    janela silenciosa. Se este cálculo aparasse o negativo em zero — como a primeira
    versão fazia —, um reinício do Upstash no meio da janela seria publicado como
    "zero comando por hora", que passa pelo `is not None` de quem lê e vira, no
    relatório, a melhor notícia possível sobre o pior dado possível.

    O aparo em zero fica só onde ele é honesto: `bruto` menor que os nossos comandos
    num servidor ocioso é arredondamento, não reinício.
    """
    if inicio.comandos is None or fim.comandos is None:
        return None
    bruto = fim.comandos - inicio.comandos
    if bruto < 0:
        return None
    return max(bruto - proprios, 0)


def orcamento_do_laco(instancias: int) -> float:
    """O que a ADR 0045 previu, por dia, para N workers ociosos.

    Um comando por ciclo por instância — que é a suposição que o número medido existe
    para conferir, e por isso ela mora aqui explícita em vez de num literal.
    """
    return round(86400 / POLLING_INTERVAL_SEGUNDOS * instancias, 0)


def montar_notas(
    inicio: Amostra,
    fim: Amostra,
    *,
    duracao: float,
    proprios: int,
    instancias: int,
    por_hora: float | None,
    is_upstash: bool,
    contador_reiniciou: bool = False,
) -> list[str]:
    """Uma nota por condição que qualifica o número. Nunca uma que o esconda."""
    notas: list[str] = []

    if contador_reiniciou:
        notas.append(
            "O contador do servidor **andou para trás** durante a janela: o Redis "
            "reiniciou, ou o provedor rodou a instância noutro nó. Nenhum número foi "
            "produzido, e isto não é o mesmo que uma janela silenciosa — repita a "
            "medição."
        )

    if not is_upstash:
        notas.append(
            "O alvo não é o Upstash: **isto não é a medição que a ADR 0045 pede**. "
            "Contra o Redis do compose o número descreve a máquina que rodou o "
            "docker compose, e ali um comando não custa nada — leia como ensaio do "
            "instrumento, nunca como capacidade ou custo."
        )

    if inicio.comandos is None or fim.comandos is None:
        notas.append(
            "O servidor recusou `INFO` (o Upstash expõe um subconjunto de comandos). "
            "**Nenhum número de comando/hora foi produzido**, e o que este relatório "
            "entrega são as condições: a fila, a janela e os produtores. O número sai "
            "do painel, e é a este relatório que ele deve ser colado."
        )

    if not inicio.vazia or not fim.vazia:
        notas.append(
            f"A fila **não** estava vazia nas duas pontas (início {inicio.filas}, fim "
            f"{fim.filas}): a condição que a ADR 0045 fixou não foi satisfeita. O "
            "número inclui trabalho de verdade e não descreve o laço ocioso."
        )

    if duracao < 300:
        ciclos = int(duracao / POLLING_INTERVAL_SEGUNDOS)
        notas.append(
            f"Janela de {duracao:.0f}s — curta. São ~{ciclos} ciclos de polling por "
            "instância, e um tique do beat dentro dela desloca o número em dezenas de "
            "por cento. Use 900s ou mais para citar o resultado."
        )
    elif duracao < 900:
        notas.append(
            f"Janela de {duracao:.0f}s: menor que os 900s do sync do Drive, então ela "
            "pode conter zero ou um tique daquele agendador por sorteio. Duas "
            "execuções podem discordar sem nada ter mudado."
        )

    notas.append(
        f"{proprios} comando(s) deste script foram descontados do total. O desconto é "
        "exato (uma chamada por amostra por fila, mais o `INFO`), não estimado."
    )

    notas.append(
        "Produtores que dividem este banco, e cujos comandos estão **dentro** do "
        "número: " + "; ".join(PRODUTORES) + ". A ADR 0045 orçou só o primeiro."
    )

    if not is_upstash:
        notas.append(
            "E, só no compose, mais dois que HML **não** tem: "
            + "; ".join(PRODUTORES_SO_DO_COMPOSE)
            + ". Em HML não há sonda declarada no módulo do Cloud Run, então este "
            "número não extrapola para lá nem depois de dividir — a medição de "
            "verdade é contra o Upstash."
        )

    if por_hora is not None:
        previsto_dia = orcamento_do_laco(instancias)
        medido_dia = por_hora * 24
        notas.append(
            f"Previsto pela ADR 0045 para {instancias} instância(s) ociosa(s): "
            f"~{previsto_dia:.0f} comandos/dia. Medido: ~{medido_dia:.0f}/dia — "
            f"{medido_dia / previsto_dia:.1f}× a previsão. A diferença é o que aquela "
            "conta não continha (gossip/mingle/heartbeat, result backend, beat e o "
            "scheduler do outro produto), e não um erro de nenhuma das duas."
        )

    return notas


def amostrar(cliente: redis.Redis) -> Amostra:
    """Uma amostra. `comandos` é `None` quando o servidor recusa `INFO`."""
    filas = {nome: int(cliente.llen(nome)) for nome in FILAS}
    try:
        comandos = int(cliente.info("stats")["total_commands_processed"])
    except (redis.ResponseError, KeyError, TypeError):
        # Recusa ou seção ausente. **Não** é erro do instrumento: o Upstash publica um
        # subconjunto de comandos, e um provedor que não deixa contar é um fato sobre
        # a medição, que a nota declara.
        comandos = None
    return Amostra(momento=time.monotonic(), comandos=comandos, filas=filas)


def run(args: argparse.Namespace) -> dict:
    settings = get_settings()
    url = args.redis_url or settings.redis_url
    is_upstash = "upstash.io" in url

    cliente = redis.Redis.from_url(url, socket_timeout=args.timeout, decode_responses=True)
    iniciado_em = datetime.now(timezone.utc)

    inicio = amostrar(cliente)
    time.sleep(args.duration)
    fim = amostrar(cliente)
    cliente.close()

    # Uma chamada de `LLEN` por fila e um `INFO`, duas vezes. Contado e não estimado
    # porque um desconto aproximado num número pequeno é pior que desconto nenhum.
    proprios = 2 * (len(FILAS) + 1)

    decorrido = fim.momento - inicio.momento
    delta = delta_descontado(inicio, fim, proprios)
    por_hora = comandos_por_hora(delta, decorrido) if delta is not None else None
    contador_reiniciou = (
        inicio.comandos is not None
        and fim.comandos is not None
        and fim.comandos < inicio.comandos
    )

    return {
        "target": url.split("@")[-1],  # sem credencial: o log de operação não vaza senha
        "is_upstash": is_upstash,
        "environment": settings.environment,
        "started_at": iniciado_em.isoformat(),
        "window_seconds": round(decorrido, 1),
        "polling_interval_seconds": POLLING_INTERVAL_SEGUNDOS,
        "worker_instances_declared": args.instancias,
        "queues": {
            "start": inicio.filas,
            "end": fim.filas,
            "empty_at_both_ends": inicio.vazia and fim.vazia,
        },
        "commands": {
            "info_available": inicio.comandos is not None and fim.comandos is not None,
            "counter_reset": contador_reiniciou,
            "start_total": inicio.comandos,
            "end_total": fim.comandos,
            "own_commands_discounted": proprios,
            "delta": delta,
            "per_hour": por_hora,
            "per_day": round(por_hora * 24, 0) if por_hora is not None else None,
            "adr_0045_budget_per_day": orcamento_do_laco(args.instancias),
        },
        "producers": list(PRODUTORES),
        "notes": montar_notas(
            inicio,
            fim,
            duracao=decorrido,
            proprios=proprios,
            instancias=args.instancias,
            por_hora=por_hora,
            is_upstash=is_upstash,
            contador_reiniciou=contador_reiniciou,
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_RATE_URL"),
        help="padrão: a REDIS_URL das settings",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=900.0,
        help="segundos da janela; padrão 900 (o período do sync do Drive)",
    )
    parser.add_argument(
        "--instancias",
        type=int,
        default=1,
        help="quantos workers estão de pé; entra no orçamento da ADR 0045",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--out", type=Path, help="onde gravar o relatório JSON")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    report = run(args)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(rendered + "\n")
    print(rendered)
    for note in report["notes"]:
        print(f"\n!! {note}", file=sys.stderr)


if __name__ == "__main__":
    main()
