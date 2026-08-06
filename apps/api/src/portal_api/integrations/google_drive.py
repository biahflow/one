"""Google Drive somente leitura: OAuth, travessia da pasta e download (ADR 0016).

Irmão de ``biahflow.py`` e com a mesma anatomia: mapas de tradução declarativos no
topo, verificação da credencial, fetch servidor-a-servidor com ``client``
injetável, e nada de banco. O que este módulo **não** faz é escrever: quem
reconcilia o índice é o worker, sob ``portal_system``.

Sem SDK. O Drive v3 é REST e o refresh é um POST de formulário; o
``google-api-python-client`` traria uma árvore de dependências para dois
endpoints, e o ``httpx`` já está aqui desde o Biahflow. O ``client`` injetável é o
que permite testar o conector inteiro com ``httpx.MockTransport``, sem credencial
do Google e sem rede — do mesmo jeito que ``fetch_snapshot`` já fazia.

**A pasta autorizada é a fronteira, e ela é verificada duas vezes.** Primeiro
porque não existe caminho que aceite um id de arquivo vindo de fora: a única fonte
de ids é a travessia, que começa na pasta conectada. Depois porque, antes de
qualquer download, o arquivo tem de declarar como pai uma das pastas que a
travessia alcançou. A segunda checagem parece redundante e não é — ela é a que um
teste consegue atacar, e o threat model cobra exatamente esse teste.

Duas armadilhas do Drive que este módulo trata explicitamente:

* **atalho não é seguido.** ``application/vnd.google-apps.shortcut`` mora dentro
  da pasta autorizada com um ``parents`` perfeitamente legal e aponta para
  qualquer arquivo do Drive. Segui-lo seria abrir a fronteira por dentro;
* **arquivo nativo do Google não tem ``md5Checksum``.** Documento, planilha e
  apresentação só têm ``modifiedTime``. Por isso o portão barato do sync é o
  ``modifiedTime``, e o md5 é bônus quando existe.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from portal_api.config import Settings
from portal_api.ingestion import SUPPORTED_MIME_TYPES

logger = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

#: Formato nativo do Google → o formato que o portal já sabe ler. É por isto que o
#: conector não acrescenta nenhum extrator: depois do export, ``ingestion/extract``
#: recebe um DOCX, um PDF ou um CSV como qualquer outro.
#:
#: Planilha vira CSV, e **o export do Google traz só a primeira aba** — limitação
#: dele, não do portal. Fica escrito na FDD porque quem envia uma planilha de
#: cinco abas precisa ler isso na tela, não descobrir pela ausência da citação.
EXPORT_FORMATS: dict[str, str] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    "application/vnd.google-apps.presentation": "application/pdf",
    "application/vnd.google-apps.spreadsheet": "text/csv",
}

#: Campos pedidos na listagem. Explícitos porque o Drive devolve o mínimo por
#: padrão, e cada um destes sustenta uma decisão: ``parents`` a fronteira,
#: ``modifiedTime`` o portão barato, ``size`` a recusa antes do download.
_LIST_FIELDS = (
    "nextPageToken, files(id, name, mimeType, modifiedTime, md5Checksum, size, parents)"
)
_PAGE_SIZE = 100
_TIMEOUT = 30


class DriveDisabled(RuntimeError):
    """Sem client id/secret configurados. Falha fechada, como ``StorageDisabled``."""


class DriveAuthError(RuntimeError):
    """O consentimento não vale mais: revogado, expirado ou de escopo errado."""


class DriveError(RuntimeError):
    """O Google respondeu erro."""


@dataclass(frozen=True)
class DriveTokens:
    access_token: str
    refresh_token: str | None
    scope: str


@dataclass(frozen=True)
class DriveFolder:
    id: str
    name: str


@dataclass(frozen=True)
class DriveFile:
    """Um arquivo elegível da pasta autorizada, já classificado.

    ``target_mime`` é o mime dos **bytes que o portal vai guardar** — o do próprio
    arquivo quando ele é binário, o do export quando é nativo do Google. ``None``
    significa que não há como lê-lo, e ``unsupported_reason`` é o que a tela mostra.
    """

    id: str
    name: str
    mime_type: str
    modified_time: datetime | None
    md5_checksum: str | None
    size: int | None
    export_mime: str | None
    target_mime: str | None
    unsupported_reason: str | None


@dataclass
class DriveListing:
    """O resultado de uma travessia — e ela é completa ou não é nada.

    ``complete`` existe porque o runbook manda "preservar último índice válido":
    uma listagem que falhou no meio não pode virar base para remover documento,
    senão uma indisponibilidade do Google apagaria o índice do cliente.
    """

    files: list[DriveFile] = field(default_factory=list)
    folders_visited: int = 0
    subfolders_skipped: int = 0
    rejected: int = 0
    truncated: bool = False
    complete: bool = True


# --- OAuth ---------------------------------------------------------------------


def session_client() -> httpx.Client | None:
    """Onde o transporte do Drive entra, e o único lugar.

    ``None`` significa "use o ``httpx`` direto", que é o caminho de produção. Existe
    como função e não como constante porque é o ponto que os testes trocam por um
    cliente sobre ``MockTransport`` — nem uma task do Celery nem uma rota do
    FastAPI podem receber um cliente por argumento como ``fetch_snapshot`` recebe.

    Um hook só, e não um por chamador, para não haver como o worker e a rota de
    administração falarem com Drives diferentes num teste.
    """
    return None


def ensure_configured(settings: Settings) -> None:
    if not settings.google_drive_client_id or not settings.google_drive_client_secret:
        raise DriveDisabled("GOOGLE_DRIVE_CLIENT_ID/SECRET are not configured")


def generate_code_verifier() -> str:
    """PKCE: um `code` interceptado sozinho não vira token."""
    return secrets.token_urlsafe(64)[:128]


def code_challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def authorize_url(settings: Settings, *, state: str, code_verifier: str) -> str:
    """A URL de consentimento.

    ``access_type=offline`` **e** ``prompt=consent`` juntos, e o segundo não é
    redundância: sem ele, uma reconexão de quem já consentiu volta sem
    ``refresh_token`` e a conexão nasce inutilizável — com um erro que só aparece
    no primeiro sync, longe da causa.
    """
    ensure_configured(settings)
    params = httpx.QueryParams(
        {
            "client_id": settings.google_drive_client_id,
            "redirect_uri": settings.google_drive_redirect_uri,
            "response_type": "code",
            "scope": settings.google_drive_scope,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "false",
            "state": state,
            "code_challenge": code_challenge_for(code_verifier),
            "code_challenge_method": "S256",
        }
    )
    return f"{settings.google_oauth_authorize_url}?{params}"


def _post_token(
    settings: Settings, data: dict[str, str], *, client: httpx.Client | None = None
) -> dict[str, Any]:
    request = ("POST", settings.google_oauth_token_url)
    try:
        if client is not None:
            response = client.post(request[1], data=data)
        else:
            response = httpx.post(request[1], data=data, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise DriveError(f"token endpoint unreachable: {exc}") from exc

    if response.status_code == 400:
        # `invalid_grant` é o Google dizendo que o consentimento não vale mais —
        # revogado na conta, expirado, ou o app ainda em "Testing" (onde o refresh
        # token dura sete dias). Distinto de erro genérico porque a resposta
        # operacional é outra: reconectar, não repetir.
        payload = _json(response)
        if payload.get("error") == "invalid_grant":
            raise DriveAuthError("consent is no longer valid")
        raise DriveError(f"token endpoint refused: {payload.get('error', 'bad request')}")
    if response.status_code >= 400:
        raise DriveError(f"token endpoint answered {response.status_code}")
    return _json(response)


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        return dict(response.json())
    except Exception:  # resposta não-JSON de um proxy no caminho
        return {}


def exchange_code(
    settings: Settings, code: str, code_verifier: str, *, client: httpx.Client | None = None
) -> DriveTokens:
    """Troca o código pelo par de tokens. O ``redirect_uri`` tem de ser idêntico
    ao da URL de consentimento — o Google compara byte a byte."""
    ensure_configured(settings)
    payload = _post_token(
        settings,
        {
            "client_id": settings.google_drive_client_id,
            "client_secret": settings.google_drive_client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": settings.google_drive_redirect_uri,
        },
        client=client,
    )
    access_token = payload.get("access_token")
    if not access_token:
        raise DriveError("token response carried no access_token")
    return DriveTokens(
        access_token=str(access_token),
        refresh_token=payload.get("refresh_token"),
        scope=str(payload.get("scope", "")),
    )


def refresh_access_token(
    settings: Settings, refresh_token: str, *, client: httpx.Client | None = None
) -> str:
    ensure_configured(settings)
    payload = _post_token(
        settings,
        {
            "client_id": settings.google_drive_client_id,
            "client_secret": settings.google_drive_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        client=client,
    )
    access_token = payload.get("access_token")
    if not access_token:
        raise DriveAuthError("refresh produced no access token")
    return str(access_token)


def scope_is_exactly_readonly(granted: str, settings: Settings) -> bool:
    """O Google pode conceder um conjunto diferente do pedido.

    Aceitar "mais do que pedi" transformaria o escopo somente-leitura numa
    intenção em vez de um controle — e é um controle que o threat model nomeia.
    """
    return set(granted.split()) == {settings.google_drive_scope}


# --- Drive ---------------------------------------------------------------------


def _get(
    settings: Settings,
    access_token: str,
    path: str,
    params: dict[str, Any] | None = None,
    *,
    client: httpx.Client | None = None,
    stream_bytes: bool = False,
) -> httpx.Response:
    url = f"{settings.google_drive_api_base_url.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        if client is not None:
            response = client.get(url, params=params, headers=headers)
        else:
            response = httpx.get(url, params=params, headers=headers, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise DriveError(f"drive unreachable: {exc}") from exc

    if response.status_code in (401, 403):
        raise DriveAuthError(f"drive refused the credential ({response.status_code})")
    if response.status_code >= 400:
        raise DriveError(f"drive answered {response.status_code} for {path}")
    return response


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def account_email(
    settings: Settings, access_token: str, *, client: httpx.Client | None = None
) -> str | None:
    """De quem é o acesso, para a tela poder dizer.

    ``about.get`` cabe no escopo somente-leitura, então não custa permissão nenhuma
    — e sem isso a tela mostraria uma pasta conectada sem dizer por qual conta.
    """
    response = _get(
        settings, access_token, "/about", {"fields": "user(emailAddress)"}, client=client
    )
    user = _json(response).get("user") or {}
    email = user.get("emailAddress")
    return str(email) if email else None


def get_folder(
    settings: Settings, access_token: str, folder_id: str, *, client: httpx.Client | None = None
) -> DriveFolder:
    """Confere que o id é mesmo de uma pasta, antes de fixá-la como a autorizada."""
    response = _get(
        settings, access_token, f"/files/{folder_id}", {"fields": "id, name, mimeType"},
        client=client,
    )
    payload = _json(response)
    if payload.get("mimeType") != FOLDER_MIME:
        raise DriveError("the chosen id is not a folder")
    return DriveFolder(id=str(payload["id"]), name=str(payload.get("name", "")))


def list_folders(
    settings: Settings, access_token: str, *, client: httpx.Client | None = None
) -> list[DriveFolder]:
    """As pastas da conta, para a pessoa escolher qual autorizar.

    Substitui o Google Picker de propósito: o Picker é um script de terceiro na
    página, e o portal não carrega script externo (CSP). Uma lista resolve.
    """
    folders: list[DriveFolder] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "q": f"mimeType = '{FOLDER_MIME}' and trashed = false",
            "fields": "nextPageToken, files(id, name)",
            "pageSize": _PAGE_SIZE,
            "spaces": "drive",
            "corpora": "user",
        }
        if page_token:
            params["pageToken"] = page_token
        payload = _json(_get(settings, access_token, "/files", params, client=client))
        folders.extend(
            DriveFolder(id=str(item["id"]), name=str(item.get("name", "")))
            for item in payload.get("files", [])
        )
        page_token = payload.get("nextPageToken")
        if not page_token:
            return folders


def _classify(item: dict[str, Any]) -> DriveFile:
    mime = str(item.get("mimeType", ""))
    export_mime = EXPORT_FORMATS.get(mime)
    if export_mime is not None:
        target: str | None = export_mime
        reason: str | None = None
    elif mime in SUPPORTED_MIME_TYPES:
        target, reason = mime, None
    elif mime.startswith("application/vnd.google-apps."):
        target, reason = None, "Formato nativo do Google sem exportação equivalente"
    else:
        target, reason = None, f"Formato não suportado pelo portal ({mime})"

    size = item.get("size")
    return DriveFile(
        id=str(item["id"]),
        name=str(item.get("name", "")),
        mime_type=mime,
        modified_time=_parse_time(item.get("modifiedTime")),
        md5_checksum=item.get("md5Checksum"),
        size=int(size) if size is not None else None,
        export_mime=export_mime,
        target_mime=target,
        unsupported_reason=reason,
    )


def walk_folder(
    settings: Settings,
    access_token: str,
    folder_id: str,
    *,
    client: httpx.Client | None = None,
) -> DriveListing:
    """Enumera a pasta autorizada em largura, dentro dos tetos configurados.

    O conjunto de visitados não é zelo: o Drive permite que uma pasta tenha mais de
    um pai, então a árvore é um grafo e uma travessia ingênua entra em ciclo.

    Os tetos (``drive_max_depth``, ``drive_max_files``) são o que impede uma pasta
    compartilhada enorme de virar um sync sem fim. Estourar o teto **não** é erro:
    marca ``truncated``, e o que já foi enumerado continua válido — o que não pode
    é a listagem truncada ser tratada como completa, porque aí a reconciliação
    apagaria o que não coube.
    """
    listing = DriveListing()
    authorized: set[str] = {folder_id}
    queue: deque[tuple[str, int]] = deque([(folder_id, 0)])
    seen_files: set[str] = set()

    while queue:
        current, depth = queue.popleft()
        listing.folders_visited += 1
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {
                "q": f"'{current}' in parents and trashed = false",
                "fields": _LIST_FIELDS,
                "pageSize": _PAGE_SIZE,
                "spaces": "drive",
                "corpora": "user",
                # Sem unidades compartilhadas: o consentimento é de uma conta, e
                # trazer drives de time ampliaria o alcance sem ninguém pedir.
                "supportsAllDrives": "false",
                "includeItemsFromAllDrives": "false",
            }
            if page_token:
                params["pageToken"] = page_token

            payload = _json(_get(settings, access_token, "/files", params, client=client))

            for item in payload.get("files", []):
                mime = str(item.get("mimeType", ""))

                if mime == SHORTCUT_MIME:
                    # Aponta para fora com um `parents` legal. Ignorado, nunca seguido.
                    #
                    # O log é da ADR 0028, e o precedente é vinte linhas abaixo:
                    # a outra metade da fronteira já registrava o que barrava, e
                    # esta some num contador. `alerts.md` mandava ler os dois
                    # casos como um evento só — e um deles não emitia nada.
                    logger.warning(
                        "drive.shortcut_skipped",
                        extra={"file_id": item.get("id"), "folder_id": folder_id},
                    )
                    listing.rejected += 1
                    continue

                if mime == FOLDER_MIME:
                    child = str(item["id"])
                    if depth + 1 > settings.drive_max_depth:
                        listing.subfolders_skipped += 1
                    elif child not in authorized:
                        authorized.add(child)
                        queue.append((child, depth + 1))
                    continue

                # Segunda barreira da fronteira: o arquivo tem de declarar como pai
                # uma pasta que a travessia alcançou. Redundante por construção, e
                # é justamente a que um teste consegue atacar.
                parents = {str(parent) for parent in item.get("parents", [])}
                if not parents & authorized:
                    logger.warning(
                        "drive.file_outside_authorized_folder",
                        extra={"file_id": item.get("id"), "folder_id": folder_id},
                    )
                    listing.rejected += 1
                    continue

                if item["id"] in seen_files:
                    continue
                seen_files.add(str(item["id"]))

                if len(listing.files) >= settings.drive_max_files:
                    listing.truncated = True
                    return listing

                listing.files.append(_classify(item))

            page_token = payload.get("nextPageToken")
            if not page_token:
                break

    return listing


def download(
    settings: Settings,
    access_token: str,
    file: DriveFile,
    *,
    client: httpx.Client | None = None,
) -> bytes:
    """Os bytes do arquivo — baixados quando é binário, exportados quando é nativo."""
    if file.export_mime is not None:
        response = _get(
            settings,
            access_token,
            f"/files/{file.id}/export",
            {"mimeType": file.export_mime},
            client=client,
        )
    else:
        response = _get(
            settings, access_token, f"/files/{file.id}", {"alt": "media"}, client=client
        )
    return response.content
