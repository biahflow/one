"""Trabalho assíncrono: sync do Biahflow, ingestão e o e-mail das notificações."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from celery import Celery
from sqlalchemy import select

from portal_api import mailer, notifications
from portal_api.config import get_settings
from portal_api.db.session import DbRole, get_session
from portal_api.integrations import biahflow
from portal_api.models import Notification, PendingItem, Project, User

logger = logging.getLogger(__name__)

settings = get_settings()
celery_app = Celery("portal_api", broker=settings.redis_url, backend=settings.redis_url)


@celery_app.task(name="portal_api.reindex_project")
def reindex_project(organization_id: str, project_id: str) -> dict[str, str]:
    """Idempotent placeholder for Drive/document ingestion with explicit tenant scope."""
    return {"organization_id": organization_id, "project_id": project_id, "status": "queued"}


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
