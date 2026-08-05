"""O único lugar onde o índice é reconciliado com o Drive (ADR 0016).

Em módulo próprio pela mesma razão que ``notifications.py`` e ``conversations.py``
são: se "o que o sync do Drive pode apagar" ficar espalhado entre o worker e o
adapter, a pergunta deixa de ter resposta que caiba em um arquivo. O adapter fala
HTTP e não conhece banco; aqui está a regra.

Três invariantes, e cada um existe porque o contrário já é um incidente conhecido:

1. **Só remove sobre listagem completa.** O runbook manda "preservar último índice
   válido". Uma enumeração que falhou no meio, ou que estourou o teto de arquivos,
   descreve um Drive menor do que o real — tratá-la como verdade apagaria o índice
   do cliente por causa de uma indisponibilidade do Google.

2. **Só alcança o que veio do Drive.** O recorte por ``origin='drive'`` é o mesmo
   desenho do ``DELETE ... WHERE origin='biahflow'`` do ``sync_snapshot``
   (ADR 0014 §2): o que a administração enviou não é do sync, e o sync não mexe
   no que não é dele.

3. **Dois portões antes de gastar.** O barato é o ``modifiedTime``, que evita o
   download; o exato é o SHA-256 dos bytes, que evita o ``put_object`` e os
   embeddings. Um sync horário de uma pasta parada custa uma listagem e nada mais.

O portão barato é ``modifiedTime`` e não ``md5Checksum`` porque arquivo nativo do
Google **não tem md5** — usar o md5 faria todo Google Doc parecer alterado a cada
sync, e o portal recobraria embeddings para sempre sem nada ter mudado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from portal_api import storage
from portal_api.config import Settings
from portal_api.integrations import google_drive as drive
from portal_api.models import (
    Document,
    DocumentIngestState,
    DocumentOrigin,
    DocumentSource,
    ProjectDriveConnection,
)
from portal_api.repositories import DriveDocumentRepository, TenantContext

logger = logging.getLogger(__name__)


@dataclass
class SyncOutcome:
    """O que o sync fez. Vira ``last_sync_stats`` e a linha da tela."""

    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0
    unsupported: int = 0
    rejected: int = 0
    truncated: bool = False
    #: Ids dos documentos a enfileirar para indexação — **depois** do commit. Se
    #: a task fosse enfileirada aqui dentro, um worker rápido poderia começar a
    #: ler uma linha que a transação ainda não gravou.
    queued: list[str] = field(default_factory=list)

    def as_stats(self) -> dict[str, int | bool]:
        return {
            "added": self.added,
            "updated": self.updated,
            "removed": self.removed,
            "skipped": self.skipped,
            "unsupported": self.unsupported,
            "rejected": self.rejected,
            "truncated": self.truncated,
        }


def sync_connection(
    session: Session,
    connection: ProjectDriveConnection,
    access_token: str,
    settings: Settings,
    *,
    client: httpx.Client | None = None,
) -> SyncOutcome:
    """Traz a pasta autorizada para o índice, e leva embora o que saiu dela.

    Levanta ``DriveError``/``DriveAuthError`` sem tratar: quem decide o que uma
    falha significa para a conexão é o worker, que tem a linha para carimbar.
    """
    if not connection.folder_id:
        return SyncOutcome()

    listing = drive.walk_folder(settings, access_token, connection.folder_id, client=client)

    ctx = TenantContext(
        organization_id=connection.organization_id, project_id=connection.project_id
    )
    repository = DriveDocumentRepository(session, ctx)
    existing = repository.by_external_id()

    outcome = SyncOutcome(rejected=listing.rejected, truncated=listing.truncated)

    for found in listing.files:
        current = existing.pop(found.id, None)
        _reconcile_one(
            session, repository, connection, current, found, access_token, settings,
            outcome, client=client,
        )

    # O que sobrou em `existing` não está mais na pasta — mas só é seguro concluir
    # isso de uma listagem que descreve o Drive inteiro.
    if listing.truncated:
        logger.warning(
            "drive.listing_truncated",
            extra={"project_id": str(connection.project_id), "files": len(listing.files)},
        )
    else:
        for orphan in existing.values():
            _remove(session, repository, orphan, settings)
            outcome.removed += 1

    return outcome


def _reconcile_one(
    session: Session,
    repository: DriveDocumentRepository,
    connection: ProjectDriveConnection,
    current: Document | None,
    found: drive.DriveFile,
    access_token: str,
    settings: Settings,
    outcome: SyncOutcome,
    *,
    client: httpx.Client | None,
) -> None:
    # 1. Formato que o portal não lê: vira estado com motivo, e nenhum byte é
    # pedido. A tela precisa poder responder "por que a IA não sabe disso?".
    if found.target_mime is None:
        _record_unsupported(repository, connection, current, found, found.unsupported_reason)
        outcome.unsupported += 1
        return

    # 2. Teto de tamanho, conferido antes do download. Arquivo nativo não declara
    # `size`, então para ele o teto só pode valer depois do export.
    if found.size is not None and found.size > settings.document_max_bytes:
        _record_unsupported(
            repository, connection, current, found, "Arquivo acima do teto do portal"
        )
        outcome.unsupported += 1
        return

    # 3. Portão barato: nada mudou desde a última indexação bem-sucedida.
    if (
        current is not None
        and current.ingest_state == DocumentIngestState.indexed
        and found.modified_time is not None
        and current.source_updated_at == found.modified_time
    ):
        outcome.skipped += 1
        return

    data = drive.download(settings, access_token, found, client=client)

    if len(data) > settings.document_max_bytes:
        _record_unsupported(
            repository, connection, current, found, "Arquivo acima do teto do portal"
        )
        outcome.unsupported += 1
        return
    if not data:
        _record_unsupported(repository, connection, current, found, "Arquivo vazio")
        outcome.unsupported += 1
        return

    content_hash = storage.digest(data)

    # 4. Portão exato: o `modifiedTime` mudou mas os bytes não (alguém abriu e
    # fechou o documento). Carimba a data nova para o portão barato voltar a
    # valer, e não gasta storage nem embeddings.
    if (
        current is not None
        and current.ingest_state == DocumentIngestState.indexed
        and current.content_hash == content_hash
    ):
        current.source_updated_at = found.modified_time
        outcome.skipped += 1
        return

    document = current
    if document is None:
        document = Document(
            title=found.name[:200] or "Documento",
            source=DocumentSource.drive,
            origin=DocumentOrigin.drive,
            external_id=found.id,
            author_label=connection.google_account_email,
        )
        repository.add(document)
        session.flush()  # o id entra na chave do objeto
        outcome.added += 1
    else:
        outcome.updated += 1

    previous_key = document.storage_key
    key = storage.object_key(
        connection.organization_id,
        connection.project_id,
        document.id,
        found.name,
        content_hash,
    )
    storage.put_object(settings, key, data, found.target_mime)

    document.title = found.name[:200] or document.title
    document.storage_key = key
    document.mime_type = found.target_mime
    document.byte_size = len(data)
    document.source_updated_at = found.modified_time
    document.content_hash = None  # quem carimba o hash é a ingestão, ao indexar
    document.ingest_state = DocumentIngestState.pending
    document.ingest_error = None

    if previous_key and previous_key != key:
        # A chave carrega o hash, então uma versão nova é um objeto novo. Sem esta
        # limpeza o bucket acumularia toda revisão de todo arquivo, para sempre.
        _forget_object(settings, previous_key)

    outcome.queued.append(str(document.id))


def _record_unsupported(
    repository: DriveDocumentRepository,
    connection: ProjectDriveConnection,
    current: Document | None,
    found: drive.DriveFile,
    reason: str | None,
) -> None:
    """Guarda o arquivo como metadado com motivo, sem baixá-lo.

    A linha existe para a tela explicar a ausência. Sem ela, um Drive cheio de
    formulários e desenhos pareceria sincronizado e o cliente não teria como saber
    por que o assistente não cita nada deles.
    """
    document = current
    if document is None:
        document = Document(
            title=found.name[:200] or "Documento",
            source=DocumentSource.drive,
            origin=DocumentOrigin.drive,
            external_id=found.id,
            author_label=connection.google_account_email,
        )
        repository.add(document)
    document.title = found.name[:200] or document.title
    document.mime_type = found.mime_type
    document.source_updated_at = found.modified_time
    document.ingest_state = DocumentIngestState.unsupported
    document.ingest_error = (reason or "Formato não suportado")[:500]


def _remove(
    session: Session,
    repository: DriveDocumentRepository,
    document: Document,
    settings: Settings,
) -> None:
    """Saiu da pasta, sai do portal — linha, trechos (por CASCADE) e objeto.

    Deixar o trecho no índice faria o assistente citar um documento que o cliente
    acredita ter removido, e é exatamente a citação que quem confere não encontra.
    """
    if document.storage_key:
        _forget_object(settings, document.storage_key)
    session.delete(document)


def _forget_object(settings: Settings, key: str) -> None:
    """Remoção best-effort: um objeto órfão custa disco, e derrubar o sync por
    causa dele custaria o índice inteiro do projeto."""
    try:
        storage.delete_object(settings, key)
    except (storage.StorageDisabled, storage.StorageError):
        logger.warning("drive.object_not_removed", extra={"key": key})


def now() -> datetime:
    return datetime.now(timezone.utc)
