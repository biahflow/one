"""O canal de WhatsApp, atrás de flag e agnóstico de fornecedor (FDD 021, ADR 0043).

Transporte puro sobre ``httpx``, sem SDK, na forma de :mod:`portal_api.integrations.google_drive`
e pelo mesmo motivo: são poucos endpoints, o ``httpx`` já está aqui, e um SDK traria
uma segunda opinião sobre retentativa e timeout dentro de um worker que já tem a
sua. O produto não conhece o nome do fornecedor — quem o conhece é este arquivo.

**A mensagem não tem campo livre, e isso é a garantia, não o estilo.** A FDD 021
exige que nenhum trecho de documento e nenhum dado comercial saiam pelo canal, e
uma regra dessas não se cumpre pedindo cuidado a quem chama: :func:`send_notice`
recebe **um título e uma URL**, e monta o corpo sozinho. Não existe parâmetro por
onde conteúdo pudesse viajar — em particular, o ``detail`` da notificação **não
entra**, que é justamente o campo de texto livre do modelo. A asserção do teste é
sobre o pedido enviado, que é a única forma de provar que algo não sai.

**Duas direções, como no e-sign e no Biahflow.** Saída: :func:`send_notice`.
Entrada: :func:`verify_signature` e :func:`parse_inbound`, para o recibo de entrega
e a resposta do cliente — que vira evento do projeto, nunca thread no canal.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from portal_api.config import Settings

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0
_SIGNATURE_PREFIX = "sha256="


class WhatsappDisabled(RuntimeError):
    """O canal não está configurado. Não é falha — é ausência de credencial."""


class WhatsappError(RuntimeError):
    """O fornecedor não aceitou a mensagem.

    Existe separado do ``Disabled`` pela razão do ``EsignProviderError``: uma coisa
    é o canal não existir neste ambiente, outra é ele existir e ter recusado. A
    primeira não merece alerta e a segunda merece.
    """


@dataclass(frozen=True)
class Inbound:
    """O que chegou do fornecedor, já no vocabulário do portal."""

    #: Identificador do evento no fornecedor — é a chave de idempotência da entrada.
    external_id: str
    #: ``delivered``/``read``/``failed`` para recibo, ``message`` para resposta.
    kind: str
    #: O telefone de quem respondeu, quando há. Campo de segredo para efeito de log.
    phone: str = ""
    #: O texto da resposta, quando há.
    text: str = ""


def session_client() -> httpx.Client | None:
    """Onde o transporte do canal entra, e o único lugar.

    ``None`` significa "use o ``httpx`` direto", que é o caminho de produção. Existe
    como função e não como constante pela razão escrita no ``google_drive``: uma
    task do Celery não recebe cliente por argumento, e sem este ponto os testes só
    poderiam exercitar o adaptador por dentro — provando que ele monta o corpo, sem
    provar que alguém o envia.
    """
    return None


def is_configured(settings: Settings) -> bool:
    """Há credencial suficiente para falar com o fornecedor.

    Separado de :func:`is_enabled` de propósito: "configurado" e "ligado" são as
    duas perguntas que o estado da integração mostra lado a lado, e colapsá-las
    esconderia o caso que mais confunde — a flag ligada sobre credencial ausente.
    """
    return bool(
        settings.whatsapp_api_token
        and settings.whatsapp_phone_number_id
        and settings.whatsapp_api_base
    )


def is_enabled(settings: Settings) -> bool:
    return settings.whatsapp_enabled and is_configured(settings)


#: O fuso do produto, e ele é **constante** (ADR 0026). Fuso por organização ou por
#: pessoa foi decidido contra: não há coluna, não há rota, e a tela já formata toda
#: data nesta zona. Um segundo lugar respondendo "que horas são para esta pessoa"
#: divergiria do primeiro no dia em que alguém editasse um só — que é o argumento
#: do ``textfold.py``.
PRODUCT_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def within_quiet_hours(settings: Settings, moment: datetime) -> bool:
    """A hora em que este canal não fala (FDD 021; o teto que a ADR 0042 deixou aberto).

    Mora **aqui** e não em :mod:`portal_api.contact_budget` porque a ADR 0042 já
    escreveu de quem é a decisão: o orçamento conta contatos, e a hora não é um
    contato. Um remetente futuro com outra tolerância — a pesquisa da FDD 022, por
    exemplo — decide a sua sem mexer no teto que os dois compartilham.

    Função pura, na forma de ``build_payload``: o relógio entra por parâmetro, como
    o dia entra em ``results.py`` e em ``audit.evaluate``. ``moment`` é *aware* em
    UTC — quem chama é o worker, com o mesmo ``retention.now()`` que o orçamento usa.

    Duas propriedades que o teste fixa, porque as duas já foram escritas errado em
    algum produto: início igual ao fim **desliga** a janela, e a janela que
    atravessa a meia-noite (21 → 8) é o caso normal, não a exceção.
    """
    start = settings.contact_quiet_hours_start
    end = settings.contact_quiet_hours_end
    if start == end:
        return False

    hour = moment.astimezone(PRODUCT_TIMEZONE).hour
    if start < end:
        return start <= hour < end
    # Atravessa a meia-noite: é silêncio dos dois lados da virada.
    return hour >= start or hour < end


def ensure_configured(settings: Settings) -> None:
    if not is_configured(settings):
        raise WhatsappDisabled("WHATSAPP_API_TOKEN/PHONE_NUMBER_ID are not configured")


def _messages_url(settings: Settings) -> str:
    base = settings.whatsapp_api_base.rstrip("/")
    return f"{base}/{settings.whatsapp_phone_number_id}/messages"


def build_payload(settings: Settings, *, to: str, title: str, url: str) -> dict[str, Any]:
    """O corpo da mensagem, e ele é fechado.

    Template com **dois** parâmetros posicionais — o fato e o link — e nada mais. O
    template em si mora no fornecedor (é ele que exige aprovação prévia de texto
    para mensagem iniciada pelo negócio), então o que sai daqui são só as duas
    variáveis. É por isso que "o aviso não carrega trecho de documento" é
    verificável: não há terceiro parâmetro.

    Função separada do envio para o teste poder afirmar sobre o corpo sem precisar
    de transporte — a mesma divisão que ``ingestion/chunk.py`` faz entre montar e
    gravar.
    """
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        # Nunca um grupo. A razão de existir de um grupo é conversa de muitos para
        # muitos, que é exatamente o que não se quer fora do portal (FDD 021) — e o
        # canal de menor atrito vence sempre, então pôr os dois para fazer o mesmo
        # trabalho esvaziaria o portal. `individual` é a única forma que este
        # adaptador sabe montar.
        "to": to,
        "type": "template",
        "template": {
            "name": settings.whatsapp_template_name,
            "language": {"code": settings.whatsapp_template_language},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": title},
                        {"type": "text", "text": url},
                    ],
                }
            ],
        },
    }


def send_notice(
    settings: Settings,
    *,
    to: str,
    title: str,
    url: str,
    client: httpx.Client | None = None,
) -> str:
    """Envia o aviso e devolve o id da mensagem no fornecedor.

    Levanta :class:`WhatsappDisabled` sem credencial e :class:`WhatsappError` em
    qualquer outra falha — inclusive um 200 sem id, que é o caso que as rodadas de
    homologação do outro repositório acharam três vezes: linha gravada como se o
    fornecedor tivesse aceitado, sem ele ter aceitado.
    """
    ensure_configured(settings)
    payload = build_payload(settings, to=to, title=title, url=url)
    headers = {"Authorization": f"Bearer {settings.whatsapp_api_token}"}

    try:
        if client is not None:
            response = client.post(_messages_url(settings), json=payload, headers=headers)
        else:  # pragma: no cover - I/O com o fornecedor
            response = httpx.post(
                _messages_url(settings), json=payload, headers=headers, timeout=_TIMEOUT
            )
    except httpx.HTTPError as exc:
        raise WhatsappError(f"whatsapp transport failed: {exc}") from exc

    if response.status_code >= 400:
        # O corpo **não** entra na exceção: um 400 do fornecedor ecoa o payload, e o
        # payload carrega o telefone. É o mesmo defeito que a ADR 0023 achou no
        # FastAPI 0.141 ecoando o corpo da requisição em todo 422.
        raise WhatsappError(f"whatsapp refused with {response.status_code}")

    try:
        body = response.json()
    except ValueError as exc:
        raise WhatsappError("whatsapp answered with a non-JSON body") from exc

    messages = body.get("messages") or []
    message_id = messages[0].get("id") if messages else None
    if not message_id:
        # 200 sem id é aceitação que não aconteceu. Sem esta guarda o carimbo de
        # envio sairia sobre uma mensagem que não existe do outro lado, e a
        # retentativa — que trabalha sobre o nulo — nunca mais a tentaria.
        raise WhatsappError("whatsapp accepted without returning a message id")
    return str(message_id)


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """HMAC do corpo cru, em tempo constante — a forma do webhook do Biahflow."""
    if not secret or not header:
        return False
    provided = (
        header[len(_SIGNATURE_PREFIX) :]
        if header.startswith(_SIGNATURE_PREFIX)
        else header
    )
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def parse_inbound(payload: dict[str, Any]) -> Inbound | None:
    """Normaliza o evento de entrada. ``None`` quando não há nada a fazer com ele.

    Devolver ``None`` em vez de levantar é deliberado: o fornecedor manda espécies
    de evento que este produto não usa, e transformar cada uma em erro encheria o
    log de falhas que descrevem o funcionamento normal — o argumento que o
    ``alerts.md`` faz na seção "não são alerta".
    """
    try:
        change = payload["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return None

    statuses = change.get("statuses") or []
    if statuses:
        first = statuses[0]
        external_id = str(first.get("id") or "")
        status = str(first.get("status") or "")
        if not external_id or not status:
            return None
        return Inbound(external_id=external_id, kind=status)

    messages = change.get("messages") or []
    if messages:
        first = messages[0]
        external_id = str(first.get("id") or "")
        if not external_id:
            return None
        return Inbound(
            external_id=external_id,
            kind="message",
            phone=str(first.get("from") or ""),
            text=str((first.get("text") or {}).get("body") or ""),
        )

    return None
