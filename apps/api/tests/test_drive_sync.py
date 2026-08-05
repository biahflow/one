"""Reconciliação da pasta do Drive com o índice (ADR 0016).

O adapter já provou a fronteira sem banco (``test_drive_adapter.py``). Aqui o que
se prova é o que a reconciliação faz com o índice do cliente: o que ela cria, o
que ela **não** recobra, e sobretudo o que ela não apaga.

Os dois testes que mais importam são negativos — a listagem incompleta que não
remove nada e o consentimento revogado que preserva o índice. Os dois vêm direto
do ``docs/runbooks/drive-sync-failure.md`` ("preservar último índice válido"), e
os dois descrevem falhas do Google virando perda de conhecimento do cliente.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from drive_fake import DOC_MIME, SHORTCUT_MIME, FakeDrive, FakeFile
from portal_api import crypto, worker
from portal_api.config import get_settings
from portal_api.integrations import google_drive
from portal_api.models import (
    Document,
    DocumentChunk,
    DocumentIngestState,
    DocumentOrigin,
    DocumentSource,
    DriveSyncState,
    Organization,
    Project,
    ProjectDriveConnection,
    ProjectStatus,
)

pytestmark = pytest.mark.integration

ROOT = "folder-autorizada"


@pytest.fixture
def project(migrated_engine: Engine) -> Iterator[Project]:
    tag = uuid.uuid4().hex[:8]
    with Session(migrated_engine) as session:
        organization = Organization(name="Acme", slug=f"acme-drive-{tag}")
        session.add(organization)
        session.flush()
        record = Project(
            organization_id=organization.id,
            name="Automação Financeira",
            slug=f"acme-drive-project-{tag}",
            status=ProjectStatus.in_implementation,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        organization_id = organization.id

    yield record

    with Session(migrated_engine) as session:
        session.execute(delete(Organization).where(Organization.id == organization_id))
        session.commit()


@pytest.fixture
def drive_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "google_drive_client_id", "client-id")
    monkeypatch.setattr(settings, "google_drive_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_drive_api_base_url", "http://drive/drive/v3")
    monkeypatch.setattr(settings, "google_oauth_token_url", "http://drive/token")
    monkeypatch.setattr(settings, "drive_token_encryption_key", crypto.generate_key())


@pytest.fixture
def fake_drive(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeDrive]:
    """Um Drive de mentira ligado no ponto de injeção do worker."""
    fake = FakeDrive()
    fake.folder(ROOT, "Contratos")
    client = fake.client()
    monkeypatch.setattr(google_drive, "session_client", lambda: client)
    yield fake
    client.close()


def _connect(engine: Engine, project: Project, **overrides: object) -> uuid.UUID:
    """Grava a conexão como o callback do OAuth faria, sem passar pelo HTTP."""
    settings = get_settings()
    aad = crypto.aad_for(project.organization_id, project.id)
    with Session(engine) as session:
        connection = ProjectDriveConnection(
            organization_id=project.organization_id,
            project_id=project.id,
            folder_id=ROOT,
            folder_name="Contratos",
            google_account_email="interno@portallabs.local",
            refresh_token_sealed=crypto.seal("refresh-token", aad=aad, settings=settings),
            granted_scope=settings.google_drive_scope,
            connected_at=datetime.now(timezone.utc),
        )
        for field, value in overrides.items():
            setattr(connection, field, value)
        session.add(connection)
        session.commit()
        return connection.id


def _text_file(fake: FakeDrive, file_id: str, body: bytes, modified: str | None = None) -> FakeFile:
    return fake.add(
        FakeFile(
            id=file_id,
            name=f"{file_id}.txt",
            mime_type="text/plain",
            parents=[ROOT],
            content=body,
            modified_time=modified or "2026-08-01T10:00:00.000Z",
        )
    )


def _documents(engine: Engine, project: Project) -> list[Document]:
    with Session(engine) as session:
        return list(
            session.execute(
                select(Document)
                .where(Document.project_id == project.id)
                .order_by(Document.title)
            ).scalars()
        )


# --- o caminho feliz -------------------------------------------------------------


def test_the_authorized_folder_becomes_queued_documents(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    _text_file(fake_drive, "contrato", b"O contrato preve suporte por 12 meses.")
    connection_id = _connect(migrated_engine, project)

    result = worker.sync_drive_project(str(connection_id))

    assert result["status"] == "synced"
    assert result["added"] == 1
    documents = _documents(migrated_engine, project)
    assert len(documents) == 1
    assert documents[0].origin == DocumentOrigin.drive
    assert documents[0].source == DocumentSource.drive
    assert documents[0].external_id == "contrato"
    assert documents[0].ingest_state == DocumentIngestState.pending
    assert documents[0].storage_key in fake_storage
    # Uma entrada só: o sync enfileira a **varredura**, e é ela que decide se
    # a ingestão acontece (ADR 0017).
    assert queued_ingestions == [str(documents[0].id)]


def test_the_indexed_document_from_the_drive_is_citable(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    """Fecha a corrente inteira: o arquivo do Drive vira trecho com embedding.

    Sem isto o conector estaria "funcionando" e o chat continuaria mudo — que é
    exatamente o estado em que a Fase 4 estava antes dele.
    """
    _text_file(fake_drive, "contrato", b"O contrato preve suporte por 12 meses.")
    connection_id = _connect(migrated_engine, project)
    worker.sync_drive_project(str(connection_id))

    _scan_and_ingest(queued_ingestions[0])

    with Session(migrated_engine) as session:
        chunks = list(
            session.execute(
                select(DocumentChunk).where(DocumentChunk.project_id == project.id)
            ).scalars()
        )
    assert chunks and all(chunk.embedding is not None for chunk in chunks)


def test_a_google_doc_is_exported_and_stored_in_a_format_the_portal_reads(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    fake_drive.add(
        FakeFile(
            id="ata",
            name="Ata da reunião",
            mime_type=DOC_MIME,
            parents=[ROOT],
            exported=b"conteudo exportado",
        )
    )
    connection_id = _connect(migrated_engine, project)

    worker.sync_drive_project(str(connection_id))

    documents = _documents(migrated_engine, project)
    assert documents[0].mime_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert fake_storage[documents[0].storage_key] == b"conteudo exportado"



def _scan_and_ingest(document_id: str) -> None:
    """A corrente completa desde a ADR 0017: varre, e só então indexa.

    O sync do Drive enfileira a varredura, não a ingestão — chamar
    ``ingest_document`` direto aqui provaria menos do que parece, porque a guarda
    no começo dela recusaria um documento que ninguém varreu.
    """
    worker.scan_document(document_id)
    worker.ingest_document(document_id)


# --- idempotência ----------------------------------------------------------------


def test_a_second_sync_over_the_same_drive_downloads_nothing(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    """Um sync horário de uma pasta parada custa uma listagem e nada mais."""
    _text_file(fake_drive, "contrato", b"O contrato preve suporte por 12 meses.")
    connection_id = _connect(migrated_engine, project)
    worker.sync_drive_project(str(connection_id))
    _scan_and_ingest(queued_ingestions[0])
    fake_drive.media_requests.clear()
    queued_ingestions.clear()

    result = worker.sync_drive_project(str(connection_id))

    assert result["skipped"] == 1
    assert result["added"] == 0
    assert fake_drive.media_requests == []
    assert queued_ingestions == []
    assert len(_documents(migrated_engine, project)) == 1


def test_a_touched_file_with_the_same_bytes_is_not_reindexed(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    """Abrir e fechar um documento muda o `modifiedTime` e não muda os bytes.

    O portão barato deixa passar; o exato é quem impede o portal de recobrar
    embeddings por causa de um clique.
    """
    found = _text_file(fake_drive, "contrato", b"O contrato preve suporte.")
    connection_id = _connect(migrated_engine, project)
    worker.sync_drive_project(str(connection_id))
    _scan_and_ingest(queued_ingestions[0])
    queued_ingestions.clear()

    found.modified_time = "2026-08-02T11:00:00.000Z"
    result = worker.sync_drive_project(str(connection_id))

    assert result["skipped"] == 1
    assert queued_ingestions == []


def test_a_changed_file_is_downloaded_again_and_queued_for_reindexing(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    found = _text_file(fake_drive, "contrato", b"Versao um.")
    connection_id = _connect(migrated_engine, project)
    worker.sync_drive_project(str(connection_id))
    _scan_and_ingest(queued_ingestions[0])
    queued_ingestions.clear()
    first_key = _documents(migrated_engine, project)[0].storage_key

    found.content = b"Versao dois, com clausula nova."
    found.modified_time = "2026-08-03T09:00:00.000Z"
    result = worker.sync_drive_project(str(connection_id))

    documents = _documents(migrated_engine, project)
    assert result["updated"] == 1
    assert documents[0].ingest_state == DocumentIngestState.pending
    assert documents[0].storage_key != first_key
    # Uma entrada só: o sync enfileira a **varredura**, e é ela que decide se
    # a ingestão acontece (ADR 0017).
    assert queued_ingestions == [str(documents[0].id)]
    # A chave carrega o hash: sem a limpeza o bucket guardaria toda revisão.
    assert first_key not in fake_storage


def test_a_file_removed_from_the_drive_leaves_no_row_chunk_or_object(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    """Continuar citando um contrato que o cliente apagou é a citação que quem
    confere não encontra."""
    _text_file(fake_drive, "contrato", b"O contrato preve suporte.")
    connection_id = _connect(migrated_engine, project)
    worker.sync_drive_project(str(connection_id))
    _scan_and_ingest(queued_ingestions[0])
    key = _documents(migrated_engine, project)[0].storage_key

    del fake_drive.files["contrato"]
    result = worker.sync_drive_project(str(connection_id))

    assert result["removed"] == 1
    assert _documents(migrated_engine, project) == []
    assert key not in fake_storage
    with Session(migrated_engine) as session:
        remaining = session.execute(
            select(DocumentChunk).where(DocumentChunk.project_id == project.id)
        ).scalars().all()
    assert remaining == []


# --- o que nunca pode ser apagado ------------------------------------------------


def test_a_listing_that_fails_midway_never_deletes(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    """Uma indisponibilidade do Google não pode virar perda do índice do cliente.

    A falha é **no meio**, e não na primeira chamada, de propósito: o caso perigoso
    é justamente aquele em que a travessia já enumerou alguma coisa e poderia
    concluir que o resto não existe mais.
    """
    _text_file(fake_drive, "contrato", b"O contrato preve suporte.")
    fake_drive.folder("anexos", "Anexos", parents=[ROOT])
    connection_id = _connect(migrated_engine, project)
    worker.sync_drive_project(str(connection_id))
    _scan_and_ingest(queued_ingestions[0])

    fake_drive.list_calls = 0
    fake_drive.fail_listing_after = 1
    result = worker.sync_drive_project(str(connection_id))

    assert result["status"] == "failed"
    assert len(_documents(migrated_engine, project)) == 1
    with Session(migrated_engine) as session:
        connection = session.get(ProjectDriveConnection, connection_id)
        assert connection is not None
        assert connection.sync_state == DriveSyncState.failed
        assert connection.last_sync_error
        # Falha de rede não é consentimento vencido: a pasta continua ligada.
        assert connection.enabled is True


def test_a_truncated_listing_never_deletes(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Estourar o teto descreve um Drive menor do que o real."""
    _text_file(fake_drive, "contrato-a", b"Primeiro contrato.")
    _text_file(fake_drive, "contrato-b", b"Segundo contrato.")
    connection_id = _connect(migrated_engine, project)
    worker.sync_drive_project(str(connection_id))
    assert len(_documents(migrated_engine, project)) == 2

    monkeypatch.setattr(get_settings(), "drive_max_files", 1)
    result = worker.sync_drive_project(str(connection_id))

    assert result["truncated"] is True
    assert result["removed"] == 0
    assert len(_documents(migrated_engine, project)) == 2


