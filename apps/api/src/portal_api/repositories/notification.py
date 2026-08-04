"""Notification repository (project-scoped, e por dono).

O ``user_id`` entra em todo filtro além do tenant: a linha pertence a uma pessoa,
não ao projeto. A RLS repete a mesma condição — as duas barreiras da ADR 0002 —,
mas a aplicação não delega isso à policy, pelo mesmo motivo de sempre: uma
consulta que rodasse sob o papel errado ainda ficaria correta.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import func, select, update

from portal_api.models import Notification
from portal_api.repositories.base import TenantScopedRepository


class NotificationRepository(TenantScopedRepository[Notification]):
    model = Notification

    def list_for_user(
        self, user_id: uuid.UUID, *, unread_only: bool = False, limit: int = 50
    ) -> list[Notification]:
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_id, *self._tenant_filters())
            .order_by(Notification.occurred_at.desc(), Notification.created_at.desc())
            .limit(limit)
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        return list(self.session.execute(stmt).scalars())

    def unread_count(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
            *self._tenant_filters(),
        )
        return int(self.session.execute(stmt).scalar_one())

    def mark_read(
        self, user_id: uuid.UUID, ids: Sequence[uuid.UUID] | None = None
    ) -> int:
        """Carimba ``read_at`` nas não lidas. ``ids`` vazio ou ``None`` marca todas.

        Só ``read_at``: é a única coluna que ``portal_app`` pode escrever (grant
        de coluna na migração 0009), então um UPDATE mais largo aqui falharia no
        banco em vez de passar despercebido.
        """
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
                *self._tenant_filters(),
            )
            .values(read_at=datetime.now(timezone.utc))
        )
        if ids:
            stmt = stmt.where(Notification.id.in_(ids))
        return int(self.session.execute(stmt).rowcount or 0)
