"""SQLAlchemy declarative base and shared column mixins.

Every table lives in the ``portal`` schema. Rather than qualifying the metadata
with that schema (which makes Alembic autogenerate perpetually diff qualified
metadata against unqualified reflection), the connection ``search_path`` is
pinned to ``portal`` in :mod:`portal_api.db.session`, so both DDL and reflection
stay unqualified and compare cleanly. Deterministic constraint/index names keep
migrations stable across autogenerate runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "portal"

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantMixin:
    """Adds the mandatory ``organization_id`` tenant key.

    Project-scoped tables additionally declare a ``project_id`` column; see
    ADR 0002 — every record carries its organization, and project when
    applicable. The column is denormalized onto child tables on purpose so the
    upcoming Row-Level Security policies and tenant filters stay simple.
    """

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        # Unqualified: resolves within the MetaData default schema (portal) and
        # matches reflection, avoiding false autogenerate drift.
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
