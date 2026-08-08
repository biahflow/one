"""Trabalho assíncrono: sync do Biahflow e do Drive, ingestão e o e-mail das notificações."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx
from celery import Celery
from celery.signals import before_task_publish, setup_logging, task_postrun, task_prerun
from sqlalchemy import and_, or_, select, text, update

from portal_api import (
    contact_budget,
    crypto,
    drive_sync,
    ingestion,
    mailer,
    notifications,
    onboarding,
    retention,
    scanner,
    storage,
)
from portal_api.ai.embeddings import get_embedder
from portal_api.config import get_settings
from portal_api.db.session import DbRole, get_session
from portal_api.integrations import biahflow
from portal_api.integrations import google_drive as drive
from portal_api.integrations import whatsapp
from portal_api.models import (
    ContactKind,
    DataErasureRequest,
    Document,
    DocumentChunk,
    DocumentIngestState,
    DriveSyncState,
    ErasureState,
    Notification,
    PendingItem,
    Project,
    ProjectDriveConnection,
    User,
)
from portal_api.preflight import preflight
from portal_api.repositories import DocumentChunkRepository, TenantContext
from portal_api.scanner import ScanState
from portal_api.telemetry import (
    TRACE_HEADER,
    bind_trace_id,
    configure_logging,
    current_trace_id,
    new_trace_id,
)

logger = logging.getLogger(__name__)

settings = get_settings()
configure_logging()
# Pela mesma razão da API, e não por simetria (ADR 0022): o worker é quem alcança
# o storage, o Drive e o SMTP, então subir com o segredo do exemplo aqui custa
# tanto quanto lá. Um dos dois processos protegido seria pior que nenhum, porque
# a metade verde faria o ambiente parecer conferido.
preflight(settings)
celery_app = Celery("portal_api", broker=settings.redis_url, backend=settings.redis_url)

# **O laço ocioso tem preço quando o Redis é cobrado por comando.**
#
# No compose o Redis é nosso e um `BRPOP` a mais não custa nada. Em HML ele é
# gerenciado (Upstash), a conta é por comando, e um worker parado consome cota sem
# nenhum trabalho ter acontecido — que é o modo de falha em que a fila para no meio
# do mês e ninguém liga uma coisa à outra.
#
# `polling_interval` é o intervalo entre visitas do Celery à fila quando ela está
# vazia. O default (1s) dá ~86 mil comandos por dia por instância só para descobrir
# que não há nada a fazer. Cinco segundos derrubam isso para ~17 mil e custam, no
# pior caso, cinco segundos de latência numa fila cujo trabalho mais rápido é
# mandar um e-mail.
#
# `visibility_timeout` precisa ser **maior que a tarefa mais longa**, senão o
# Celery devolve para a fila uma tarefa que ainda está rodando e ela executa duas
# vezes. A mais longa aqui é a ingestão de documento (varredura, extração,
# embedding); uma hora é folga confortável.
celery_app.conf.broker_transport_options = {
    "polling_interval": 5.0,
    "visibility_timeout": 3600,
}
celery_app.conf.result_expires = 3600

# O primeiro agendador do projeto (ADR 0016). A ADR 0005 já reivindicava o sync do
# Drive como job desde sempre; o que faltava era quem acordasse.
#
# **O beat é singleton.** Duas réplicas significam dois ticks, e dois ticks
# significam dois syncs concorrentes por conexão. A guarda de sobreposição em
# `_claim_drive_sync` faz o segundo virar no-op, mas contar com ela para o caso
# normal seria desenhar para o acidente: o compose fixa uma réplica só.
celery_app.conf.beat_schedule = {}
if settings.drive_sync_enabled:
    celery_app.conf.beat_schedule["drive-sync-due"] = {
        "task": "portal_api.sync_due_drive_connections",
        "schedule": timedelta(seconds=settings.drive_sync_interval_seconds),
    }
# A poda (Fase 5, ADR 0017). Ligada por padrão, ao contrário do sync do Drive:
# aquele precisa de credencial de terceiro para fazer sentido, e este só precisa
# do próprio banco. Um portal que nunca poda é o estado que as ADRs 0012/0015
# descreveram como dívida, e o padrão deve ser o comportamento correto.
if settings.retention_enabled:
    celery_app.conf.beat_schedule["retention-purge"] = {
        "task": "portal_api.purge_expired_data",
        "schedule": timedelta(seconds=settings.retention_interval_seconds),
    }
    celery_app.conf.beat_schedule["erasure-requests"] = {
        "task": "portal_api.run_erasure_requests",
        "schedule": timedelta(seconds=settings.retention_interval_seconds),
    }
# O alerta de cliente travado (Fase 7, RFC 001 passo 3, ADR 0040). Ligado por
# padrão pelo mesmo argumento da poda, e com a mesma consequência declarada: como
# nenhum compose passa `ONBOARDING_ALERT_ENABLED`, desligá-lo exige editar o
# compose. É a postura certa — um radar que nasce desligado é um radar que ninguém
# liga.
if settings.onboarding_alert_enabled:
    celery_app.conf.beat_schedule["onboarding-stuck"] = {
        "task": "portal_api.alert_stuck_onboarding",
        "schedule": timedelta(seconds=settings.onboarding_alert_interval_seconds),
    }


# --------------------------------------------------------------------------- #
# O `trace_id` atravessa a fila (Fase 5, ADR 0018)
#
# Em **header da mensagem**, nunca em argumento da task: mudar assinatura
# obrigaria a mexer em cada `.delay()` do repositório e, pior, uma mensagem
# publicada antes de um deploy chegaria a um worker que espera um parâmetro a
# mais. O header é ignorado por quem não o conhece.
# --------------------------------------------------------------------------- #


@setup_logging.connect
def _keep_our_logging(**_kwargs) -> None:
    """Impede o Celery de reconfigurar o `logging` por cima do nosso.

    Não é preferência de formato: o `setup_logging_subsystem` do Celery aplica
    um `dictConfig` com `disable_existing_loggers`, o que marca
    ``logger.disabled = True`` em **todo** logger `portal_api.*` já criado. O
    worker então rodaria sem uma linha de log nossa — exatamente a telemetria
    que esta fase existe para ter. Ter um receptor conectado a este sinal faz o
    Celery pular a configuração inteira, que é o contrato documentado dele; o
    `configure_logging()` do topo do módulo continua sendo quem configura.
    """
    configure_logging()


@before_task_publish.connect
def _publish_trace_id(headers=None, **_kwargs) -> None:
    """Carimba na mensagem o id da requisição que a originou.

    Roda no processo de **quem publica** — a API, no meio de um request — e por
    isso `current_trace_id()` ainda é o da requisição. Vazio significa que a
    publicação não veio de uma (um comando de CLI, um teste): nesse caso não
    inventa um aqui, porque quem consumir cunha o próprio e a alternativa seria
    dois ids para a mesma execução.
    """
    trace_id = current_trace_id()
    if trace_id and headers is not None:
        headers[TRACE_HEADER] = trace_id


@task_prerun.connect
def _bind_task_trace_id(task=None, **_kwargs) -> None:
    """Liga o id no contexto do worker antes do corpo da task rodar.

    Sem pai — as três tasks do beat — cunha um e o marca como raiz: um tick
    agendado não continua a história de ninguém, mas ainda precisa ser
    encontrável por um identificador só.
    """
    request = getattr(task, "request", None)
    inherited = None
    if request is not None:
        # `.get()` porque o Context do Celery devolve None para chave ausente em
        # vez de levantar, e um header inexistente é o caso normal do beat.
        inherited = (getattr(request, "headers", None) or {}).get(TRACE_HEADER)
    trace_id = bind_trace_id(inherited or new_trace_id())
    logger.info(
        "task.started",
        extra={
            "task": getattr(task, "name", ""),
            "root": "beat" if not inherited else "request",
            "trace_id": trace_id,
        },
    )


@task_postrun.connect
def _log_task_finished(task=None, state=None, **_kwargs) -> None:
    logger.info(
        "task.finished",
        extra={"task": getattr(task, "name", ""), "status": state or "UNKNOWN"},
    )


#: Os dois vereditos que autorizam a indexação. ``skipped`` entra porque a stack
#: local e o CI não têm ClamAV, e exigir ``clean`` ali faria a demo nunca indexar
#: nada — mas ele continua sendo *outra coisa* que ``clean`` no banco e na tela,
#: e é assim que "ninguém varreu" permanece dizível (ADR 0017).
_SCAN_ALLOWS_INDEX = (ScanState.clean, ScanState.skipped)


@celery_app.task(name="portal_api.scan_document")
def scan_document(document_id: str) -> dict[str, object]:
    """Varre o arquivo antes de ele virar texto (Fase 5, ADR 0017).

    Entra **entre** o objeto e a extração, porque extrair texto já é abrir o
    arquivo com um parser — e o parser é justamente a superfície que um arquivo
    malicioso procura. Roda sob ``portal_system``, como a ingestão, e pelo mesmo
    motivo: não há principal aqui, e o tenant vem da linha.

    Limpo (ou sem scanner) encadeia a ingestão. Infectado carimba o estado e
    **apaga o objeto do bucket**: ao contrário de ``delete_document``, que
    preserva o arquivo do cliente, aqui o arquivo é a coisa de que se quer
    distância. A linha fica — é ela que explica na tela e sustenta o `audit_log`.
    """
    current = get_settings()
    with get_session(role=DbRole.system) as session:
        document = session.get(Document, uuid.UUID(document_id))
        if document is None or not document.storage_key:
            return {"status": "skipped"}

        try:
            data = storage.get_object(current, document.storage_key)
        except (storage.StorageDisabled, storage.StorageError) as exc:
            # Storage fora do ar não é arquivo limpo. `error` mantém o documento
            # fora do índice e a causa na tela.
            document.scan_state = ScanState.error
            document.scan_error = str(exc)[:500]
            document.scanned_at = datetime.now(timezone.utc)
            return {"status": ScanState.error.value}

        verdict = scanner.get_scanner(current).scan(data)
        note = verdict.signature or verdict.detail
        document.scan_state = verdict.state
        document.scan_error = note[:500] if note else None
        document.scanned_at = datetime.now(timezone.utc)

        if verdict.state is ScanState.infected:
            document.ingest_state = DocumentIngestState.rejected
            document.ingest_error = f"Barrado pela varredura: {verdict.signature}"
            # O único evento do portal que acorda alguém por uma **ocorrência**,
            # e não por uma taxa (`docs/runbooks/alerts.md`). A contenção já
            # aconteceu logo abaixo; o alerta existe para avisar o tenant, que é
            # a parte que nenhum código faz sozinho. Sem o nome do arquivo: o
            # que interessa é qual organização, e `data-classification.md` não
            # quer conteúdo de cliente no log.
            logger.warning(
                "document.infected",
                extra={
                    "document_id": document_id,
                    "organization_id": str(document.organization_id),
                    "project_id": str(document.project_id),
                    "signature": verdict.signature,
                },
            )
            storage_key = document.storage_key
            # A chave sai da linha antes do commit: o objeto vai embora logo
            # abaixo, e um `storage_key` apontando para o que não existe faria a
            # URL temporária prometer um arquivo ausente.
            document.storage_key = None
        else:
            storage_key = None

    if storage_key:
        try:
            storage.delete_object(current, storage_key)
        except (storage.StorageDisabled, storage.StorageError):
            # A linha já diz `rejected` e o arquivo já não é alcançável por
            # nenhuma rota. Objeto órfão é trabalho da retenção, não motivo para
            # repetir a varredura.
            logger.warning(
                "document.infected_object_kept",
                extra={"document_id": document_id, "storage_key": storage_key},
            )
        return {"status": ScanState.infected.value}

    if verdict.state in _SCAN_ALLOWS_INDEX:
        queue_document_ingestion(document_id)
    return {"status": verdict.state.value}


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

        # A fronteira conferida duas vezes, como a pasta do Drive na ADR 0016.
        # `scan_document` já encadeia só o que passou, mas uma task antiga na
        # fila ou um reenfileiramento manual chegariam aqui direto — e indexar é
        # exatamente o que não pode acontecer sem varredura.
        if document.scan_state not in _SCAN_ALLOWS_INDEX:
            return {"status": "unscanned", "chunks": 0}

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
            logger.exception("embedding.failed", extra={"document_id": document_id})
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

    Recomeça pela varredura e não pela ingestão. O documento parado pode ter
    ficado para trás *antes* de ser varrido, e "reindexar" não é motivo para
    pular a fronteira — ``scan_document`` reencadeia a ingestão quando é o caso.
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
        queue_document_scan(str(document_id))
    return {"project_id": project_id, "queued": len(pending)}


@celery_app.task(name="portal_api.sync_due_drive_connections")
def sync_due_drive_connections() -> dict[str, int]:
    """O tick do beat, e ele só faz fan-out.

    Mesma forma de ``reindex_project``: seleciona ids e enfileira uma task por
    projeto. Sincronizar dentro do tick faria uma pasta lenta atrasar todas as
    outras, e uma exceção derrubaria o agendamento inteiro.
    """
    with get_session(role=DbRole.system) as session:
        due = list(
            session.execute(
                select(ProjectDriveConnection.id).where(
                    ProjectDriveConnection.enabled.is_(True),
                    ProjectDriveConnection.refresh_token_sealed.is_not(None),
                    ProjectDriveConnection.folder_id.is_not(None),
                )
            ).scalars()
        )
    for connection_id in due:
        queue_drive_sync(str(connection_id))
    return {"queued": len(due)}


@celery_app.task(name="portal_api.sync_drive_project")
def sync_drive_project(connection_id: str) -> dict[str, object]:
    """Reconcilia a pasta autorizada de um projeto com o índice (ADR 0016).

    Sob ``portal_system`` como a ingestão, e pelo mesmo motivo (ADR 0014 §3): o
    tenant vem da linha da conexão, que só existe porque uma rota de administração
    já verificou ``internal_admin``. Não há identificador vindo de fora.

    Três transações, de propósito. A primeira reivindica o sync e **commita**, para
    outro worker enxergar ``running`` em vez de bloquear numa linha travada pelo
    tempo inteiro de uma pasta grande. A segunda faz o trabalho. A terceira só
    existe quando algo falhou, para carimbar o motivo — é a mesma separação que
    ``agent_auth`` faz entre resolver a credencial e usar o que ela abriu.
    """
    current = get_settings()
    identifier = uuid.UUID(connection_id)

    with get_session(role=DbRole.system) as session:
        connection = session.get(ProjectDriveConnection, identifier)
        if connection is None:
            return {"status": "skipped"}
        # Pausada não é ocupada. Os dois casos param o sync, mas só um deles é
        # transitório — e quem chamou pelo botão precisa saber qual.
        if not connection.enabled or not connection.refresh_token_sealed:
            return {"status": "paused"}
        if not _claim_drive_sync(session, identifier, current):
            return {"status": "busy"}

    client = drive.session_client()
    try:
        with get_session(role=DbRole.system) as session:
            connection = session.get(ProjectDriveConnection, identifier)
            if connection is None:
                return {"status": "skipped"}

            access_token = _drive_access_token(connection, current, client=client)
            outcome = drive_sync.sync_connection(
                session, connection, access_token, current, client=client
            )

            connection.sync_state = DriveSyncState.idle
            connection.sync_started_at = None
            connection.last_sync_at = drive_sync.now()
            connection.last_sync_error = None
            connection.last_sync_stats = outcome.as_stats()
    except drive.DriveAuthError as exc:
        # O consentimento não vale mais. Pausa a pasta e **preserva o índice**: o
        # runbook é explícito, e apagar por autorização vencida transformaria um
        # problema de credencial numa perda de conhecimento.
        _fail_drive_sync(identifier, str(exc), disable=True)
        return {"status": "unauthorized"}
    except (drive.DriveError, drive.DriveDisabled, crypto.SealedSecretError) as exc:
        _fail_drive_sync(identifier, str(exc), disable=False)
        return {"status": "failed"}

    for document_id in outcome.queued:
        queue_document_scan(document_id)
    return {"status": "synced", **outcome.as_stats(), "queued": len(outcome.queued)}


def _claim_drive_sync(session, connection_id: uuid.UUID, current) -> bool:
    """Reivindica o sync com um ``UPDATE`` condicional, não com ler-e-escrever.

    Dois ticks chegando juntos precisam que exatamente um ganhe, e quem decide
    isso é o banco. A janela de ``sync_started_at`` é o que impede um worker morto
    no meio de um sync de deixar a conexão travada para sempre — sem ela, "está
    rodando" seria indistinguível de "ficou rodando".
    """
    stale = drive_sync.now() - timedelta(seconds=current.drive_sync_stale_after_seconds)
    claimed = session.execute(
        text(
            "UPDATE project_drive_connection"
            "   SET sync_state = 'running', sync_started_at = now(), updated_at = now()"
            " WHERE id = :id AND enabled"
            "   AND refresh_token_sealed IS NOT NULL"
            "   AND (sync_state <> 'running' OR sync_started_at < :stale)"
            " RETURNING id"
        ),
        {"id": connection_id, "stale": stale},
    ).scalar_one_or_none()
    return claimed is not None


def _drive_access_token(
    connection: ProjectDriveConnection, current, *, client: httpx.Client | None = None
) -> str:
    """Abre o refresh token e troca por um access token de uma hora.

    Se o segredo foi selado com a chave anterior, re-sela agora: é o que faz uma
    rotação de chave terminar sozinha, sem migração de dados e sem obrigar
    ninguém a refazer o consentimento no Google.
    """
    if not connection.refresh_token_sealed:
        raise drive.DriveAuthError("connection has no refresh token")

    aad = crypto.aad_for(connection.organization_id, connection.project_id)
    refresh_token = crypto.unseal(connection.refresh_token_sealed, aad=aad, settings=current)
    access_token = drive.refresh_access_token(current, refresh_token, client=client)

    if crypto.needs_resealing(connection.refresh_token_sealed, current):
        connection.refresh_token_sealed = crypto.seal(refresh_token, aad=aad, settings=current)
    return access_token


def _fail_drive_sync(connection_id: uuid.UUID, reason: str, *, disable: bool) -> None:
    with get_session(role=DbRole.system) as session:
        connection = session.get(ProjectDriveConnection, connection_id)
        if connection is None:
            return
        connection.sync_state = DriveSyncState.failed
        connection.sync_started_at = None
        connection.last_sync_error = reason[:500]
        if disable:
            # Pausa sem desconectar: o consentimento fica na linha, e reconectar é
            # uma ação da tela — não algo que o worker decide sozinho.
            connection.enabled = False
        # A linha da conexão continua sendo a fonte para a tela
        # (`observability.md`); o evento existe para o alerta, que não consulta
        # o banco. `disable` é o campo que separa "reconsentir" de "tentar de
        # novo" — os dois têm destinos diferentes em `alerts.md`.
        logger.warning(
            "drive.sync_failed",
            extra={
                "connection_id": str(connection_id),
                "project_id": str(connection.project_id),
                "disable": disable,
                "reason": reason[:200],
            },
        )


def queue_drive_sync(connection_id: str) -> None:
    """Mesma tolerância a broker morto das demais filas.

    A conexão já está gravada quando chegamos aqui: sem Redis o botão
    "Sincronizar agora" não sincroniza, mas nada se perde — o próximo tick pega.
    """
    try:
        sync_drive_project.delay(connection_id)
    except Exception:
        logger.warning(
            "queue.unavailable",
            extra={"task": "sync_drive_connection", "connection_id": connection_id},
        )


def _fail(document: Document, state: DocumentIngestState, reason: str) -> dict[str, object]:
    """Carimba o motivo no documento. Só a mensagem do erro — nunca trecho do
    conteúdo (``docs/data-classification.md``)."""
    document.ingest_state = state
    document.ingest_error = reason[:500]
    return {"status": state.value, "chunks": 0}


# --- Retenção e expurgo (Fase 5, ADR 0017) ------------------------------------


@celery_app.task(name="portal_api.purge_expired_data")
def purge_expired_data() -> dict[str, object]:
    """O tick da poda: uma organização por transação (ADR 0017).

    Não é fan-out como ``sync_due_drive_connections``, e a diferença tem motivo:
    ali cada projeto fala com um Google que pode demorar, aqui é só ``DELETE`` no
    próprio banco. Uma task por organização multiplicaria mensagens sem
    encurtar nada. O que precisa ficar curto é a *transação*, e isso o lote de
    ``retention.purge_expired`` já garante.
    """
    current = get_settings()
    totals: dict[str, int] = {}
    with get_session(role=DbRole.system) as session:
        organizations = retention.organizations_with_data(session)

    for organization_id in organizations:
        # Uma transação por organização: um erro numa não deve desfazer a poda
        # das outras, e segurar todas num `commit` só é o oposto de podar em
        # lotes.
        try:
            with get_session(role=DbRole.system) as session:
                outcome = retention.purge_expired(session, organization_id, current)
        except Exception:
            logger.exception(
                "retention.purge_failed", extra={"organization_id": str(organization_id)}
            )
            continue
        for table, count in outcome.removed.items():
            totals[table] = totals.get(table, 0) + count
    return {"organizations": len(organizations), **totals}


@celery_app.task(name="portal_api.alert_stuck_onboarding")
def alert_stuck_onboarding() -> dict[str, object]:
    """O tick do alerta de cliente travado (Fase 7, RFC 001 passo 3, ADR 0040).

    Uma organização por transação, na forma de ``purge_expired_data`` logo acima e
    pelo mesmo motivo: é trabalho de banco local, e uma task por organização
    multiplicaria mensagens sem encurtar transação nenhuma.

    Quem decide se o aviso sai — e se o evento é emitido — é
    ``onboarding.raise_alert``, porque é lá que mora a resposta a "é a primeira
    vez?". Aqui só sobra o laço, o ``except`` por organização e o enfileiramento do
    digest, que sai **fora** da transação porque a task de e-mail lê as linhas do
    banco.
    """
    current = get_settings()
    with get_session(role=DbRole.system) as session:
        organizations = onboarding.organizations_to_watch(session)

    alerted = 0
    digests: list[str] = []
    for organization_id in organizations:
        try:
            with get_session(role=DbRole.system) as session:
                outcome = onboarding.raise_alert(session, organization_id, current)
        except Exception:
            logger.exception(
                "onboarding.stuck_scan_failed",
                extra={"organization_id": str(organization_id)},
            )
            continue
        if outcome is not None and outcome.notified and outcome.project_id is not None:
            alerted += 1
            digests.append(str(outcome.project_id))

    for project_id in digests:
        queue_project_digests(project_id)
    return {"organizations": len(organizations), "alerted": alerted}


@celery_app.task(name="portal_api.run_erasure_requests")
def run_erasure_requests() -> dict[str, int]:
    """Executa os pedidos de apagamento pendentes.

    A administração grava a intenção sob ``portal_admin`` e o worker a cumpre sob
    ``portal_system`` — a ADR 0015 já tinha decidido que "quando o expurgo
    chegar, não será o caminho de requisição a fazê-lo".
    """
    current = get_settings()
    with get_session(role=DbRole.system) as session:
        pending = list(
            session.execute(
                select(DataErasureRequest.id).where(
                    _erasure_is_claimable(current)
                )
            ).scalars()
        )
    done = 0
    for request_id in pending:
        if _run_erasure(request_id):
            done += 1
    return {"pending": len(pending), "completed": done}


def _erasure_is_claimable(settings):
    """``pending``, ou um ``running`` que ficou para trás (ADR 0028).

    O segundo caso é o worker que morreu **no meio** — nenhum ``except`` alcança
    um processo que sumiu, e sem esta janela a linha ficava `running` para
    sempre: `_claim_erasure` só reivindicava `pending` e este filtro só
    selecionava `pending`. É a janela que o sync do Drive tem desde a ADR 0016 e
    que este caminho deixou de copiar junto com o resto.

    Um predicado só, usado nos dois lugares, porque selecionar e reivindicar com
    regras diferentes é como se ganha um laço que escolhe o que não consegue
    pegar.
    """
    stale = retention.now() - timedelta(seconds=settings.erasure_stale_after_seconds)
    return or_(
        DataErasureRequest.state == ErasureState.pending,
        and_(
            DataErasureRequest.state == ErasureState.running,
            DataErasureRequest.started_at < stale,
        ),
    )


def _claim_erasure(session, request_id: uuid.UUID, settings) -> DataErasureRequest | None:
    """Reivindica o pedido com um ``UPDATE`` condicional, como o sync do Drive.

    Dois workers pegando o mesmo pedido precisam que exatamente um ganhe, e quem
    decide isso é o banco — não uma leitura seguida de escrita, que tem uma
    janela entre as duas.
    """
    claimed = session.execute(
        update(DataErasureRequest)
        .where(
            DataErasureRequest.id == request_id,
            _erasure_is_claimable(settings),
        )
        .values(state=ErasureState.running, started_at=retention.now())
        .returning(DataErasureRequest.id)
    ).scalar_one_or_none()
    if claimed is None:
        return None
    return session.get(DataErasureRequest, request_id)


def _run_erasure(request_id: uuid.UUID) -> bool:
    current = get_settings()
    with get_session(role=DbRole.system) as session:
        request = _claim_erasure(session, request_id, current)
        if request is None:
            return False
        organization_id = request.organization_id

    try:
        # O storage **antes** do banco, e a ordem é o inverso da do upload. Lá a
        # linha nasce primeiro porque o id dela compõe a chave do objeto; aqui a
        # linha é o que sabe quais objetos existem, então perdê-la primeiro
        # deixaria os arquivos sem quem os encontrasse. Um objeto que sobrevive a
        # uma falha no meio é recolhido na próxima passagem pelo prefixo; uma
        # linha apagada com o arquivo de pé não teria segunda chance.
        objects = storage.delete_prefix(
            current, retention.storage_prefix(organization_id)
        )
    except storage.StorageDisabled:
        # Sem storage configurado não há objeto a remover — a stack local é
        # assim. Não é motivo para o expurgo do banco não acontecer.
        objects = 0
    except storage.StorageError as exc:
        with get_session(role=DbRole.system) as session:
            failed = session.get(DataErasureRequest, request_id)
            if failed is not None:
                failed.state = ErasureState.failed
                failed.error = str(exc)[:500]
        logger.exception(
            "erasure.storage_failed", extra={"organization_id": str(organization_id)}
        )
        return False

    try:
        with get_session(role=DbRole.system) as session:
            outcome = retention.run_erasure(session, organization_id)
            request = session.get(DataErasureRequest, request_id)
            if request is not None:
                request.state = ErasureState.completed
                request.completed_at = retention.now()
                request.removed = {**outcome.removed, "storage_objects": objects}
                request.error = None
    except Exception as exc:
        # A metade do banco não tinha `except` nenhum até a ADR 0028, e o ramo
        # acima do storage tinha — a assimetria era lapso, não decisão: dez
        # linhas antes, `purge_expired_data` envolve cada organização.
        #
        # Sessão **nova** pelo mesmo motivo que lá: a que falhou foi revertida,
        # então o carimbo precisa de outra ou some junto com o rollback. É essa
        # reversão que garante que `failed` nunca descreve meia remoção.
        #
        # `failed` é terminal para o laço automático. Quem decide tentar de novo
        # é uma pessoa, pela tela (ADR 0027) — `admin.py` só bloqueia pedido
        # novo enquanto houver `pending` ou `running`, então um `failed` já
        # reabre o caminho, com linha nova e o histórico do anterior intacto.
        # Retentar sozinho gravaria o mesmo erro a cada tick numa falha
        # permanente, e dispararia junto um alerta de "qualquer ocorrência".
        with get_session(role=DbRole.system) as session:
            failed = session.get(DataErasureRequest, request_id)
            if failed is not None:
                failed.state = ErasureState.failed
                failed.error = str(exc)[:500]
        logger.exception(
            "erasure.failed", extra={"organization_id": str(organization_id)}
        )
        return False
    return True


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
                logger.info("digest.email_disabled")
                return {"sent": sent, "notifications": len(pending)}
            except Exception:  # SMTP fora do ar: tenta de novo no próximo sync
                logger.exception("digest.send_failed", extra={"user_id": str(user_id)})
                continue
            _stamp(items, now)
            sent += 1

    return {"sent": sent, "notifications": len(pending)}


@celery_app.task(name="portal_api.send_whatsapp_notices")
def send_whatsapp_notices(project_id: str) -> dict[str, int]:
    """Um aviso 1:1 por WhatsApp para quem optou pelo canal (FDD 021, ADR 0043).

    Irmão do :func:`send_project_digests` e deliberadamente **não** unificado com
    ele. São dois canais com regras diferentes — um agrega o que mudou num e-mail
    só, o outro manda uma mensagem por fato com um link —, carimbam colunas
    diferentes, e um gasta o teto de contato enquanto o outro não. Fundi-los faria
    "o que sai por qual canal" deixar de caber num arquivo, e é a mesma razão pela
    qual as duas colunas de carimbo existem em vez de uma.

    Trabalha sobre ``whatsapp_sent_at IS NULL`` pelo mesmo argumento do digest: a
    repetição vira no-op e a perda vira atraso.
    """
    current = get_settings()
    if not whatsapp.is_enabled(current):
        return {"sent": 0, "suppressed": 0, "notifications": 0}

    sent = 0
    suppressed = 0
    with get_session(role=DbRole.system) as session:
        pending = list(
            session.execute(
                select(Notification)
                .where(
                    Notification.project_id == uuid.UUID(project_id),
                    Notification.whatsapp_sent_at.is_(None),
                )
                .order_by(Notification.occurred_at)
            ).scalars()
        )
        if not pending:
            return {"sent": 0, "suppressed": 0, "notifications": 0}

        now = datetime.now(timezone.utc)
        for item in pending:
            user = session.get(User, item.user_id)
            if user is None:
                continue

            # **O consentimento é conferido aqui, e não no formulário.** É o que faz
            # a revogação alcançar o que já está na fila sem precisar varrer fila
            # nenhuma — critério de aceite (2) da FDD 021. E o carimbo sai mesmo sem
            # envio, na decisão que o digest já tinha tomado: quem religa a
            # preferência amanhã não deve receber semanas de avisos de uma vez.
            if not user.notify_by_whatsapp or not user.phone:
                item.whatsapp_sent_at = now
                continue

            # Sem link não há "coisa exata" a abrir, e a FDD proíbe cair na home.
            # Hoje todo aviso tem link (`notifications.deep_link`); a guarda existe
            # para o dia em que alguém acrescentar uma espécie sem entrada no
            # `LINK_TAB` — e aí o aviso fica no sino, em vez de o canal levar
            # alguém a lugar nenhum.
            if not item.link:
                item.whatsapp_sent_at = now
                logger.info(
                    "whatsapp.skipped_without_link", extra={"kind": item.kind.value}
                )
                continue

            if not contact_budget.claim(
                session,
                user_id=user.id,
                organization_id=item.organization_id,
                kind=ContactKind.whatsapp_notice,
                # A chave do contato é a do aviso: é o que faz a retentativa deste
                # laço não gastar uma segunda unidade do teto (ADR 0042).
                dedupe_key=item.dedupe_key,
                settings=current,
            ):
                # O teto é terminal para **este** contato. Não carimbar o deixaria
                # sair dias depois, quando a janela rolasse — um aviso velho num
                # canal de urgência, sobre um fato que o sino já mostrou.
                item.whatsapp_sent_at = now
                suppressed += 1
                continue

            try:
                whatsapp.send_notice(
                    current,
                    to=user.phone,
                    # Só título e link. O `detail` **não** vai: é o campo de texto
                    # livre do modelo, e é por onde um trecho de documento ou um
                    # valor comercial passariam a viajar sem ninguém decidir isso.
                    title=item.title,
                    url=f"{current.portal_web_url.rstrip('/')}{item.link}",
                    client=whatsapp.session_client(),
                )
            except whatsapp.WhatsappDisabled:
                logger.info("whatsapp.disabled")
                break
            except whatsapp.WhatsappError:
                # **Pausa em vez de insistir**, o tratamento que o conector de Drive
                # dá a uma falha no Google: sai do laço em vez de atirar os demais
                # avisos contra um fornecedor que acabou de recusar. Sem carimbo, e
                # o orçamento já gasto não se perde — a chave de dedupe faz a
                # próxima passagem reusá-lo.
                logger.warning(
                    "whatsapp.send_failed", extra={"notification_id": str(item.id)}
                )
                break

            item.whatsapp_sent_at = now
            sent += 1

    return {"sent": sent, "suppressed": suppressed, "notifications": len(pending)}


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


@celery_app.task(name="portal_api.notify_pending_comment")
def notify_pending_comment(project_id: str, comment_id: str) -> dict[str, int]:
    """Avisa o **outro lado** de um comentário na pendência (ADR 0032).

    Uma task, e pelo mesmo motivo de :func:`notify_pending_created`: a rota roda
    sob ``portal_app``, que não tem ``INSERT`` em ``notification`` — e essa
    ausência é o desenho. O caminho de requisição não origina aviso.

    ``exclude_user_id`` é quem escreveu: receber notificação do próprio
    comentário é o ruído que ensina a ignorar o sino.
    """
    from portal_api.models import PendingItemComment

    with get_session(role=DbRole.system) as session:
        comment = session.get(PendingItemComment, uuid.UUID(comment_id))
        project = session.get(Project, uuid.UUID(project_id))
        if comment is None or project is None:
            return {"created": 0}
        item = session.get(PendingItem, comment.pending_item_id)
        created = notifications.fan_out(
            session,
            project,
            [
                notifications.Change(
                    kind=notifications.NotificationKind.pending_commented,
                    title=f"{comment.author_label} comentou numa pendência",
                    detail=item.title if item is not None else None,
                    # Único por comentário: um reenvio da mensagem não repete o
                    # aviso, e dois comentários seguidos não se anulam.
                    dedupe_key=f"comment:{comment.id}",
                )
            ],
            exclude_user_id=comment.author_user_id,
        )
        return {"created": len(created)}


def queue_pending_comment_notification(project_id: str, comment_id: str) -> None:
    """Mesma tolerância a broker morto das demais filas.

    O comentário já está commitado quando chegamos aqui: quem espera é o aviso, e
    derrubar a resposta por causa dele faria a pessoa achar que não escreveu.
    """
    try:
        notify_pending_comment.delay(project_id, comment_id)
    except Exception:
        logger.warning(
            "queue.unavailable",
            extra={"task": "notify_pending_comment", "comment_id": comment_id},
        )


def queue_project_digests(project_id: str) -> None:
    """Enfileira o resumo sem deixar a fila derrubar quem chamou.

    O webhook já persistiu as notificações quando chega aqui: elas aparecem no
    portal com ou sem Redis. Falhar a requisição do Biahflow por causa do e-mail
    trocaria uma degradação por uma indisponibilidade.
    """
    try:
        send_project_digests.delay(project_id)
    except Exception:  # broker fora do ar
        logger.warning(
            "queue.unavailable",
            extra={"task": "send_project_digests", "project_id": project_id},
        )
    # O canal vai junto e num `try` **próprio**: um broker que engoliu o digest não
    # deve levar o WhatsApp junto no mesmo `except`, e o contrário também não. São
    # duas entregas independentes desde a coluna de carimbo (ADR 0043).
    try:
        send_whatsapp_notices.delay(project_id)
    except Exception:  # broker fora do ar
        logger.warning(
            "queue.unavailable",
            extra={"task": "send_whatsapp_notices", "project_id": project_id},
        )


def queue_pending_notification(project_id: str, pending_id: str) -> None:
    """Mesma tolerância do :func:`queue_project_digests`, para a pendência do chat."""
    try:
        notify_pending_created.delay(project_id, pending_id)
    except Exception:
        logger.warning(
            "queue.unavailable",
            extra={"task": "notify_pending_created", "pending_id": pending_id},
        )


def queue_erasure_requests() -> None:
    """Acorda o expurgo assim que o pedido é gravado (ADR 0017).

    Mesma tolerância a broker morto das demais filas, e aqui ela custa ainda
    menos: o pedido está comitado, e o tick do beat pega o que a fila perdeu. A
    diferença entre enfileirar e não enfileirar é minutos, não o trabalho.
    """
    try:
        run_erasure_requests.delay()
    except Exception:
        logger.warning("queue.unavailable", extra={"task": "run_erasure_requests"})


def queue_document_scan(document_id: str) -> None:
    """A porta única do arquivo para o índice (ADR 0017).

    Quem quer que um documento seja indexado chama **isto**, e não
    ``queue_document_ingestion``: é a varredura que decide se a ingestão
    acontece. Ter um ponto de entrada só é o que faz o arquivo vindo do Drive
    passar pela mesma fronteira do que foi enviado na tela, sem código próprio
    para cada origem.

    Mesma tolerância a broker morto das demais filas: o arquivo já está no
    storage e a linha já está comitada, então sem Redis o upload continua
    valendo e o documento fica `pending`, visível na tela e recuperável por
    ``reindex_project``.
    """
    try:
        scan_document.delay(document_id)
    except Exception:
        logger.warning(
            "queue.unavailable",
            extra={"task": "scan_document", "document_id": document_id},
        )


def queue_document_ingestion(document_id: str) -> None:
    """Enfileira a ingestão de um documento **já varrido**.

    Chamada por ``scan_document`` depois do veredito, e não de fora: quem tem um
    documento novo em mãos quer ``queue_document_scan``. A guarda no começo de
    ``ingest_document`` existe para o caso de alguém chamar mesmo assim.
    """
    try:
        ingest_document.delay(document_id)
    except Exception:
        logger.warning(
            "queue.unavailable",
            extra={"task": "ingest_document", "document_id": document_id},
        )


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
