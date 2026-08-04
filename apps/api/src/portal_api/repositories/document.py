"""Document repository (project-scoped)."""

from __future__ import annotations

from portal_api.models import Document
from portal_api.repositories.base import TenantScopedRepository


class DocumentRepository(TenantScopedRepository[Document]):
    model = Document
