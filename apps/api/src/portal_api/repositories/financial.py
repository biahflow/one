"""Premissas financeiras do projeto, por vigência (ADR 0013)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from portal_api.models import ProjectFinancialAssumption
from portal_api.repositories.base import TenantScopedRepository


class FinancialAssumptionRepository(TenantScopedRepository[ProjectFinancialAssumption]):
    model = ProjectFinancialAssumption

    def history(self) -> list[ProjectFinancialAssumption]:
        """Todas as vigências, da mais recente para a mais antiga."""
        stmt = (
            select(self.model)
            .where(*self._tenant_filters())
            .order_by(self.model.effective_from.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def covering(self, start: date, end: date) -> list[ProjectFinancialAssumption]:
        """As vigências que tocam o intervalo ``[start, end)``.

        É o conjunto mínimo capaz de explicar todo indicador do período — e é
        exatamente o que a resposta devolve ao cliente junto do número.
        """
        stmt = (
            select(self.model)
            .where(
                self.model.effective_from < end,
                (self.model.effective_to.is_(None)) | (self.model.effective_to > start),
                *self._tenant_filters(),
            )
            .order_by(self.model.effective_from)
        )
        return list(self.session.execute(stmt).scalars())

    def in_force_on(self, day: date) -> ProjectFinancialAssumption | None:
        """A premissa vigente num dia. Sem sobreposição possível — o
        ``EXCLUDE USING gist`` da migração garante que a resposta é uma só."""
        stmt = select(self.model).where(
            self.model.effective_from <= day,
            (self.model.effective_to.is_(None)) | (self.model.effective_to > day),
            *self._tenant_filters(),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def current_open(self) -> ProjectFinancialAssumption | None:
        """A vigência ainda aberta, que uma premissa nova precisa fechar."""
        stmt = select(self.model).where(
            self.model.effective_to.is_(None), *self._tenant_filters()
        )
        return self.session.execute(stmt).scalar_one_or_none()
