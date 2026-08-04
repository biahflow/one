"""A aritmética da apuração (Fase 3, ADR 0013).

Contra o banco, mas sem HTTP: o que está sob teste é a regra — qual premissa se
aplica a qual evento, como o investimento é rateado, e o que acontece quando
falta base. `compute_results` é módulo puro justamente para isto caber num teste
que se lê como a definição do indicador.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from portal_api.models import (
    AgentEvent,
    AgentEventOutcome,
    Organization,
    Project,
    ProjectFinancialAssumption,
)
from portal_api.repositories import TenantContext
from portal_api.results import Period, compute_results

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Tenant:
    organization_id: uuid.UUID
    project_id: uuid.UUID

    @property
    def ctx(self) -> TenantContext:
        return TenantContext(
            organization_id=self.organization_id, project_id=self.project_id
        )


@pytest.fixture
def tenant(db_session: Session) -> Tenant:
    tag = uuid.uuid4().hex[:8]
    organization = Organization(name="Results", slug=f"results-{tag}")
    db_session.add(organization)
    db_session.flush()
    project = Project(organization_id=organization.id, name="Fluxo", slug=f"fluxo-{tag}")
    db_session.add(project)
    db_session.flush()
    return Tenant(organization.id, project.id)


def _assume(
    session: Session,
    tenant: Tenant,
    *,
    effective_from: date,
    effective_to: date | None = None,
    hourly_rate_cents: int = 10_000,
    monthly_investment_cents: int = 300_000,
) -> ProjectFinancialAssumption:
    row = ProjectFinancialAssumption(
        organization_id=tenant.organization_id,
        project_id=tenant.project_id,
        effective_from=effective_from,
        effective_to=effective_to,
        hourly_rate_cents=hourly_rate_cents,
        monthly_investment_cents=monthly_investment_cents,
    )
    session.add(row)
    session.flush()
    return row


def _event(
    session: Session,
    tenant: Tenant,
    *,
    day: date,
    seconds: int = 3_600,
    avoided_cents: int = 0,
    outcome: AgentEventOutcome = AgentEventOutcome.success,
    human: bool = False,
) -> AgentEvent:
    row = AgentEvent(
        organization_id=tenant.organization_id,
        project_id=tenant.project_id,
        event_type="agent_run",
        occurred_at=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
        external_event_id=uuid.uuid4().hex,
        time_saved_seconds=seconds,
        avoided_cost_cents=avoided_cents,
        outcome=outcome,
        human_intervention=human,
    )
    session.add(row)
    session.flush()
    return row


JANUARY = Period(start=date(2026, 1, 1), end=date(2026, 1, 31))


# --- dinheiro --------------------------------------------------------------


def test_hours_become_money_at_the_rate_in_force(db_session: Session, tenant: Tenant) -> None:
    _assume(db_session, tenant, effective_from=date(2026, 1, 1), hourly_rate_cents=10_000)
    _event(db_session, tenant, day=date(2026, 1, 10), seconds=7_200)  # 2h

    summary = compute_results(db_session, tenant.ctx, JANUARY)

    assert summary.hours_saved == 2
    assert summary.labor_savings_cents == 20_000


def test_avoided_cost_is_added_as_reported(db_session: Session, tenant: Tenant) -> None:
    """Custo evitado não passa pelo valor-hora: já vem em dinheiro do produtor."""
    _assume(db_session, tenant, effective_from=date(2026, 1, 1), hourly_rate_cents=10_000)
    _event(db_session, tenant, day=date(2026, 1, 10), seconds=3_600, avoided_cents=5_000)

    summary = compute_results(db_session, tenant.ctx, JANUARY)

    assert summary.avoided_cost_cents == 5_000
    assert summary.benefit_cents == 10_000 + 5_000


def test_a_later_rate_does_not_rewrite_an_earlier_event(
    db_session: Session, tenant: Tenant
) -> None:
    """O ponto da vigência: aumentar o valor-hora hoje não reprecifica março.

    Cada evento é avaliado pela premissa que valia no dia em que ele aconteceu.
    """
    _assume(
        db_session, tenant,
        effective_from=date(2026, 1, 1), effective_to=date(2026, 1, 15),
        hourly_rate_cents=10_000,
    )
    _assume(db_session, tenant, effective_from=date(2026, 1, 15), hourly_rate_cents=20_000)
    _event(db_session, tenant, day=date(2026, 1, 10), seconds=3_600)  # premissa antiga
    _event(db_session, tenant, day=date(2026, 1, 20), seconds=3_600)  # premissa nova

    summary = compute_results(db_session, tenant.ctx, JANUARY)

    assert summary.labor_savings_cents == 10_000 + 20_000


def test_investment_is_prorated_by_day(db_session: Session, tenant: Tenant) -> None:
    """Mês comercial de 30 dias, declarado na resposta.

    Comparar benefício de um período curto com o investimento de um mês inteiro
    produziria um ROI fictício.
    """
    _assume(
        db_session, tenant, effective_from=date(2026, 1, 1), monthly_investment_cents=300_000
    )

    summary = compute_results(db_session, tenant.ctx, Period(date(2026, 1, 1), date(2026, 1, 16)))

    assert summary.period.days == 15
    assert summary.investment_cents == 150_000


def test_roi_is_benefit_minus_investment_over_investment(
    db_session: Session, tenant: Tenant
) -> None:
    _assume(
        db_session, tenant,
        effective_from=date(2026, 1, 1), effective_to=date(2026, 1, 31),
        hourly_rate_cents=10_000, monthly_investment_cents=300_000,
    )
    # 30 dias de vigência dentro do período → investimento de 300.000.
    _event(db_session, tenant, day=date(2026, 1, 10), seconds=3_600 * 60)  # 60h → 600.000

    summary = compute_results(db_session, tenant.ctx, JANUARY)

    assert summary.investment_cents == 300_000
    assert summary.benefit_cents == 600_000
    assert summary.net_cents == 300_000
    assert summary.roi_ratio == pytest.approx(1.0)


# --- lacunas ---------------------------------------------------------------


def test_without_investment_the_roi_is_a_gap_not_a_number(
    db_session: Session, tenant: Tenant
) -> None:
    """Dividir por zero para mostrar "infinito" seria inventar resultado."""
    _assume(
        db_session, tenant, effective_from=date(2026, 1, 1), monthly_investment_cents=0
    )
    _event(db_session, tenant, day=date(2026, 1, 10))

    summary = compute_results(db_session, tenant.ctx, JANUARY)

    assert summary.roi_ratio is None
    assert "no_investment" in summary.gaps


def test_without_any_assumption_money_is_zero_and_the_gap_is_declared(
    db_session: Session, tenant: Tenant
) -> None:
    _event(db_session, tenant, day=date(2026, 1, 10), seconds=3_600)

    summary = compute_results(db_session, tenant.ctx, JANUARY)

    assert summary.labor_savings_cents == 0
    assert summary.events_total == 1  # o volume continua real
    assert "no_assumption" in summary.gaps


def test_an_event_outside_every_assumption_is_counted_and_flagged(
    db_session: Session, tenant: Tenant
) -> None:
    _assume(db_session, tenant, effective_from=date(2026, 1, 15))
    _event(db_session, tenant, day=date(2026, 1, 2), seconds=3_600)  # antes da vigência

    summary = compute_results(db_session, tenant.ctx, JANUARY)

    assert summary.events_without_assumption == 1
    assert summary.labor_savings_cents == 0
    assert "events_outside_assumption" in summary.gaps


def test_no_events_is_a_gap_not_a_zero_dressed_as_a_result(
    db_session: Session, tenant: Tenant
) -> None:
    _assume(db_session, tenant, effective_from=date(2026, 1, 1))

    summary = compute_results(db_session, tenant.ctx, JANUARY)

    assert summary.events_total == 0
    assert summary.accuracy is None
    assert summary.unattended_share is None
    assert "no_events" in summary.gaps


# --- os três cards que saíram da demonstração ------------------------------


def test_accuracy_counts_a_handled_exception_as_a_success(
    db_session: Session, tenant: Tenant
) -> None:
    """Exceção tratada é o fluxo funcionando, não falhando."""
    for outcome in (
        AgentEventOutcome.success,
        AgentEventOutcome.success,
        AgentEventOutcome.exception_handled,
        AgentEventOutcome.failed,
    ):
        _event(db_session, tenant, day=date(2026, 1, 5), outcome=outcome)

    summary = compute_results(db_session, tenant.ctx, JANUARY)

    assert summary.events_total == 4
    assert summary.failed == 1
    assert summary.exceptions_handled == 1
    assert summary.accuracy == pytest.approx(0.75)


def test_unattended_share_is_over_the_exceptions_not_over_everything(
    db_session: Session, tenant: Tenant
) -> None:
    _event(db_session, tenant, day=date(2026, 1, 5))  # sucesso puro, fora da conta
    _event(
        db_session, tenant, day=date(2026, 1, 5),
        outcome=AgentEventOutcome.exception_handled, human=True,
    )
    for _ in range(3):
        _event(
            db_session, tenant, day=date(2026, 1, 5),
            outcome=AgentEventOutcome.exception_handled,
        )

    summary = compute_results(db_session, tenant.ctx, JANUARY)

    assert summary.exceptions_handled == 4
    assert summary.human_interventions == 1
    assert summary.unattended_share == pytest.approx(0.75)


# --- bordas ----------------------------------------------------------------


def test_the_period_is_half_open(db_session: Session, tenant: Tenant) -> None:
    """Dois períodos adjacentes não podem contar o mesmo evento duas vezes."""
    _event(db_session, tenant, day=date(2026, 1, 1))
    _event(db_session, tenant, day=date(2026, 1, 31))

    january = compute_results(db_session, tenant.ctx, Period(date(2026, 1, 1), date(2026, 1, 31)))
    february = compute_results(db_session, tenant.ctx, Period(date(2026, 1, 31), date(2026, 2, 28)))

    assert january.events_total == 1
    assert february.events_total == 1


def test_another_projects_events_never_enter_the_sum(
    db_session: Session, tenant: Tenant
) -> None:
    other = Organization(name="Outra", slug=f"outra-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    db_session.flush()
    other_project = Project(organization_id=other.id, name="X", slug=f"x-{uuid.uuid4().hex[:8]}")
    db_session.add(other_project)
    db_session.flush()
    _event(db_session, Tenant(other.id, other_project.id), day=date(2026, 1, 10), seconds=99_999)

    _assume(db_session, tenant, effective_from=date(2026, 1, 1))
    _event(db_session, tenant, day=date(2026, 1, 10), seconds=3_600)

    summary = compute_results(db_session, tenant.ctx, JANUARY)

    assert summary.events_total == 1
    assert summary.labor_savings_cents == 10_000


def test_overlapping_assumptions_are_impossible(db_session: Session, tenant: Tenant) -> None:
    """A garantia é do banco, não do código — `EXCLUDE USING gist` na migração.

    Sem ela, "qual era a premissa naquele dia" teria mais de uma resposta e o
    número deixaria de ser auditável.
    """
    from sqlalchemy.exc import IntegrityError

    _assume(
        db_session, tenant, effective_from=date(2026, 1, 1), effective_to=date(2026, 2, 1)
    )

    with pytest.raises(IntegrityError):
        _assume(
            db_session, tenant,
            effective_from=date(2026, 1, 15), effective_to=date(2026, 3, 1),
        )
