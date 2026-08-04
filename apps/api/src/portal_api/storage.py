"""Storage dos documentos: MinIO local, S3 em produção (ADR 0014).

Um adapter só, porque é a mesma API: o que muda entre o compose e a nuvem é o
endpoint e a credencial. Fica fora do pacote ``ingestion`` de propósito — a API
grava o objeto no upload e o worker o lê de volta para indexar, e os dois
precisam desta camada sem precisar um do outro.

A chave do objeto carrega o tenant inteiro
(``org/<id>/project/<id>/document/<id>/<sha256><ext>``). Não é organização
cosmética: chave de outro tenant não é adivinhável, o prefixo permite uma
política de retenção por organização na Fase 5, e um objeto solto no bucket diz
sozinho a quem pertencia.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import TYPE_CHECKING, Any

from portal_api.config import Settings

if TYPE_CHECKING:  # pragma: no cover - apenas para tipagem
    import uuid

logger = logging.getLogger(__name__)

_clients: dict[tuple[str, str, str], Any] = {}


class StorageDisabled(RuntimeError):
    """Não há credencial de storage configurada.

    Falha fechada e explícita: sem isto o upload gravaria a linha em ``document``
    e perderia o arquivo, deixando um metadado que nunca vira evidência.
    """


class StorageError(RuntimeError):
    """O storage respondeu com erro (indisponível, sem permissão, sem objeto)."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_key(
    organization_id: "uuid.UUID",
    project_id: "uuid.UUID",
    document_id: "uuid.UUID",
    filename: str,
    content_digest: str,
) -> str:
    return (
        f"org/{organization_id}/project/{project_id}/document/{document_id}/"
        f"{content_digest}{_extension(filename)}"
    )


def _extension(filename: str) -> str:
    """A extensão do nome original, sanitizada — nunca o nome inteiro.

    O nome do arquivo é conteúdo do cliente e não tem por que virar caminho no
    bucket; a extensão sobrevive apenas porque ajuda quem abre o objeto na mão.
    """
    _, _, suffix = filename.rpartition(".")
    if not suffix or suffix == filename or len(suffix) > 8:
        return ""
    cleaned = re.sub(r"[^a-z0-9]", "", suffix.lower())
    return f".{cleaned}" if cleaned else ""


def _client(settings: Settings) -> Any:
    if not settings.storage_access_key or not settings.storage_secret_key:
        raise StorageDisabled("Storage sem credencial configurada")
    cache_key = (
        settings.storage_endpoint_url,
        settings.storage_access_key,
        settings.storage_region,
    )
    client = _clients.get(cache_key)
    if client is None:
        import boto3  # lazy: mantém o import fora do caminho de subida da API

        client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url or None,
            aws_access_key_id=settings.storage_access_key,
            aws_secret_access_key=settings.storage_secret_key,
            region_name=settings.storage_region,
        )
        _clients[cache_key] = client
    return client


def reset_clients() -> None:
    """Descarta os clientes cacheados — o equivalente de ``reset_engines``."""
    _clients.clear()


def ensure_bucket(settings: Settings) -> None:
    """Cria o bucket se ele ainda não existe.

    Feito no código, e não por um serviço ``mc`` a mais no compose, porque é
    idempotente e vale igual para quem sobe contra um S3 vazio.
    """
    client = _client(settings)
    try:
        client.head_bucket(Bucket=settings.storage_bucket)
    except Exception:
        try:
            client.create_bucket(Bucket=settings.storage_bucket)
        except Exception as exc:  # corrida entre dois processos, ou sem permissão
            logger.info("Bucket %s não criado: %s", settings.storage_bucket, exc)


def put_object(settings: Settings, key: str, data: bytes, content_type: str | None) -> None:
    ensure_bucket(settings)
    client = _client(settings)
    try:
        client.put_object(
            Bucket=settings.storage_bucket,
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )
    except Exception as exc:
        raise StorageError(f"Falha ao gravar {key}") from exc


def get_object(settings: Settings, key: str) -> bytes:
    client = _client(settings)
    try:
        response = client.get_object(Bucket=settings.storage_bucket, Key=key)
        return response["Body"].read()
    except Exception as exc:
        raise StorageError(f"Falha ao ler {key}") from exc


def delete_object(settings: Settings, key: str) -> None:
    """Remove o objeto. Ausência não é erro: apagar duas vezes é o mesmo que uma."""
    client = _client(settings)
    try:
        client.delete_object(Bucket=settings.storage_bucket, Key=key)
    except Exception as exc:
        raise StorageError(f"Falha ao remover {key}") from exc
