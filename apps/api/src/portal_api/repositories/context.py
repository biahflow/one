"""Tenant context carried into every scoped repository."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    """The organization (and optional project) a request is authorized for.

    Repositories use it to filter every read and stamp every write, so a caller
    can never reach another organization's or project's rows (ADR 0002). This is
    the application-layer barrier that precedes PostgreSQL Row-Level Security.
    """

    organization_id: uuid.UUID
    project_id: uuid.UUID | None = None
