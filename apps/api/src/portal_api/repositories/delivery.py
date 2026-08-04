"""Delivery repository (project-scoped)."""

from __future__ import annotations

from portal_api.models import Delivery
from portal_api.repositories.base import TenantScopedRepository


class DeliveryRepository(TenantScopedRepository[Delivery]):
    model = Delivery