def test_a_revoked_consent_pauses_the_folder_and_keeps_the_index(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    """O runbook manda preservar o último índice válido e renovar a autorização."""
    _text_file(fake_drive, "contrato", b"O contrato preve suporte.")
    connection_id = _connect(migrated_engine, project)
    worker.sync_drive_project(str(connection_id))
    _scan_and_ingest(queued_ingestions[0])

    fake_drive.consent_revoked = True
    result = worker.sync_drive_project(str(connection_id))

    assert result["status"] == "unauthorized"
    assert len(_documents(migrated_engine, project)) == 1
    with Session(migrated_engine) as session:
        connection = session.get(ProjectDriveConnection, connection_id)
        assert connection is not None
        assert connection.enabled is False
        assert connection.sync_state == DriveSyncState.failed
        # O consentimento fica na linha: reconectar é ação da tela, não do worker.
        assert connection.refresh_token_sealed is not None


def test_an_uploaded_document_survives_the_drive_sync(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    """O sync do Drive não mexe no que não é dele — o mesmo recorte por `origin`
    que a ADR 0014 §2 usou para o snapshot do Biahflow."""
    with Session(migrated_engine) as session:
        session.add(
            Document(
                organization_id=project.organization_id,
                project_id=project.id,
                title="Enviado pela administração",
                source=DocumentSource.upload,
                origin=DocumentOrigin.portal,
                storage_key="chave/do/upload",
                ingest_state=DocumentIngestState.indexed,
            )
        )
        session.commit()
    connection_id = _connect(migrated_engine, project)

    worker.sync_drive_project(str(connection_id))

    titles = {d.title for d in _documents(migrated_engine, project)}
    assert "Enviado pela administração" in titles


# --- formatos e tetos ------------------------------------------------------------


def test_an_unsupported_drive_file_becomes_a_state_the_screen_can_explain(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    """Responde "por que a IA não sabe disso?" sem consultar log."""
    fake_drive.add(
        FakeFile(id="zip", name="tudo.zip", mime_type="application/zip", parents=[ROOT], content=b"PK")
    )
    connection_id = _connect(migrated_engine, project)

    result = worker.sync_drive_project(str(connection_id))

    documents = _documents(migrated_engine, project)
    assert result["unsupported"] == 1
    assert documents[0].ingest_state == DocumentIngestState.unsupported
    assert documents[0].ingest_error
    assert documents[0].storage_key is None
    assert fake_drive.media_requests == []


def test_a_file_over_the_cap_is_refused_before_the_download(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _text_file(fake_drive, "gigante", b"x" * 5_000)
    monkeypatch.setattr(get_settings(), "document_max_bytes", 100)
    connection_id = _connect(migrated_engine, project)

    result = worker.sync_drive_project(str(connection_id))

    assert result["unsupported"] == 1
    assert fake_drive.media_requests == []
    assert _documents(migrated_engine, project)[0].storage_key is None


def test_a_shortcut_never_becomes_a_document(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    fake_drive.add(FakeFile(id="atalho", name="atalho", mime_type=SHORTCUT_MIME, parents=[ROOT]))
    connection_id = _connect(migrated_engine, project)

    result = worker.sync_drive_project(str(connection_id))

    assert result["rejected"] == 1
    assert _documents(migrated_engine, project) == []


# --- a guarda de sobreposição ----------------------------------------------------


def test_a_second_sync_finds_the_row_claimed_and_returns_busy(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
) -> None:
    """Dois ticks do beat chegando juntos: exatamente um ganha, e quem decide é o banco."""
    connection_id = _connect(
        migrated_engine,
        project,
        sync_state=DriveSyncState.running,
        sync_started_at=datetime.now(timezone.utc),
    )

    assert worker.sync_drive_project(str(connection_id)) == {"status": "busy"}


def test_a_stale_claim_is_reclaimed_after_the_timeout(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    """Sem esta janela, um worker morto no meio travaria a pasta para sempre."""
    stale = datetime.now(timezone.utc) - timedelta(
        seconds=get_settings().drive_sync_stale_after_seconds + 60
    )
    connection_id = _connect(
        migrated_engine,
        project,
        sync_state=DriveSyncState.running,
        sync_started_at=stale,
    )

    assert worker.sync_drive_project(str(connection_id))["status"] == "synced"


def test_a_paused_connection_is_not_synced(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
) -> None:
    """`enabled=false` é o que o runbook chama de "pausar a pasta afetada".

    E o estado é distinto de `busy`: os dois param o sync, mas só um é transitório,
    e quem apertou o botão precisa saber qual.
    """
    connection_id = _connect(migrated_engine, project, enabled=False)

    assert worker.sync_drive_project(str(connection_id)) == {"status": "paused"}


def test_the_beat_tick_only_fans_out_enabled_connections(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _connect(migrated_engine, project, enabled=False)
    queued: list[str] = []
    monkeypatch.setattr(worker, "queue_drive_sync", queued.append)

    worker.sync_due_drive_connections()

    assert queued == []


# --- a chave de cifra ------------------------------------------------------------


def test_a_rotated_key_reseals_the_token_on_the_next_sync(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """É o que faz a rotação terminar sozinha, sem ninguém refazer o consentimento."""
    settings = get_settings()
    connection_id = _connect(migrated_engine, project)
    with Session(migrated_engine) as session:
        before = session.get(ProjectDriveConnection, connection_id).refresh_token_sealed

    monkeypatch.setattr(settings, "drive_token_encryption_key_previous", settings.drive_token_encryption_key)
    monkeypatch.setattr(settings, "drive_token_encryption_key", crypto.generate_key())

    assert worker.sync_drive_project(str(connection_id))["status"] == "synced"

    with Session(migrated_engine) as session:
        after = session.get(ProjectDriveConnection, connection_id).refresh_token_sealed
    assert after != before
    aad = crypto.aad_for(project.organization_id, project.id)
    assert crypto.unseal(after, aad=aad, settings=settings) == "refresh-token"


def test_without_an_encryption_key_the_sync_fails_instead_of_running(
    migrated_engine: Engine,
    project: Project,
    drive_settings: None,
    fake_drive: FakeDrive,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = _connect(migrated_engine, project)
    monkeypatch.setattr(get_settings(), "drive_token_encryption_key", "")
    monkeypatch.setattr(get_settings(), "drive_token_encryption_key_previous", "")

    assert worker.sync_drive_project(str(connection_id))["status"] == "failed"
