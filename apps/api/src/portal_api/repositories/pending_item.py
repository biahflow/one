"""Pending item repository (project-scoped)."""

from __future__ import annotations

from datetime import datetime, timezone

from portal_api.models import PendingItem, PendingState
from portal_api.repositories.base import TenantScopedRepository


class PendingItemRepository(TenantScopedRepository[PendingItem]):
    model = PendingItem

    def resolve(self, item: PendingItem) -> PendingItem:
        """Mark a pending item resolved, stamping the resolution time."""
        item.state = PendingState.resolved
        item.resolved_at = datetime.now(timezone.utc)
        self.session.flush()
        return item
