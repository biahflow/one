"""Organization — the tenant root."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from portal_api.db.base import Base, TimestampMixin


class Organization(Base, TimestampMixin):
    __tablename__ = "organization"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
