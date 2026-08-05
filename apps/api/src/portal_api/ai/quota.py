"""Quanto a IA custou a esta organização, e a partir de quanto o portal recusa.

Fase 5, ADR 0022. O único lugar onde gasto de IA é contado e cobrado, na forma de
``notifications.py``, ``conversations.py`` e ``chat_limit.py``: se "quanto este
cliente custa" estiver espalhado, a pergunta deixa de ter resposta que se leia num
arquivo.

Fecha a terceira das três coisas que o ``threat-model.md`` prometia para abuso de
chat desde a Fase 1 — "rate limit, quotas e auditoria". A ADR 0021 entregou duas e
**corrigiu o documento** para parar de prometer esta, em vez de fechar duas
promessas falsas mantendo a terceira.

## Por que não é o ``chat_limit.py`` com uma janela maior

O docstring daquele módulo responde: *"sob concorrência alta o contador subconta,
o que é aceitável para um limite de abuso e seria **inaceitável para um contador
de faturamento**"*. Este é o contador de faturamento. Um ``UPDATE ... SET total =
total + n`` é leitura-modificação-escrita, e duas perguntas simultâneas perdem uma
das duas somas. Um ``INSERT`` por chamada não disputa com nada.

Também são coisas diferentes no tempo e no eixo: a janela é de **uma pessoa** e de
um minuto, e existe porque cada lacuna grava uma pendência e enfileira uma
notificação — a ameaça é a enxurrada na caixa do time interno. A quota é de uma
**organização** e de um mês, e existe porque a conta chega. Fundi-las faria as duas
piores.

## O dinheiro nasce na leitura

``ai_usage_event`` guarda tokens. O custo é calculado pelo preço vigente **no dia
da chamada**, o que é literalmente ``results.py`` e pelo motivo dele: reajustar o
preço do modelo hoje não pode reprecificar março.

**Sem preço vigente, o turno passa** e a lacuna é declarada — a única falha aberta
de um repositório que falha fechado em quase tudo, e a razão é assimetria de
recuperação: o razão guardou o fato (os tokens), então um preço que falta pode ser
aplicado retroativamente amanhã; uma pergunta recusada hoje porque alguém trocou o
modelo sem cadastrar o preço não volta. A lacuna sai como ``ai_quota.price_missing``,
e ``alerts.md`` a lista.

## O preço declarado do controle

A checagem é sobre gasto **já gravado**, então N perguntas simultâneas no limite
passam todas. O estouro é limitado a `concorrência × custo do turno`, que para um
teto mensal é ruído. A alternativa — segurar um lock durante a chamada ao modelo —
é exatamente o que a ADR 0021 recusou ao tirar a janela de taxa da transação do
chat.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import Integer, and_, case, func, or_, select
from sqlalchemy.orm import Session

from portal_api.config import Settings
from portal_api.models import AiModelPrice, AiUsageEvent, OrganizationAiQuota
from portal_api.repositories import TenantContext

logger = logging.getLogger(__name__)

#: Tokens são publicados por milhão. Guardar centavo-por-token seria zero inteiro.
PER_MILLION = 1_000_000


class AiQuotaExhausted(HTTPException):
    """429, e **não** 403.

    Não por preferência: `test_openapi_contract.py` reprova qualquer rota que
    declare 403, porque um 403 confirmaria a existência de um recurso a quem não
    deveria saber (ADR 0020). 402 diria "pague", que é falso — quem pergunta não
    é quem contrata.

    O ``Retry-After`` aponta para a virada do mês, que é quando a afirmação volta
    a ser verdadeira. É longo de propósito, e é por ele que a tela distingue esta
    recusa da janela de um minuto sem precisar ler o texto.
    """

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Monthly AI quota exhausted for this organization",
            headers={"Retry-After": str(retry_after)},
        )


@dataclass(frozen=True)
class Spend:
    """O gasto do período, e o que impediu de sabê-lo por inteiro.

    ``gaps`` é a lista de motivos, na forma de ``results.py``: base ausente
    devolve o número que dá para calcular **mais** a razão do que falta, nunca um
    zero silencioso que se lê como "não gastou nada".
    """

    cost_cents: int
    input_tokens: int
    output_tokens: int
    calls: int
    gaps: tuple[str, ...] = ()


def period_bounds(now: datetime) -> tuple[datetime, datetime]:
    """O mês corrente em UTC, ``[início, fim)``.

    Mês-calendário e não janela deslizante de 30 dias, porque o teto é uma
    decisão comercial e a fatura de quem cobra também vira no dia 1.
    """

    start = now.astimezone(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _price_join(on_day: object) -> object:
    """A vigência que contém ``on_day``, meio aberta — a forma do ``daterange``."""

    return and_(
        AiModelPrice.model == AiUsageEvent.model,
        AiModelPrice.effective_from <= on_day,
        or_(AiModelPrice.effective_to.is_(None), AiModelPrice.effective_to > on_day),
    )


def spend(
    session: Session, organization_id: uuid.UUID, *, now: datetime | None = None
) -> Spend:
    """O gasto da organização no mês corrente, calculado agora.

    Recebe a organização e não um ``TenantContext`` porque roda sob dois papéis
    diferentes: ``portal_app`` no caminho do chat e ``portal_admin`` na tela que
    mostra a fatura. Nos dois a policy é a segunda barreira e o ``where`` é a
    primeira — o que muda é qual policy se aplica.
    """

    now = now or datetime.now(timezone.utc)
    start, end = period_bounds(now)
    day = func.date(AiUsageEvent.occurred_at)

    cost = func.sum(
        AiUsageEvent.input_tokens * AiModelPrice.input_cents_per_mtok
        + AiUsageEvent.output_tokens * AiModelPrice.output_cents_per_mtok
    )
    # Uma chamada é "sem preço" quando teve modelo e nenhuma vigência o cobria. O
    # caminho offline tem `model IS NULL` e custo zero de verdade, então não conta
    # como lacuna — declarar lacuna ali faria o alerta disparar toda vez que o
    # provedor caísse, que já tem evento próprio.
    unpriced = func.sum(
        case(
            (
                and_(
                    AiUsageEvent.model.is_not(None),
                    AiModelPrice.input_cents_per_mtok.is_(None),
                ),
                1,
            ),
            else_=0,
        )
    )

    row = session.execute(
        select(
            func.coalesce(cost, 0),
            func.coalesce(func.sum(AiUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(AiUsageEvent.output_tokens), 0),
            func.count(),
            func.coalesce(unpriced, 0).cast(Integer),
        )
        .select_from(AiUsageEvent)
        .outerjoin(AiModelPrice, _price_join(day))
        .where(
            AiUsageEvent.organization_id == organization_id,
            AiUsageEvent.occurred_at >= start,
            AiUsageEvent.occurred_at < end,
        )
    ).one()

    raw_cost, tokens_in, tokens_out, calls, unpriced_calls = row
    gaps: list[str] = []
    if unpriced_calls:
        gaps.append(
            f"{unpriced_calls} chamada(s) sem preço vigente para o modelo — "
            "o custo delas não entra na soma"
        )
        logger.warning(
            "ai_quota.price_missing",
            extra={"calls": int(unpriced_calls), "organization_id": str(organization_id)},
        )

    return Spend(
        cost_cents=round(int(raw_cost) / PER_MILLION),
        input_tokens=int(tokens_in),
        output_tokens=int(tokens_out),
        calls=int(calls),
        gaps=tuple(gaps),
    )


def limit_cents(session: Session, organization_id: uuid.UUID, settings: Settings) -> int:
    """O teto desta organização, ou o padrão.

    Coluna nula significa **"usa o padrão"**, nunca "sem teto" — a regra do
    ``organization_retention_policy`` (ADR 0017), e pela mesma razão: um contrato
    que não fala de limite não é um contrato de limite infinito. Para desligar de
    verdade existe ``AI_QUOTA_MONTHLY_CENTS=0``, que é uma decisão explícita e não
    um esquecimento.
    """

    configured = session.execute(
        select(OrganizationAiQuota.monthly_limit_cents).where(
            OrganizationAiQuota.organization_id == organization_id
        )
    ).scalar_one_or_none()
    if configured is None:
        return settings.ai_quota_monthly_cents
    return int(configured)


def check(
    session: Session,
    ctx: TenantContext,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> None:
    """Recusa a pergunta se a organização já estourou o mês.

    Chamada **depois** da resolução do projeto, ao contrário do limite de taxa:
    sem projeto não há organização a que cobrar, e recusar antes contaria a quem
    não tem vínculo que a organização existe. É a mesma preocupação que faz toda
    negação ser 404 (ADR 0010) — e a diferença de ordem com o ``chat_limit`` é
    deliberada, não um descuido.
    """

    limit = limit_cents(session, ctx.organization_id, settings)
    if limit <= 0:
        return

    now = now or datetime.now(timezone.utc)
    current = spend(session, ctx.organization_id, now=now)
    if current.cost_cents < limit:
        return

    _, end = period_bounds(now)
    retry_after = max(1, int((end - now).total_seconds()))
    logger.warning(
        "ai_quota.exhausted",
        extra={
            "organization_id": str(ctx.organization_id),
            "spent_cents": current.cost_cents,
            "limit_cents": limit,
        },
    )
    raise AiQuotaExhausted(retry_after)


def record(
    session: Session,
    ctx: TenantContext,
    *,
    responder: str,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    now: datetime | None = None,
) -> None:
    """Grava o que a chamada consumiu, na transação do turno.

    Na **mesma** transação, e não numa anterior como a janela de taxa: um turno
    revertido não deve cobrar. O preço disso está declarado na ADR 0022 — se a
    transação reverter depois de o provedor responder, o dinheiro saiu e a linha
    não existe. É subcontagem, e é por isso que o mesmo número vai no evento
    ``chat.answered``, que o log guarda fora da transação: o razão responde
    "quanto neste mês", o log responde "quanto de fato saiu", e os dois se
    reconciliam.
    """

    session.add(
        AiUsageEvent(
            organization_id=ctx.organization_id,
            project_id=ctx.project_id,
            occurred_at=now or datetime.now(timezone.utc),
            model=model,
            responder=responder,
            input_tokens=max(0, int(input_tokens)),
            output_tokens=max(0, int(output_tokens)),
        )
    )


def open_price(session: Session, model: str, on_day: date) -> AiModelPrice | None:
    """O preço vigente de um modelo num dia. Usado pelo harness de carga."""

    return session.execute(
        select(AiModelPrice).where(
            AiModelPrice.model == model,
            AiModelPrice.effective_from <= on_day,
            or_(AiModelPrice.effective_to.is_(None), AiModelPrice.effective_to > on_day),
        )
    ).scalar_one_or_none()
