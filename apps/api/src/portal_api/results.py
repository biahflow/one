"""Apuração dos resultados a partir dos eventos dos agentes (ADR 0013).

Módulo puro — recebe sessão e contexto, devolve números — para que o teste da
aritmética não precise de HTTP, no mesmo espírito de ``notifications.py`` e
``health.py``.

O princípio que organiza tudo aqui: **nada é derivado no momento da escrita**.
O evento guarda o que o agente reportou, em inteiros; o valor em dinheiro nasce
na leitura, aplicando a premissa que vigia *no dia do evento*. É isso que
impede um aumento de valor-hora hoje de reescrever o resultado de março, e é o
que faz cada número ser explicável meses depois.

Onde falta base para um número, ele vem ``None`` **acompanhado da razão** em
``gaps`` — a mesma disciplina da regra 3 do AGENTS.md: declarar a lacuna, nunca
preencher com um palpite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from portal_api.models import AgentEventOutcome, ProjectFinancialAssumption
from portal_api.repositories import (
    AgentEventRepository,
    FinancialAssumptionRepository,
    TenantContext,
)

SECONDS_PER_HOUR = Decimal(3600)
#: Mês comercial de 30 dias. É a premissa de rateio do investimento, e está
#: declarada aqui e na resposta porque um número que o cliente não consegue
#: refazer na mão não é auditável.
DAYS_PER_MONTH = Decimal(30)
DEFAULT_PERIOD_DAYS = 30


@dataclass(frozen=True)
class Period:
    """Intervalo ``[start, end)`` em dias. Meio aberto para que dois períodos
    adjacentes nunca contem o mesmo evento duas vezes."""

    start: date
    end: date

    @classmethod
    def last_days(cls, days: int = DEFAULT_PERIOD_DAYS, *, today: date | None = None) -> "Period":
        today = today or datetime.now(timezone.utc).date()
        return cls(start=today - timedelta(days=days), end=today + timedelta(days=1))

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def bounds(self) -> tuple[datetime, datetime]:
        """Os limites em UTC, para comparar com ``occurred_at``."""
        return (
            datetime.combine(self.start, time.min, tzinfo=timezone.utc),
            datetime.combine(self.end, time.min, tzinfo=timezone.utc),
        )


@dataclass(frozen=True)
class AssumptionView:
    """Uma premissa como o cliente a vê, ao lado do indicador que ela produziu."""

    effective_from: date
    effective_to: date | None
    hourly_rate_cents: int
    monthly_investment_cents: int
    currency: str
    note: str | None
    #: Dias desta vigência que caem dentro do período pedido.
    days_in_period: int


@dataclass
class ResultsSummary:
    period: Period
    events_total: int = 0
    #: Eventos que caíram fora de qualquer vigência — contam para volume e
    #: precisão, mas não para dinheiro, e o cliente é avisado disso.
    events_without_assumption: int = 0
    time_saved_seconds: int = 0
    labor_savings_cents: int = 0
    avoided_cost_cents: int = 0
    investment_cents: int = 0
    exceptions_handled: int = 0
    failed: int = 0
    human_interventions: int = 0
    assumptions: list[AssumptionView] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def hours_saved(self) -> Decimal:
        return (Decimal(self.time_saved_seconds) / SECONDS_PER_HOUR).quantize(Decimal("0.1"))

    @property
    def benefit_cents(self) -> int:
        return self.labor_savings_cents + self.avoided_cost_cents

    @property
    def net_cents(self) -> int:
        return self.benefit_cents - self.investment_cents

    @property
    def roi_ratio(self) -> float | None:
        """``(benefício − investimento) / investimento``.

        ``None`` com investimento zero: dividir por zero para exibir "infinito"
        seria inventar um resultado onde não há premissa. A lacuna vai em
        ``gaps`` e a tela mostra "—".
        """
        if self.investment_cents <= 0:
            return None
        return self.net_cents / self.investment_cents

    @property
    def accuracy(self) -> float | None:
        """Execuções que chegaram ao fim, com ou sem exceção tratada.

        Exceção tratada conta como acerto: o fluxo encontrou algo para o qual
        não foi desenhado e resolveu. Contá-la como falha subestimaria a
        precisão; contá-la como sucesso puro esconderia o que o cliente quer ver.
        """
        if self.events_total == 0:
            return None
        return (self.events_total - self.failed) / self.events_total

    @property
    def unattended_share(self) -> float | None:
        """Fatia das exceções resolvidas sem humano no meio."""
        if self.exceptions_handled == 0:
            return None
        return (self.exceptions_handled - self.human_interventions) / self.exceptions_handled


def _overlap_days(period: Period, assumption: ProjectFinancialAssumption) -> int:
    start = max(period.start, assumption.effective_from)
    end = min(period.end, assumption.effective_to or period.end)
    return max(0, (end - start).days)


def _assumption_for(
    assumptions: list[ProjectFinancialAssumption], day: date
) -> ProjectFinancialAssumption | None:
    for assumption in assumptions:
        if assumption.effective_from <= day and (
            assumption.effective_to is None or assumption.effective_to > day
        ):
            return assumption
    return None


def compute_results(
    session: Session, ctx: TenantContext, period: Period | None = None
) -> ResultsSummary:
    """Apura o período a partir dos eventos e das premissas vigentes."""
    period = period or Period.last_days()
    summary = ResultsSummary(period=period)

    assumptions = FinancialAssumptionRepository(session, ctx).covering(
        period.start, period.end
    )
    start, end = period.bounds()
    events = AgentEventRepository(session, ctx).in_period(start, end)

    summary.events_total = len(events)
    for event in events:
        if event.outcome is AgentEventOutcome.failed:
            summary.failed += 1
        elif event.outcome is AgentEventOutcome.exception_handled:
            summary.exceptions_handled += 1
            if event.human_intervention:
                summary.human_interventions += 1

        summary.time_saved_seconds += event.time_saved_seconds or 0
        summary.avoided_cost_cents += event.avoided_cost_cents or 0

        assumption = _assumption_for(assumptions, event.occurred_at.date())
        if assumption is None:
            summary.events_without_assumption += 1
            continue
        seconds = Decimal(event.time_saved_seconds or 0)
        summary.labor_savings_cents += int(
            (seconds / SECONDS_PER_HOUR * assumption.hourly_rate_cents).to_integral_value()
        )

    for assumption in assumptions:
        days = _overlap_days(period, assumption)
        summary.assumptions.append(
            AssumptionView(
                effective_from=assumption.effective_from,
                effective_to=assumption.effective_to,
                hourly_rate_cents=assumption.hourly_rate_cents,
                monthly_investment_cents=assumption.monthly_investment_cents,
                currency=assumption.currency,
                note=assumption.note,
                days_in_period=days,
            )
        )
        # Rateio por dia: comparar benefício de 30 dias com investimento de
        # projeto inteiro produziria um ROI fictício.
        summary.investment_cents += int(
            (
                Decimal(assumption.monthly_investment_cents) / DAYS_PER_MONTH * days
            ).to_integral_value()
        )

    if not assumptions:
        summary.gaps.append("no_assumption")
    elif summary.events_without_assumption:
        summary.gaps.append("events_outside_assumption")
    if summary.investment_cents <= 0:
        summary.gaps.append("no_investment")
    if not events:
        summary.gaps.append("no_events")

    return summary


def to_payload(summary: ResultsSummary) -> dict:
    """Serializa a apuração com a premissa ao lado do número.

    A premissa e as lacunas viajam junto de propósito: o aceite da fase é o
    cliente ver a origem de todo indicador, e uma resposta que mandasse só os
    valores obrigaria a tela a inventar a explicação.
    """
    return {
        "period": {
            "from": summary.period.start.isoformat(),
            "to": summary.period.end.isoformat(),
            "days": summary.period.days,
        },
        "events_total": summary.events_total,
        "hours_saved": float(summary.hours_saved),
        "labor_savings_cents": summary.labor_savings_cents,
        "avoided_cost_cents": summary.avoided_cost_cents,
        "benefit_cents": summary.benefit_cents,
        "investment_cents": summary.investment_cents,
        "net_cents": summary.net_cents,
        "roi_ratio": summary.roi_ratio,
        "accuracy": summary.accuracy,
        "exceptions_handled": summary.exceptions_handled,
        "unattended_share": summary.unattended_share,
        "failed": summary.failed,
        "events_without_assumption": summary.events_without_assumption,
        "assumptions": [
            {
                "effective_from": item.effective_from.isoformat(),
                "effective_to": item.effective_to.isoformat() if item.effective_to else None,
                "hourly_rate_cents": item.hourly_rate_cents,
                "monthly_investment_cents": item.monthly_investment_cents,
                "currency": item.currency,
                "note": item.note,
                "days_in_period": item.days_in_period,
            }
            for item in summary.assumptions
        ],
        "assumption_basis": {
            "days_per_month": int(DAYS_PER_MONTH),
            "formula": "(beneficio - investimento) / investimento",
        },
        "gaps": summary.gaps,
    }
