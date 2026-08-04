"""Trabalho assíncrono: sync do Biahflow, ingestão e o e-mail das notificações."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from celery import Celery
from sqlalchemy import select

from portal_api import ingestion, mailer, notifications, storage
from portal_api.ai.embeddings import get_embedder
from portal_api.config import get_settings
from portal_api.db.session import DbRole, get_session
from portal_api.integrations import biahflow
from portal_api.models import (
    Document,
    DocumentChunk,
    DocumentIngestState,
    Notification,
    PendingItem,
    Project,
    User,
)
from portal_api.repositories import DocumentChunkRepository, TenantContext

logger = logging.getLogger(__name__)

settings = get_settings()
celery_app = Celery("portal_api", broker=settings.redis_url, backend=settings.redis_url)


@celery_app.task(name="portal_api.ingest_document")
def ingest_document(document_id: str) -> dict[str, object]:
    """Arquivo → texto → trechos → embeddings (ADR 0014).

    Roda sob ``portal_system``, como o sync: aqui não há principal nem requisição,
    e o tenant vem do próprio documento — que só existe porque uma rota de
    administração já verificou quem o enviou. O caminho de requisição continua
    apenas lendo o índice.

    Idempotente pelo hash do arquivo: reenfileirar a mesma task não recobra
    embeddings nem reescreve o índice. Toda falha vira estado no documento, não
    exceção perdida no log — é a tela de administração que precisa explicar o
    que houve.
    """
    current = get_settings()
    with get_session(role=DbRole.system) as session:
        document = session.get(Document, uuid.UUID(document_id))
        if document is None or not document.storage_key:
            return {"status": "skipped", "chunks": 0}

        try:
            data = storage.get_object(current, document.storage_key)
        except (storage.StorageDisabled, storage.StorageError) as exc:
            return _fail(document, DocumentIngestState.failed, str(exc))

        content_hash = storage.digest(data)
        if (
            document.ingest_state == DocumentIngestState.indexed
            and document.content_hash == content_hash
        ):
            return {"status": "unchanged", "chunks": 0}

        try:
            pages = ingestion.extract(data, document.mime_type)
        except ingestion.UnsupportedDocument as exc:
            return _fail(
                document, DocumentIngestState.unsupported, f"Formato não suportado: {exc}"
            )
        except ingestion.ExtractionFailed as exc:
            return _fail(document, DocumentIngestState.failed, str(exc))

        chunks = ingestion.chunk_pages(
            pages, size=current.chunk_size_chars, overlap=current.chunk_overlap_chars
        )
        if not chunks:
            # Um PDF digitalizado é imagem, não texto. Dizer isso é melhor do que
            # marcar `indexed` com zero trechos e deixar o chat mudo sem motivo.
            return _fail(
                document,
                DocumentIngestState.unsupported,
                "Documento sem texto extraível (digitalizado?)",
            )

        embedder = get_embedder(current)
        try:
            vectors = embedder.embed_documents([chunk.text for chunk in chunks])
        except Exception as exc:  # provedor fora do ar: o documento espera
            logger.exception("Falha ao gerar embeddings do documento %s", document_id)
            return _fail(document, DocumentIngestState.failed, f"Embeddings: {exc}")

        ctx = TenantContext(
            organization_id=document.organization_id, project_id=document.project_id
        )
        DocumentChunkRepository(session, ctx).replace_for_document(
            document.id,
            [
                DocumentChunk(
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    location=chunk.location,
                    char_count=len(chunk.text),
                    embedding=vector,
                    embedding_model=embedder.model_name,
                    content_hash=chunk.content_hash,
                )
                for chunk, vector in zip(chunks, vectors)
            ],
        )
        document.ingest_state = DocumentIngestState.indexed
        document.ingest_error = None
        document.content_hash = content_hash
        document.indexed_at = datetime.now(timezone.utc)
        return {"status": "indexed", "chunks": len(chunks)}


@celery_app.task(name="portal_api.reindex_project")
def reindex_project(organization_id: str, project_id: str) -> dict[str, object]:
    """Enfileira os documentos do projeto que ainda não viraram índice.

    Rede de segurança para o que ficou para trás quando o broker esteve fora do
    ar: o upload já respondeu, o documento está `pending`, e nada mais o
    empurraria sozinho.
    """
    with get_session(role=DbRole.system) as session:
        pending = list(
            session.execute(
                select(Document.id).where(
                    Document.project_id == uuid.UUID(project_id),
                    Document.organization_id == uuid.UUID(organization_id),
                    Document.ingest_state == DocumentIngestState.pending,
                    Document.storage_key.is_not(None),
                )
            ).scalars()
        )
    for document_id in pending:
        queue_document_ingestion(str(document_id))
    return {"project_id": project_id, "queued": len(pending)}


def _fail(document: Document, state: DocumentIngestState, reason: str) -> dict[str, object]:
    """Carimba o motivo no documento. Só a mensagem do erro — nunca trecho do
    conteúdo (``docs/data-classification.md``)."""
    document.ingest_state = state
    document.ingest_error = reason[:500]
    return {"status": state.value, "chunks": 0}


@celery_app.task(name="portal_api.sync_biahflow_project")
def sync_biahflow_project(biahflow_project_id: int) -> dict[str, str]:
    """Backfill/reconciliation: pull a project snapshot from Biahflow into the read model (ADR 0006)."""
    current = get_settings()
    snapshot = biahflow.fetch_snapshot(
        current.biahflow_base_url, current.biahflow_read_token, biahflow_project_id
    )
    # The sync *creates* the tenant, so it runs under portal_system (BYPASSRLS):
    # there is no organization/project context to bind yet (ADR 0010).
    with get_session(role=DbRole.system) as session:
        project = biahflow.sync_snapshot(session, snapshot)
        project_id = str(project.id)
    queue_project_digests(project_id)
    return {"project_id": project_id, "status": "synced"}


@celery_app.task(name="portal_api.send_project_digests")
def send_project_digests(project_id: str) -> dict[str, int]:
    """Um e-mail por pessoa com o que aquele sync mudou (ADR 0012).

    Trabalha sobre ``emailed_at IS NULL`` em vez de receber a lista de ids do
    chamador, e isso é deliberado: um webhook do Biahflow costuma mexer em várias
    coisas de uma vez, e a fila pode perder ou repetir uma task. Perguntar ao
    banco "o que ainda não foi avisado?" faz a repetição virar no-op e a perda
    virar atraso — o próximo sync varre o que sobrou.
    """
    current = get_settings()
    sent = 0
    with get_session(role=DbRole.system) as session:
        pending = list(
            session.execute(
                select(Notification)
                .where(
                    Notification.project_id == uuid.UUID(project_id),
                    Notification.emailed_at.is_(None),
                )
                .order_by(Notification.occurred_at)
            ).scalars()
        )
        if not pending:
            return {"sent": 0, "notifications": 0}

        project = session.get(Project, uuid.UUID(project_id))
        by_user: dict[uuid.UUID, list[Notification]] = defaultdict(list)
        for item in pending:
            by_user[item.user_id].append(item)

        now = datetime.now(timezone.utc)
        for user_id, items in by_user.items():
            user = session.get(User, user_id)
            if user is None:
                continue
            if not user.notify_by_email:
                # Carimba mesmo sem enviar: quem desligou o e-mail não deve
                # receber tudo de uma vez se religar a preferência depois.
                _stamp(items, now)
                continue
            try:
                mailer.send(
                    current,
                    mailer.build_message(
                        current,
                        to=user.email,
                        subject=_subject(items, project),
                        body=_body(items, project, current.portal_web_url),
                    ),
                )
            except mailer.MailerDisabled:
                logger.info("E-mail das notificações desligado; nada enviado")
                return {"sent": sent, "notifications": len(pending)}
            except Exception:  # SMTP fora do ar: tenta de novo no próximo sync
                logger.exception("Falha ao enviar o resumo para %s", user_id)
                continue
            _stamp(items, now)
            sent += 1

    return {"sent": sent, "notifications": len(pending)}


@celery_app.task(name="portal_api.notify_pending_created")
def notify_pending_created(project_id: str, pending_id: str) -> dict[str, int]:
    """Avisa o time da pendência que a IA abriu por falta de contexto (ADR 0007).

    Uma task e não uma escrita no próprio pedido: o chat roda sob ``portal_app``,
    que não tem ``INSERT`` em ``notification`` — e essa ausência é o desenho, não
    um descuido. O caminho de requisição não origina nada.
    """
    with get_session(role=DbRole.system) as session:
        project = session.get(Project, uuid.UUID(project_id))
        item = session.get(PendingItem, uuid.UUID(pending_id))
        if project is None or item is None:
            return {"created": 0}
        created = notifications.fan_out(
            session,
            project,
            [
                notifications.Change(
                    kind=notifications.NotificationKind.pending_opened,
                    title="Pendência aberta pela IA",
                    detail=item.title,
                    dedupe_key=f"pending:portal:{item.id}",
                )
            ],
        )
        return {"created": len(created)}


def queue_project_digests(project_id: str) -> None:
    """Enfileira o resumo sem deixar a fila derrubar quem chamou.

    O webhook já persistiu as notificações quando chega aqui: elas aparecem no
    portal com ou sem Redis. Falhar a requisição do Biahflow por causa do e-mail
    trocaria uma degradação por uma indisponibilidade.
    """
    try:
        send_project_digests.delay(project_id)
    except Exception:  # broker fora do ar
        logger.warning("Não foi possível enfileirar o resumo do projeto %s", project_id)


def queue_pending_notification(project_id: str, pending_id: str) -> None:
    """Mesma tolerância do :func:`queue_project_digests`, para a pendência do chat."""
    try:
        notify_pending_created.delay(project_id, pending_id)
    except Exception:
        logger.warning("Não foi possível enfileirar o aviso da pendência %s", pending_id)


def queue_document_ingestion(document_id: str) -> None:
    """Mesma tolerância, para a ingestão do documento (ADR 0014).

    O arquivo já está no storage e a linha já está comitada quando chegamos
    aqui: com o broker fora do ar o upload continua valendo e o documento fica
    `pending`, visível na tela e recuperável por ``reindex_project``. Derrubar o
    upload por causa da fila trocaria uma degradação por uma indisponibilidade.
    """
    try:
        ingest_document.delay(document_id)
    except Exception:
        logger.warning("Não foi possível enfileirar a ingestão do documento %s", document_id)


def _stamp(items: list[Notification], when: datetime) -> None:
    for item in items:
        item.emailed_at = when


def _subject(items: list[Notification], project: Project | None) -> str:
    name = project.name if project else "seu projeto"
    if len(items) == 1:
        return f"{items[0].title} — {name}"
    return f"{len(items)} atualizações em {name}"


def _body(items: list[Notification], project: Project | None, portal_url: str) -> str:
    name = project.name if project else "seu projeto"
    lines = [f"Novidades em {name}:", ""]
    lines += [
        f"- {item.title}" + (f": {item.detail}" if item.detail else "") for item in items
    ]
    lines += ["", f"Ver no portal: {portal_url}"]
    return "\n".join(lines)
