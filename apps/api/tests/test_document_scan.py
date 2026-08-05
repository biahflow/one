"""Varredura antes da indexação (Fase 5, ADR 0017).

Duas metades, como em ``test_document_ingestion.py``. A primeira é pura — o
adapter não toca banco nem rede, e é onde mora a decisão que dá sentido ao resto:
**um scanner ausente não devolve "limpo"**. A segunda roda a task contra o
Postgres, porque "o objeto sumiu do bucket" e "a ingestão recusou" só existem lá.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from portal_api import scanner, worker
from portal_api.config import Settings
from portal_api.models import (
    Document,
    DocumentChunk,
    DocumentIngestState,
    DocumentOrigin,
    DocumentSource,
    Organization,
    Project,
    ProjectStatus,
)
from portal_api.scanner import ScanState
from portal_api.storage import digest, object_key

# A cadeia de teste padrão, montada em pedaços pelo mesmo motivo do
# `scanner.py`: escrita inteira e literal, faria um antivírus de verdade acusar
# este arquivo no checkout de quem clonar o repositório.
EICAR = (
    "X5O!P%@AP[4\\PZX54(P^)7CC)7}$"
    "EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
    "!$H+H*"
).encode("ascii")


# --- o adapter (sem banco) -------------------------------------------------


def test_without_a_scanner_the_verdict_is_skipped_and_never_clean() -> None:
    """A decisão central da ADR 0017, e a única que não se pode afrouxar depois.

    ``clean`` é uma afirmação sobre o arquivo. Ninguém a fez aqui, então ninguém
    pode registrá-la — é a mesma regra que o `AGENTS.md` impõe ao assistente, e
    não haveria por que o portal se permitir em segurança o que proíbe na IA.
    """
    verdict = scanner.OfflineScanner().scan(b"Contrato de suporte, 12 meses.")

    assert verdict.state is ScanState.skipped
    assert verdict.state is not ScanState.clean


def test_the_offline_scanner_recognizes_the_standard_test_signature() -> None:
    verdict = scanner.OfflineScanner().scan(EICAR)

    assert verdict.state is ScanState.infected
    assert verdict.signature == "Eicar-Test-Signature"


def test_the_signature_is_found_even_buried_in_a_larger_file() -> None:
    """Um anexo real não é só a assinatura — ela vem no meio de outra coisa."""
    verdict = scanner.OfflineScanner().scan(b"cabecalho\n" + EICAR + b"\nrodape")

    assert verdict.state is ScanState.infected


def test_the_adapter_is_chosen_by_configuration_like_the_embedder() -> None:
    assert isinstance(scanner.get_scanner(Settings(clamav_host="")), scanner.OfflineScanner)
    assert isinstance(
        scanner.get_scanner(Settings(clamav_host="clamav")), scanner.ClamavScanner
    )


def test_a_dead_clamd_is_an_error_and_not_a_clean_file() -> None:
    """Antivírus fora do ar é o dia em que a barreira mais importa.

    Porta 1 em localhost recusa a conexão na hora — não é um teste de rede, é um
    ``ECONNREFUSED`` determinístico.
    """
    verdict = scanner.ClamavScanner("127.0.0.1", 1, timeout=1.0).scan(b"qualquer coisa")

    assert verdict.state is ScanState.error
    assert verdict.state is not ScanState.clean


# --- a task (com banco) ----------------------------------------------------


@pytest.fixture
def project(migrated_engine: Engine) -> Iterator[Project]:
    tag = uuid.uuid4().hex[:8]
    with Session(migrated_engine) as session:
        organization = Organization(name="Acme", slug=f"acme-scan-{tag}")
        session.add(organization)
        session.flush()
        record = Project(
            organization_id=organization.id,
            name="Automação Financeira",
            slug=f"acme-scan-project-{tag}",
            status=ProjectStatus.in_implementation,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        yield record


def _document(
    engine: Engine, project: Project, data: bytes, objects: dict[str, bytes]
) -> uuid.UUID:
    """A linha e o objeto como o upload os deixa: por varrer."""
    with Session(engine) as session:
        record = Document(
            organization_id=project.organization_id,
            project_id=project.id,
            title="Contrato",
            source=DocumentSource.upload,
            origin=DocumentOrigin.portal,
            mime_type="text/plain",
            byte_size=len(data),
            ingest_state=DocumentIngestState.pending,
        )
        session.add(record)
        session.flush()
        record.storage_key = object_key(
            project.organization_id, project.id, record.id, "contrato.txt", digest(data)
        )
        objects[record.storage_key] = data
        session.commit()
        return record.id


@pytest.mark.integration
def test_a_new_document_starts_unscanned(
    migrated_engine: Engine, project: Project, fake_storage: dict[str, bytes]
) -> None:
    """O padrão da coluna em linha nova é `pending`, não `skipped`.

    O `server_default` da migração é `skipped` e vale para o acervo que já
    existia — carimbar de `clean` o que foi indexado antes de haver varredura
    seria o banco afirmar o que ninguém verificou. Mas o documento **novo** tem
    de nascer devendo a varredura, senão a guarda nunca dispara.
    """
    document_id = _document(migrated_engine, project, b"Contrato.", fake_storage)

    with Session(migrated_engine) as session:
        assert session.get(Document, document_id).scan_state is ScanState.pending


@pytest.mark.integration
def test_a_clean_file_is_stamped_and_chains_into_the_index(
    migrated_engine: Engine,
    project: Project,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    text = b"O contrato preve suporte por 12 meses."
    document_id = _document(migrated_engine, project, text, fake_storage)

    result = worker.scan_document(str(document_id))

    assert result["status"] == ScanState.skipped.value
    assert queued_ingestions == [str(document_id)]
    with Session(migrated_engine) as session:
        record = session.get(Document, document_id)
        assert record.scan_state is ScanState.skipped
        assert record.scanned_at is not None
        assert record.ingest_state is DocumentIngestState.pending


@pytest.mark.integration
def test_an_infected_file_is_rejected_and_the_object_is_destroyed(
    migrated_engine: Engine,
    project: Project,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    """O avesso de ``delete_document``, e de propósito.

    Ali o arquivo do cliente é preservado porque é conteúdo no lugar errado.
    Aqui ele é a coisa de que se quer distância: sai do bucket, e a linha fica
    para a tela explicar e o `audit_log` guardar o rastro.
    """
    document_id = _document(migrated_engine, project, EICAR, fake_storage)
    assert fake_storage != {}

    result = worker.scan_document(str(document_id))

    assert result["status"] == ScanState.infected.value
    assert fake_storage == {}
    assert queued_ingestions == []
    with Session(migrated_engine) as session:
        record = session.get(Document, document_id)
        assert record.scan_state is ScanState.infected
        assert record.ingest_state is DocumentIngestState.rejected
        assert record.scan_error == "Eicar-Test-Signature"
        # Sem chave: um `storage_key` apontando para o que já não existe faria a
        # URL temporária prometer um arquivo ausente.
        assert record.storage_key is None


@pytest.mark.integration
def test_the_index_refuses_a_document_nobody_scanned(
    migrated_engine: Engine, project: Project, fake_storage: dict[str, bytes]
) -> None:
    """A fronteira conferida duas vezes, como a pasta do Drive na ADR 0016.

    ``scan_document`` só encadeia o que passou, mas uma task antiga na fila ou um
    reenfileiramento manual chegam aqui direto — e indexar é exatamente o que não
    pode acontecer sem varredura.
    """
    text = b"O contrato preve suporte por 12 meses."
    document_id = _document(migrated_engine, project, text, fake_storage)

    result = worker.ingest_document(str(document_id))

    assert result["status"] == "unscanned"
    with Session(migrated_engine) as session:
        chunks = list(
            session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            ).scalars()
        )
    assert chunks == []


@pytest.mark.integration
def test_an_infected_document_never_reaches_the_index_even_if_reenqueued(
    migrated_engine: Engine,
    project: Project,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    """O ataque óbvio: varrer, ser barrado, e pedir a ingestão assim mesmo."""
    document_id = _document(migrated_engine, project, EICAR, fake_storage)
    worker.scan_document(str(document_id))

    result = worker.ingest_document(str(document_id))

    # Sem `storage_key` a ingestão já não tem o que ler — e mesmo que tivesse, a
    # guarda de `scan_state` recusaria. Duas barreiras, nenhuma delas sozinha.
    assert result["status"] == "skipped"
    with Session(migrated_engine) as session:
        chunks = list(
            session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            ).scalars()
        )
    assert chunks == []


@pytest.mark.integration
def test_storage_out_of_reach_is_an_error_and_not_a_clean_verdict(
    migrated_engine: Engine, project: Project, fake_storage: dict[str, bytes]
) -> None:
    document_id = _document(migrated_engine, project, b"Contrato.", fake_storage)
    fake_storage.clear()  # o objeto sumiu debaixo da task

    result = worker.scan_document(str(document_id))

    assert result["status"] == ScanState.error.value
    with Session(migrated_engine) as session:
        assert session.get(Document, document_id).scan_state is ScanState.error
