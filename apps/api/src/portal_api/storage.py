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
from collections.abc import Iterator
from dataclasses import dataclass
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


def _client(settings: Settings, *, endpoint_url: str | None = None) -> Any:
    """O cliente S3. ``endpoint_url`` sobrepõe o endereço, e só a assinatura usa.

    A chave do cache inclui o endereço justamente porque existem dois clientes
    possíveis para o mesmo storage: o interno, que grava e lê, e o público, que
    só assina URL (ver ``storage_public_endpoint_url``).
    """
    if not settings.storage_access_key or not settings.storage_secret_key:
        raise StorageDisabled("Storage sem credencial configurada")
    endpoint = endpoint_url or settings.storage_endpoint_url
    cache_key = (
        endpoint,
        settings.storage_access_key,
        settings.storage_region,
    )
    client = _clients.get(cache_key)
    if client is None:
        import boto3  # lazy: mantém o import fora do caminho de subida da API

        client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
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
            logger.info(
                "storage.bucket_not_created",
                extra={"bucket": settings.storage_bucket, "detail": str(exc)},
            )


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


@dataclass(frozen=True)
class StoredObject:
    """Os bytes **e** o content type, que ``get_object`` descarta.

    Existe para o backup (ADR 0019): restaurar só os bytes devolveria todo PDF
    como ``application/octet-stream``, e a URL assinada faria o navegador baixar
    o arquivo em vez de abrir a página 3 — que é justamente o que a ADR 0017
    trocou por um link.
    """

    key: str
    data: bytes
    content_type: str | None


def fetch_object(settings: Settings, key: str) -> StoredObject:
    client = _client(settings)
    try:
        response = client.get_object(Bucket=settings.storage_bucket, Key=key)
        return StoredObject(
            key=key,
            data=response["Body"].read(),
            content_type=response.get("ContentType"),
        )
    except Exception as exc:
        raise StorageError(f"Falha ao ler {key}") from exc


def iter_keys(settings: Settings, prefix: str = "") -> Iterator[str]:
    """Percorre as chaves sob um prefixo, página a página.

    ``prefix`` vazio é o bucket inteiro, que é o caso do backup completo; um
    prefixo de organização (``org/<id>/``) é o backup de um tenant só. A regra da
    barra final de ``delete_prefix`` vale aqui pelo mesmo motivo — o S3 compara
    texto, não caminho —, mas aqui ela não é imposta: listar demais é inofensivo,
    apagar demais não.
    """
    client = _client(settings)
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.storage_bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                yield item["Key"]
    except Exception as exc:
        raise StorageError(f"Falha ao listar o prefixo {prefix!r}") from exc


def presigned_get_url(settings: Settings, key: str, ttl_seconds: int) -> str:
    """URL de leitura que expira sozinha (Fase 5, ADR 0017).

    É o que `docs/security.md` chama de "URLs de arquivo temporárias", e a razão
    de a API devolver um endereço em vez dos bytes: o arquivo trafega do storage
    para o navegador sem atravessar o processo que valida o token, o que tira do
    caminho de requisição o custo de um PDF de 25 MiB.

    A URL **não carrega sessão** — quem a tiver, abre. Por isso o que a contém é
    o TTL curto e não a autenticação: ela é gerada depois da checagem de
    associação, e o que impede o vazamento de virar acesso permanente é ela
    vencer. Não guardamos a URL em lugar nenhum; cada clique gera outra.

    Assinada contra o endereço **público** do storage, não o interno. A SigV4
    cobre o host, então reescrever a URL depois de assinada a invalidaria — é a
    mesma razão pela qual `auth.ts` passa os dois endpoints do Keycloak
    explicitamente em vez de corrigir a URL no meio do caminho.
    """
    client = _client(
        settings,
        endpoint_url=settings.storage_public_endpoint_url or settings.storage_endpoint_url,
    )
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.storage_bucket, "Key": key},
            ExpiresIn=ttl_seconds,
        )
    except Exception as exc:
        raise StorageError(f"Falha ao assinar {key}") from exc


def delete_object(settings: Settings, key: str) -> None:
    """Remove o objeto. Ausência não é erro: apagar duas vezes é o mesmo que uma."""
    client = _client(settings)
    try:
        client.delete_object(Bucket=settings.storage_bucket, Key=key)
    except Exception as exc:
        raise StorageError(f"Falha ao remover {key}") from exc


def delete_prefix(settings: Settings, prefix: str) -> int:
    """Remove tudo sob um prefixo, e devolve quantos objetos saíram.

    É o expurgo por organização (Fase 5, ADR 0017), e o que o torna possível é a
    forma da chave: ``org/<id>/...`` desde a ADR 0014, escolhida ali justamente
    para "permitir uma política de retenção por organização na Fase 5".

    Recolhe junto o objeto órfão — aquele que ``delete_document`` admite deixar
    para trás quando o storage está fora do ar no momento em que a linha some.
    Como o prefixo é o tenant inteiro, não há como um órfão de outra organização
    entrar no lote.

    O ``prefix`` **precisa** terminar em ``/``. Sem a barra, ``org/<id>`` casaria
    também com ``org/<id-de-outra-coisa>``: o S3 compara texto, não caminho.
    """
    if not prefix.endswith("/"):
        raise ValueError("O prefixo do expurgo tem de terminar em '/'")

    client = _client(settings)
    removed = 0
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.storage_bucket, Prefix=prefix):
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if not keys:
                continue
            # `delete_objects` aceita 1000 por chamada, que é o mesmo teto da
            # paginação — uma página nunca passa do limite do lote.
            client.delete_objects(
                Bucket=settings.storage_bucket, Delete={"Objects": keys}
            )
            removed += len(keys)
    except Exception as exc:
        raise StorageError(f"Falha ao remover o prefixo {prefix}") from exc
    return removed
