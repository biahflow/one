"""Repository base classes.

``Repository`` is the plain base for tenant-root entities (organization, user).
``TenantScopedRepository`` enforces organization/project isolation on every read
and write, materializing the ADR 0002 barrier at the application layer.
"""

from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from portal_api.db.base import Base
from portal_api.repositories.context import TenantContext

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        self.session.flush()
        return instance

    def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return self.session.get(self.model, entity_id)


class TenantScopedRepository(Repository[ModelT]):
    """Repository bound to a :class:`TenantContext`.

    Every query is filtered by ``organization_id`` (and ``project_id`` when the
    model has that column and the context supplies one). Writes are stamped from
    the context, so a mismatched or missing tenant key can never be persisted.
    """

    def __init__(self, session: Session, ctx: TenantContext) -> None:
        super().__init__(session)
        self.ctx = ctx

    @property
    def _has_project_column(self) -> bool:
        return hasattr(self.model, "project_id")

    def _tenant_filters(self) -> list:
        filters = [self.model.organization_id == self.ctx.organization_id]
        if self._has_project_column and self.ctx.project_id is not None:
            filters.append(self.model.project_id == self.ctx.project_id)
        return filters

    def add(self, instance: ModelT) -> ModelT:
        # Stamp tenant keys from the context so callers cannot write cross-tenant.
        instance.organization_id = self.ctx.organization_id
        if self._has_project_column and self.ctx.project_id is not None:
            instance.project_id = self.ctx.project_id
        return super().add(instance)

    def get(self, entity_id: uuid.UUID) -> ModelT | None:
        stmt = select(self.model).where(
            self.model.id == entity_id, *self._tenant_filters()
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list(self) -> list[ModelT]:
        stmt = select(self.model).where(*self._tenant_filters())
        return list(self.session.execute(stmt).scalars())
