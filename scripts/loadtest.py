#!/usr/bin/env python
"""Carga do chat contextual, com orçamento declarado (Fase 5, ADR 0022).

Mora em ``scripts/`` pela razão do ``backup.sh``: é **operação**, não aplicação.
Não sobe rota, não é importado por nada e roda quando alguém decide rodar.

    PYTHONPATH=apps/api/src python scripts/loadtest.py --duration 60 --out /tmp/carga.json

## O que ele mede, e o que ele não mede

Bate no ``POST /api/v1/chat`` da **API**, não no BFF. É onde estão as duas coisas
caras — a busca vetorial no pgvector e a chamada ao modelo — e onde o custo
acontece; incluir o salto do Next.js misturaria a renderização à medição. O preço
é que o número não descreve o que o navegador sente, e o relatório diz isso.

## As três decisões

**1. O orçamento é fail-closed.** Com ``ANTHROPIC_API_KEY`` configurada, cada
pergunta custa dinheiro de verdade, e o harness **recusa rodar** sem
``--budget-usd`` — a forma do ``BACKUP_AGE_RECIPIENT`` do ``backup.sh``, que
prefere não fazer backup a fazer um em texto claro. Era esta a exigência que o
`ROADMAP.md` fazia ao adiar a carga: *"sem orçamento declarado, um número de
carga contra o `docker compose` mede o laptop de quem roda"*.

**2. O custo vem do razão, não de uma estimativa.** O harness lê
``ai/quota.py`` — o mesmo código que a quota usa para cobrar — e para quando o
gasto do período passa do orçamento. Uma tabela de preços própria aqui poderia
discordar da que recusa perguntas em produção, e as duas estariam erradas em
silêncio.

**3. O relatório declara o que mediu.** Contra a pilha local ele escreve, no
próprio artefato, que aquilo **não é homologação**; se o respondedor caiu para
``offline_fallback``, ele escreve que os percentis não medem o que dizem medir. É
a regra do ``testing-strategy.md`` — *um pulo não é um teste que passou* —
aplicada a uma medição: um número sem a condição em que foi obtido é pior que
nenhum, porque alguém o cita depois.

## O teto que não dá para ignorar

``CHAT_RATE_LIMIT`` são 20 perguntas por minuto **por pessoa**. Um harness com um
usuário mede o limitador, não o sistema: ele daria 20 e depois 429 para sempre.
Por isso a carga é distribuída entre N contas, e a vazão máxima honesta é
``N × CHAT_RATE_LIMIT``. Acima disso o relatório contabiliza os 429 e avisa —
levantar a vazão é acrescentar contas ou subir a variável para a execução, o que
só é possível desde a ADR 0022, quando ela passou a chegar ao contêiner.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from portal_api.ai import quota  # noqa: E402
from portal_api.config import get_settings  # noqa: E402
# A fábrica de sessão do próprio projeto, e não um `create_engine` cru: é ela que
# fixa o `search_path` em `portal,public` (ADR 0010). Um engine construído à mão
# aqui não enxerga tabela nenhuma.
from portal_api.db.session import DbRole, get_session  # noqa: E402
from portal_api.models import AiUsageEvent, Membership, User  # noqa: E402

#: Perguntas de carga. Deliberadamente variadas entre "tem evidência" e "não tem":
#: a lacuna é o caminho **mais caro** do portal — grava pendência, linha de
#: auditoria e enfileira notificação —, e uma carga só de perguntas respondíveis
#: mediria o caminho barato e chamaria isso de carga.
QUESTIONS = (
    "Qual é o status do projeto?",
    "Quais pendências estão abertas?",
    "Quando é a próxima reunião?",
    "Qual é o ROI apurado até agora?",
    "O que diz o contrato sobre suporte?",
    "Quais entregáveis já foram desbloqueados?",
    "Qual foi a última decisão registrada?",
    "Quanto custa um trator em Marte?",
)

DEFAULT_USERS = ("marina.farias", "helena.dias", "rafael.costa")
DEFAULT_PASSWORD = "portal_local_only"


@dataclass
class Tally:
    latencies_ms: list[float] = field(default_factory=list)
    ok: int = 0
    rate_limited: int = 0
    quota_exhausted: int = 0
    errors: int = 0
    status_counts: dict[int, int] = field(default_factory=dict)

    def record(self, status: int, elapsed_ms: float, retry_after: str | None) -> None:
        self.status_counts[status] = self.status_counts.get(status, 0) + 1
        if status == 200:
            self.ok += 1
            self.latencies_ms.append(elapsed_ms)
        elif status == 429:
            # O mesmo código para duas recusas diferentes, separadas pela ordem de
            # grandeza do `Retry-After` — exatamente como a tela faz (ADR 0022).
            seconds = int(retry_after or 0)
            if seconds > 3600:
                self.quota_exhausted += 1
            else:
                self.rate_limited += 1
        else:
            self.errors += 1


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((p / 100) * (len(ordered) - 1))))
    return round(ordered[index], 1)


async def obtain_token(client: httpx.AsyncClient, issuer: str, username: str, password: str,
                       client_id: str, client_secret: str) -> str:
    response = await client.post(
        f"{issuer}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "password": password,
        },
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


async def worker(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    tally: Tally,
    stop: asyncio.Event,
    seed: int,
    interval: float,
) -> None:
    """Um laço com passo, e o passo é a parte que importa.

    Sem ele o harness gira o mais rápido que consegue e vira uma tempestade de
    429: a primeira execução deste script devolveu 12.839 recusas para 62
    respostas — mediu o limitador de taxa com muita precisão e o sistema com
    nenhuma, porque os percentis saíram de 62 amostras. Um gerador de carga que
    ignora o controle de admissão do alvo não está medindo o alvo.
    """

    turn = seed
    while not stop.is_set():
        cycle_started = time.perf_counter()
        question = QUESTIONS[turn % len(QUESTIONS)]
        turn += 1
        try:
            response = await client.post(
                f"{base_url}/api/v1/chat",
                json={"question": question},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError:
            tally.errors += 1
        else:
            elapsed_ms = (time.perf_counter() - cycle_started) * 1000
            tally.record(response.status_code, elapsed_ms, response.headers.get("Retry-After"))

        # Descontando o que a requisição já levou: o passo é do ciclo, não do
        # descanso, senão a vazão real cairia junto com a latência do alvo — e a
        # medição ficaria mais fraca justamente quando o sistema fica mais lento.
        remaining = interval - (time.perf_counter() - cycle_started)
        if remaining > 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                pass


def organization_of(subjects: list[str]) -> uuid.UUID | None:
    """A organização que a carga vai gastar, descoberta pelo vínculo das contas.

    Pelo vínculo e não pelo razão: a tabela de consumo tem linhas de todo tenant,
    e pegar "a primeira" mediria o gasto de outra organização — o relatório sairia
    plausível e errado, que é a pior combinação.
    """

    with get_session(role=DbRole.system) as session:
        user = (
            session.execute(select(User).where(User.external_subject.in_(subjects)))
            .scalars()
            .first()
        )
        if user is None:
            return None
        return session.execute(
            select(Membership.organization_id).where(Membership.user_id == user.id).limit(1)
        ).scalar_one_or_none()


def responder_mix(organization_id: uuid.UUID, since: datetime) -> dict[str, int]:
    """De onde saíram as respostas desta execução.

    É a asserção que dá sentido a todo o resto do relatório: se
    ``offline_fallback`` aparece, o provedor degradou no meio da medição e os
    percentis descrevem o casador determinístico, não o modelo.
    """

    with get_session(role=DbRole.system) as session:
        rows = session.execute(
            select(AiUsageEvent.responder, func.count())
            .where(
                AiUsageEvent.organization_id == organization_id,
                AiUsageEvent.occurred_at >= since,
            )
            .group_by(AiUsageEvent.responder)
        ).all()
    return {name: int(count) for name, count in rows}


async def run(args: argparse.Namespace) -> dict:
    settings = get_settings()
    issuer = args.issuer or settings.oidc_issuer
    mode = "provider" if settings.anthropic_api_key else "offline"

    if mode == "provider" and args.budget_usd is None:
        raise SystemExit(
            "ANTHROPIC_API_KEY está configurada: cada pergunta custa dinheiro de verdade.\n"
            "Declare o orçamento com --budget-usd. Recusar é o comportamento certo aqui — "
            "é a mesma regra do BACKUP_AGE_RECIPIENT em scripts/backup.sh."
        )

    usernames = args.users or list(DEFAULT_USERS)
    if args.concurrency is None:
        args.concurrency = len(usernames)

    async with httpx.AsyncClient(timeout=args.timeout) as auth_client:
        tokens = [
            await obtain_token(
                auth_client, issuer, name, args.password, args.client_id, args.client_secret
            )
            for name in usernames
        ]

    subjects = []
    for token in tokens:
        import base64

        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        subjects.append(json.loads(base64.urlsafe_b64decode(payload))["sub"])

    organization_id = organization_of(subjects)
    if organization_id is None:
        raise SystemExit("nenhuma das contas informadas tem vínculo; nada a medir")

    with get_session(role=DbRole.system) as session:
        baseline = quota.spend(session, organization_id)

    # A vazão honesta é `contas × CHAT_RATE_LIMIT`, e o padrão fica 10% abaixo
    # dela: pedir exatamente o teto faria a janela recusar por arredondamento, e
    # o relatório sairia cheio de 429 que não dizem nada sobre o sistema.
    ceiling_per_second = len(usernames) * settings.chat_rate_limit / 60
    rate = args.rate if args.rate is not None else ceiling_per_second * 0.9

    # O passo é calculado **por conta**, não pela vazão total, porque o limite é
    # por pessoa. Com 4 workers sobre 3 contas, uma delas recebe o dobro das
    # outras e estoura sozinha enquanto a vazão agregada ainda está abaixo do
    # teto — foi o que aconteceu na segunda execução deste script, com 4 recusas
    # em 20 requisições a 90% do teto agregado.
    workers_per_account = [0] * len(usernames)
    for index in range(args.concurrency):
        workers_per_account[index % len(usernames)] += 1
    per_account_rate = rate / len(usernames)
    intervals = [
        (share / per_account_rate if per_account_rate > 0 else 0.0)
        for share in workers_per_account
    ]

    started_at = datetime.now(timezone.utc)
    tally = Tally()
    stop = asyncio.Event()
    stopped_by_budget = False

    async def budget_guard() -> None:
        nonlocal stopped_by_budget
        if args.budget_usd is None:
            return
        ceiling_cents = args.budget_usd * 100
        while not stop.is_set():
            await asyncio.sleep(args.poll_seconds)
            with get_session(role=DbRole.system) as session:
                current = quota.spend(session, organization_id)
            if current.cost_cents - baseline.cost_cents >= ceiling_cents:
                stopped_by_budget = True
                stop.set()
                return

    async def clock() -> None:
        await asyncio.sleep(args.duration)
        stop.set()

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        workers = [
            asyncio.create_task(
                worker(
                    client,
                    args.base_url,
                    tokens[i % len(tokens)],
                    tally,
                    stop,
                    i,
                    intervals[i % len(usernames)],
                )
            )
            for i in range(args.concurrency)
        ]
        await asyncio.gather(clock(), budget_guard(), *workers)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    with get_session(role=DbRole.system) as session:
        final = quota.spend(session, organization_id)
    mix = responder_mix(organization_id, started_at)

    total = tally.ok + tally.rate_limited + tally.quota_exhausted + tally.errors
    cost_delta = final.cost_cents - baseline.cost_cents

    notes: list[str] = []
    if settings.environment.strip().lower() == "local":
        notes.append(
            "ENVIRONMENT=local: **isto não é homologação**. Os números descrevem a "
            "máquina que rodou o compose, não o ambiente — leia-os como regressão "
            "relativa, nunca como capacidade."
        )
    if mode == "offline":
        notes.append(
            "Sem ANTHROPIC_API_KEY: o respondedor foi o casador offline determinístico. "
            "Isto mede pgvector, RLS, transações e o limite de taxa — **não** mede "
            "latência nem custo de modelo."
        )
    if mix.get("offline_fallback"):
        notes.append(
            f"{mix['offline_fallback']} turno(s) caíram para offline_fallback: o provedor "
            "degradou durante a medição e os percentis não descrevem o modelo. Ver "
            "chat.provider_unavailable no log e docs/runbooks/ai-provider-failure.md."
        )
    if tally.rate_limited:
        notes.append(
            f"{tally.rate_limited} requisição(ões) recusadas pela janela de taxa. A vazão "
            f"honesta com {len(usernames)} conta(s) é "
            f"{len(usernames) * settings.chat_rate_limit}/min "
            f"({ceiling_per_second:.1f}/s), e esta execução pediu {rate:.1f}/s. Para subir, "
            "acrescente contas ou levante CHAT_RATE_LIMIT **para a execução** — o que só é "
            "possível desde a ADR 0022, quando a variável passou a chegar ao contêiner."
        )
    if tally.quota_exhausted:
        notes.append(
            f"{tally.quota_exhausted} requisição(ões) recusadas pelo teto mensal da "
            "organização — o controle da ADR 0022 funcionando."
        )
    if stopped_by_budget:
        notes.append(
            f"Interrompido pelo orçamento de US$ {args.budget_usd:.2f} antes de "
            f"{args.duration}s."
        )
    notes.extend(final.gaps)

    return {
        "target": args.base_url,
        "environment": settings.environment,
        "is_homologation": settings.environment.strip().lower() != "local",
        "mode": mode,
        "model": settings.anthropic_model if mode == "provider" else None,
        "started_at": started_at.isoformat(),
        "duration_seconds": round(elapsed, 1),
        "concurrency": args.concurrency,
        "accounts": len(usernames),
        "requested_rate_per_second": round(rate, 2),
        "rate_ceiling_per_second": round(ceiling_per_second, 2),
        "requests": {
            "total": total,
            "ok": tally.ok,
            "rate_limited": tally.rate_limited,
            "quota_exhausted": tally.quota_exhausted,
            "errors": tally.errors,
            "by_status": tally.status_counts,
            "throughput_per_second": round(total / elapsed, 2) if elapsed else 0,
        },
        "latency_ms": {
            "p50": percentile(tally.latencies_ms, 50),
            "p95": percentile(tally.latencies_ms, 95),
            "p99": percentile(tally.latencies_ms, 99),
            "mean": round(statistics.fmean(tally.latencies_ms), 1) if tally.latencies_ms else None,
        },
        "responder_mix": mix,
        "cost": {
            "budget_usd": args.budget_usd,
            "spent_cents": cost_delta,
            "spent_usd": round(cost_delta / 100, 4),
            "input_tokens": final.input_tokens - baseline.input_tokens,
            "output_tokens": final.output_tokens - baseline.output_tokens,
            "cents_per_answer": round(cost_delta / tally.ok, 3) if tally.ok else None,
            "stopped_by_budget": stopped_by_budget,
        },
        "notes": notes,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("LOAD_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--issuer", default=os.environ.get("LOAD_ISSUER"))
    parser.add_argument("--duration", type=int, default=30, help="segundos")
    parser.add_argument(
        "--concurrency",
        type=int,
        help="padrão: uma conexão por conta, que é o que distribui o limite por igual",
    )
    parser.add_argument("--users", nargs="*", help=f"padrão: {' '.join(DEFAULT_USERS)}")
    parser.add_argument("--password", default=os.environ.get("LOAD_PASSWORD", DEFAULT_PASSWORD))
    parser.add_argument("--client-id", default=os.environ.get("AUTH_KEYCLOAK_ID", "portal-web"))
    parser.add_argument(
        "--client-secret",
        default=os.environ.get("AUTH_KEYCLOAK_SECRET", "portal-web-local-only"),
    )
    parser.add_argument(
        "--budget-usd",
        type=float,
        default=float(os.environ["LOAD_BUDGET_USD"]) if os.environ.get("LOAD_BUDGET_USD") else None,
        help="obrigatório quando ANTHROPIC_API_KEY está configurada",
    )
    parser.add_argument(
        "--rate",
        type=float,
        help="requisições por segundo; o padrão é 90%% de contas × CHAT_RATE_LIMIT",
    )
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--out", type=Path, help="onde gravar o relatório JSON")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    report = asyncio.run(run(args))
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(rendered + "\n")
    print(rendered)
    for note in report["notes"]:
        print(f"\n!! {note}", file=sys.stderr)


if __name__ == "__main__":
    main()
