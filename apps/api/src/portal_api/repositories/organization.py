"""Organization and user repositories (tenant roots, not scoped)."""

from __future__ import annotations

from sqlalchemy import select

from portal_api.models import Organization, User
from portal_api.repositories.base import Repository


class OrganizationRepository(Repository[Organization]):
    model = Organization

    def get_by_slug(self, slug: str) -> Organization | None:
        stmt = select(Organization).where(Organization.slug == slug)
        return self.session.execute(stmt).scalar_one_or_none()


class UserRepository(Repository[User]):
    model = User

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        return self.session.execute(stmt).scalar_one_or_none()
