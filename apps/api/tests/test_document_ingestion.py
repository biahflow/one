"""Ingestão de documentos: arquivo → texto → trechos → índice (ADR 0014).

Duas metades. A primeira é pura — extração e chunking não tocam banco nem rede, e
é onde mora a regra que sustenta a citação: **o trecho nunca cruza a fronteira da
página**. A segunda roda a task de verdade contra o Postgres, porque idempotência
e estado de falha só existem no banco.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from portal_api import worker
from portal_api.ingestion import (
    ExtractedPage,
    ExtractionFailed,
    UnsupportedDocument,
    chunk_pages,
    extract,
)
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

# --- extração e chunking (sem banco) --------------------------------------


def test_a_plain_text_file_becomes_one_page_without_pagination() -> None:
    pages = extract("Contrato de suporte.".encode("utf-8"), "text/plain")

    assert [page.number for page in pages] == [0]
    # Página 0 = formato sem paginação, e a citação sai sem localização. Melhor
    # do que uma página inventada.
    assert chunk_pages(pages)[0].location == ""


def test_an_unknown_format_is_a_state_and_not_a_crash() -> None:
    with pytest.raises(UnsupportedDocument):
        extract(b"PK\x03\x04", "application/zip")


def test_a_corrupt_pdf_fails_loudly_instead_of_indexing_garbage() -> None:
    with pytest.raises(ExtractionFailed):
        extract(b"not really a pdf", "application/pdf")


def test_the_mime_type_ignores_the_charset_suffix() -> None:
    pages = extract("olá".encode("utf-8"), "text/plain; charset=utf-8")

    assert pages[0].text == "olá"


def test_a_chunk_never_spans_two_pages() -> None:
    """A regra que faz "página 3" ser verdade e não estimativa.

    Duas páginas curtas caberiam folgadamente num trecho só; se coubessem, a
    citação de uma delas apontaria para texto da outra.
    """
    pages = [
        ExtractedPage(number=1, text="O contrato começa em março."),
        ExtractedPage(number=2, text="A renovação é automática."),
    ]

    chunks = chunk_pages(pages, size=1200, overlap=150)

    assert [chunk.location for chunk in chunks] == ["página 1", "página 2"]
    assert "renovação" not in chunks[0].text
    assert "março" not in chunks[1].text


def test_a_long_page_is_split_with_overlap_and_stays_ordered() -> None:
    page = ExtractedPage(number=7, text="\n\n".join(f"Parágrafo {i} do relatório." for i in range(60)))

    chunks = chunk_pages([page], size=300, overlap=80)

    assert len(chunks) > 1
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    assert {chunk.location for chunk in chunks} == {"página 7"}
    # A emenda entre dois trechos é onde a frase que responde costuma estar.
    assert chunks[0].text[-40:] in chunks[1].text


def test_the_same_text_always_produces_the_same_hash() -> None:
    once = chunk_pages([ExtractedPage(number=1, text="Escopo fechado.")])
    twice = chunk_pages([ExtractedPage(number=1, text="Escopo fechado.")])

    assert once[0].content_hash == twice[0].content_hash


def test_a_pdf_keeps_one_page_per_page() -> None:
    pdf = _two_page_pdf()

    pages = extract(pdf, "application/pdf")

    assert [page.number for page in pages] == [1, 2]
    assert "primeira" in pages[0].text.lower()
    assert "segunda" in pages[1].text.lower()


def _two_page_pdf() -> bytes:
    return _pdf_with_pages(["Pagina primeira do contrato", "Pagina segunda do contrato"])


def _pdf_with_pages(texts: list[str]) -> bytes:
    """Um PDF válido montado à mão — sem depender de um renderizador só para o teste."""
    page_count = len(texts)
    font_id = 3 + 2 * page_count
    objects: list[tuple[int, bytes]] = [(1, b"<</Type/Catalog/Pages 2 0 R>>")]
    kids = b" ".join(f"{3 + 2 * i} 0 R".encode() for i in range(page_count))
    objects.append(
        (2, b"<</Type/Pages/Kids[" + kids + b"]/Count " + str(page_count).encode() + b">>")
    )
    for index, text in enumerate(texts):
        page_id, content_id = 3 + 2 * index, 4 + 2 * index
        objects.append(
            (
                page_id,
                f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]"
                f"/Resources<</Font<</F1 {font_id} 0 R>>>>"
                f"/Contents {content_id} 0 R>>".encode(),
            )
        )
        stream = f"BT /F1 12 Tf 20 150 Td ({text}) Tj ET".encode("latin-1")
        objects.append(
            (
                content_id,
                b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
            )
        )
    objects.append((font_id, b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"))
    objects.sort()

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number, body in objects:
        offsets[number] = len(out)
        out += f"{number} 0 obj".encode() + body + b"endobj\n"
    xref_at = len(out)
    size = len(objects) + 1
    out += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for number, _ in objects:
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += f"trailer<</Size {size}/Root 1 0 R>>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


# --- a task de ingestão (com banco) ---------------------------------------


@pytest.fixture
def project(migrated_engine: Engine) -> Iterator[Project]:
    tag = uuid.uuid4().hex[:8]
    with Session(migrated_engine) as session:
        organization = Organization(name="Acme", slug=f"acme-ingest-{tag}")
        session.add(organization)
        session.flush()
        record = Project(
            organization_id=organization.id,
            name="Automação Financeira",
            slug=f"acme-ingest-project-{tag}",
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


def _document(
    engine: Engine,
    project: Project,
    data: bytes,
    mime_type: str,
    objects: dict[str, bytes],
) -> uuid.UUID:
    """Grava a linha e o objeto como o upload faria, sem passar pelo HTTP.

    Nasce com ``scan_state=skipped`` porque estes testes são sobre a **ingestão**:
    a varredura é a etapa anterior e tem arquivo próprio. Deixar `pending` faria
    todos eles baterem na guarda da ADR 0017 e provarem só que a guarda existe —
    o que `test_document_scan.py` já prova, uma vez.
    """
    with Session(engine) as session:
        record = Document(
            organization_id=project.organization_id,
            project_id=project.id,
            title="Contrato",
            source=DocumentSource.upload,
            origin=DocumentOrigin.portal,
            mime_type=mime_type,
            byte_size=len(data),
            ingest_state=DocumentIngestState.pending,
            scan_state=ScanState.skipped,
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
def test_a_document_becomes_chunks_with_an_embedding(
    migrated_engine: Engine, project: Project, fake_storage: dict[str, bytes]
) -> None:
    text = "O contrato prevê suporte por 12 meses.\n\nA renovação é automática."
    document_id = _document(migrated_engine, project, text.encode(), "text/plain", fake_storage)

    result = worker.ingest_document(str(document_id))

    assert result["status"] == "indexed"
    with Session(migrated_engine) as session:
        record = session.get(Document, document_id)
        chunks = list(
            session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            ).scalars()
        )
        assert record is not None
        assert record.ingest_state == DocumentIngestState.indexed
        assert record.indexed_at is not None
        assert record.content_hash == digest(text.encode())
        assert chunks and all(chunk.embedding is not None for chunk in chunks)
        # O tenant é carimbado pelo repositório, nunca pelo chamador.
        assert {chunk.organization_id for chunk in chunks} == {project.organization_id}
        assert {chunk.project_id for chunk in chunks} == {project.id}


@pytest.mark.integration
def test_reingesting_the_same_file_is_a_no_op(
    migrated_engine: Engine, project: Project, fake_storage: dict[str, bytes]
) -> None:
    """Task reentregue não recobra embeddings nem reescreve o índice."""
    document_id = _document(
        migrated_engine, project, b"Escopo fechado em marco.", "text/plain", fake_storage
    )
    worker.ingest_document(str(document_id))
    with Session(migrated_engine) as session:
        first = [
            chunk.id
            for chunk in session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            ).scalars()
        ]

    result = worker.ingest_document(str(document_id))

    assert result["status"] == "unchanged"
    with Session(migrated_engine) as session:
        again = [
            chunk.id
            for chunk in session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            ).scalars()
        ]
    assert again == first


@pytest.mark.integration
def test_a_changed_file_replaces_the_whole_index(
    migrated_engine: Engine, project: Project, fake_storage: dict[str, bytes]
) -> None:
    """Documento que encolheu não deixa trecho órfão apontando para texto que sumiu."""
    document_id = _document(
        migrated_engine,
        project,
        "\n\n".join(f"Parágrafo {i} sobre o contrato de suporte." for i in range(40)).encode(),
        "text/plain",
        fake_storage,
    )
    worker.ingest_document(str(document_id))

    with Session(migrated_engine) as session:
        record = session.get(Document, document_id)
        assert record is not None and record.storage_key
        fake_storage[record.storage_key] = b"Somente uma linha agora."
    worker.ingest_document(str(document_id))

    with Session(migrated_engine) as session:
        chunks = list(
            session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.ordinal)
            ).scalars()
        )
    assert len(chunks) == 1
    assert chunks[0].ordinal == 0
    assert "Parágrafo" not in chunks[0].text


@pytest.mark.integration
def test_an_unsupported_format_becomes_a_state_the_screen_can_explain(
    migrated_engine: Engine, project: Project, fake_storage: dict[str, bytes]
) -> None:
    document_id = _document(
        migrated_engine, project, b"PK\x03\x04", "application/zip", fake_storage
    )

    result = worker.ingest_document(str(document_id))

    assert result["status"] == "unsupported"
    with Session(migrated_engine) as session:
        record = session.get(Document, document_id)
        assert record is not None
        assert record.ingest_state == DocumentIngestState.unsupported
        assert "não suportado" in (record.ingest_error or "").lower()


@pytest.mark.integration
def test_a_file_without_extractable_text_says_so_instead_of_indexing_nothing(
    migrated_engine: Engine, project: Project, fake_storage: dict[str, bytes]
) -> None:
    """Um PDF digitalizado é imagem. `indexed` com zero trechos calaria o chat sem motivo."""
    document_id = _document(migrated_engine, project, b"   \n\n  ", "text/plain", fake_storage)

    result = worker.ingest_document(str(document_id))

    assert result["status"] == "unsupported"
    with Session(migrated_engine) as session:
        record = session.get(Document, document_id)
        assert record is not None and "texto" in (record.ingest_error or "")


@pytest.mark.integration
def test_a_missing_object_marks_the_document_failed(
    migrated_engine: Engine, project: Project, fake_storage: dict[str, bytes]
) -> None:
    document_id = _document(migrated_engine, project, b"conteudo", "text/plain", fake_storage)
    fake_storage.clear()

    result = worker.ingest_document(str(document_id))

    assert result["status"] == "failed"
    with Session(migrated_engine) as session:
        record = session.get(Document, document_id)
        assert record is not None
        assert record.ingest_state == DocumentIngestState.failed
        assert record.ingest_error


@pytest.mark.integration
def test_reindex_project_picks_up_what_the_broker_lost(
    migrated_engine: Engine,
    project: Project,
    fake_storage: dict[str, bytes],
    queued_ingestions: list[str],
) -> None:
    pending = _document(migrated_engine, project, b"Primeiro.", "text/plain", fake_storage)
    done = _document(migrated_engine, project, b"Segundo.", "text/plain", fake_storage)
    worker.ingest_document(str(done))

    result = worker.reindex_project(str(project.organization_id), str(project.id))

    assert result["queued"] == 1
    assert queued_ingestions == [str(pending)]
