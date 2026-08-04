"""Envio de e-mail do portal — SMTP puro, sem SDK de provedor.

O convite sai pelo SMTP do *realm* (o Keycloak é quem manda, ADR 0011); este é o
caminho do próprio portal, para as notificações da Fase 2. É `smtplib` da
biblioteca padrão de propósito: o requisito é "Mailpit local, provedor
configurável em produção", e todo provedor sério fala SMTP. Um SDK amarraria o
portal a um fornecedor para ganhar nada.

Nenhuma mensagem daqui carrega conteúdo do projeto além do que o destinatário já
vê no portal: o e-mail é um aviso com um link, não um relatório
(`docs/data-classification.md`).
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from portal_api.config import Settings

logger = logging.getLogger(__name__)


class MailerDisabled(RuntimeError):
    """SMTP não configurado — o chamador decide se isso é erro ou silêncio."""


def build_message(
    settings: Settings, *, to: str, subject: str, body: str
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = f"{settings.notifications_from_name} <{settings.notifications_from_email}>"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return message


def send(settings: Settings, message: EmailMessage) -> None:
    """Entrega a mensagem. Levanta :class:`MailerDisabled` quando não há SMTP."""
    if not settings.notifications_email_enabled or not settings.smtp_host:
        raise MailerDisabled("notifications_email_enabled está desligado")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_user:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(message)
