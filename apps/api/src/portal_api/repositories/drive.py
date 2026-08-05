"""Conexão do Google Drive (project-scoped) — ADR 0016."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from portal_api.models import Document, DocumentOrigin, ProjectDriveConnection
from portal_api.repositories.base import TenantScopedRepository


class DriveConnectionRepository(TenantScopedRepository[ProjectDriveConnection]):
    model = ProjectDriveConnection

    def for_project(self) -> ProjectDriveConnection | None:
        """A conexão do projeto no contexto, se existir.

        Não recebe ``project_id``: ele já está no ``TenantContext``, e aceitar um
        segundo aqui criaria a chance de os dois discordarem.
        """
        stmt = select(ProjectDriveConnection).where(*self._tenant_filters())
        return self.session.execute(stmt).scalar_one_or_none()


class DriveDocumentRepository(TenantScopedRepository[Document]):
    """Os documentos que **vieram do Drive**, que são os únicos que o sync reconcilia.

    Existe separado do ``DocumentRepository`` porque o recorte por ``origin`` é a
    regra de negócio inteira: o sync do Drive não pode ver — e portanto não pode
    apagar — o que a administração enviou nem o que o Biahflow espelha, do mesmo
    jeito que ``sync_snapshot`` só alcança ``origin='biahflow'`` (ADR 0014 §2).
    """

    model = Document

    def by_external_id(self) -> dict[str, Document]:
        """Índice por id do Drive, que é a chave da reconciliação idempotente."""
        stmt = select(Document).where(
            Document.origin == DocumentOrigin.drive,
            Document.external_id.is_not(None),
            *self._tenant_filters(),
        )
        return {
            document.external_id: document
            for document in self.session.execute(stmt).scalars()
            if document.external_id is not None
        }

    def get_by_external_id(self, external_id: str) -> Document | None:
        stmt = select(Document).where(
            Document.origin == DocumentOrigin.drive,
            Document.external_id == external_id,
            *self._tenant_filters(),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def remove(self, document_id: uuid.UUID) -> None:
        """Apaga a linha; os trechos vão junto por CASCADE."""
        document = self.get(document_id)
        if document is not None:
            self.session.delete(document)
