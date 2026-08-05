"""Backup e restore dos objetos do storage (Fase 5, ADR 0019).

Só os objetos. O banco é trabalho de ``pg_dump``, e o motivo de a divisão não ser
arbitrária é que as duas metades têm modos de falha opostos: o dump do Postgres
erra por **privilégio** (a credencial errada devolve um backup vazio sem dizer),
e o do storage erra por **completude** (uma listagem parcial descreve um bucket
menor que o real). Cada metade é conferida pelo que a ameaça dela exige — o banco
por um censo de linhas, os objetos por um índice com o SHA-256 de cada um.

Mesma forma de :mod:`portal_api.retention`, e pela mesma razão: duas funções,
nenhuma rota HTTP. Um endpoint que devolvesse o bucket inteiro seria exatamente o
que a regra 1 do ``AGENTS.md`` proíbe — um caminho de requisição capaz de ler
dado de todo tenant de uma vez. Quem chama isto é o operador, pela linha de
comando, com a credencial de storage no ambiente.

O contêiner é um tar, e o nome de cada membro é a **chave do objeto**: a chave já
carrega o tenant inteiro (``org/<id>/project/<id>/document/<id>/<sha256><ext>``,
ADR 0014), então o tar não precisa de estrutura própria e um backup por
organização é só um prefixo. Nada é extraído para o sistema de arquivos — o
restore lê membro a membro e grava direto no storage —, mas o nome ainda é
validado antes do uso, porque um tar é entrada e não se confia numa entrada só
porque nós a produzimos da última vez.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

from portal_api.config import Settings, get_settings
from portal_api import storage

logger = logging.getLogger(__name__)

#: O índice vive dentro do próprio tar. Fora dele viraria um segundo arquivo para
#: alguém perder, e um backup cujo verificador se perde não é verificável.
INDEX_MEMBER = "__portal_backup_index__.json"

#: Sobe junto do índice para um tar de amanhã não ser lido como se fosse de hoje.
FORMAT_VERSION = 1


class BackupError(RuntimeError):
    """O backup ou o restore não pôde ser concluído com integridade."""


@dataclass
class ObjectBackupResult:
    objects: int = 0
    total_bytes: int = 0
    #: Chaves que o restore recusou, com o motivo. Vazio é o caso bom.
    rejected: dict[str, str] = field(default_factory=dict)


def _validate_member_name(name: str) -> None:
    """Recusa nome de membro que não é uma chave de objeto.

    Nada aqui extrai para disco, então travessia de caminho não é a ameaça
    imediata; a ameaça é gravar no bucket sob uma chave que o tenant não descreve
    — ``../`` ou uma barra inicial produziriam uma chave fora de ``org/<id>/`` e,
    com ela, um objeto que não responde a quem pertencia.
    """
    if not name or name.startswith("/"):
        raise BackupError(f"Chave inválida no backup: {name!r}")
    if any(part in ("..", ".", "") for part in name.split("/")):
        raise BackupError(f"Chave inválida no backup: {name!r}")


def dump_objects(
    settings: Settings, destination: Path, *, prefix: str = ""
) -> ObjectBackupResult:
    """Escreve todo objeto sob ``prefix`` num tar, com índice e SHA-256.

    ``prefix`` vazio é o bucket inteiro; ``org/<id>/`` é uma organização só.
    """
    result = ObjectBackupResult()
    entries: list[dict[str, object]] = []

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w") as tar:
        for key in storage.iter_keys(settings, prefix):
            _validate_member_name(key)
            stored = storage.fetch_object(settings, key)
            info = tarfile.TarInfo(name=key)
            info.size = len(stored.data)
            # mtime fixo: dois backups do mesmo bucket devem sair byte a byte
            # iguais, senão "o backup mudou" deixa de ser um sinal.
            info.mtime = 0
            tar.addfile(info, io.BytesIO(stored.data))
            entries.append(
                {
                    "key": key,
                    "size": len(stored.data),
                    "sha256": hashlib.sha256(stored.data).hexdigest(),
                    "content_type": stored.content_type,
                }
            )
            result.objects += 1
            result.total_bytes += len(stored.data)

        index = json.dumps(
            {
                "format_version": FORMAT_VERSION,
                "bucket": settings.storage_bucket,
                "prefix": prefix,
                "objects": entries,
            },
            indent=2,
            sort_keys=True,
        ).encode()
        info = tarfile.TarInfo(name=INDEX_MEMBER)
        info.size = len(index)
        info.mtime = 0
        tar.addfile(info, io.BytesIO(index))

    logger.info(
        "backup.objects.dumped",
        extra={
            "objects": result.objects,
            "total_bytes": result.total_bytes,
            "bucket": settings.storage_bucket,
            "prefix": prefix,
        },
    )
    return result


def restore_objects(settings: Settings, source: Path) -> ObjectBackupResult:
    """Devolve ao storage o que ``dump_objects`` guardou, conferindo cada hash.

    Um objeto cujo SHA-256 não bate **não é gravado**: um backup que restaura
    bytes corrompidos é pior que um que falha, porque a citação continuaria
    abrindo um link — só que para um arquivo que não é mais o que foi citado.
    """
    result = ObjectBackupResult()

    with tarfile.open(source, "r") as tar:
        # `extractfile` levanta KeyError quando o membro não existe, e devolve
        # None quando existe mas não é arquivo regular. Os dois casos são "isto
        # não é um backup do portal".
        try:
            index_member = tar.extractfile(INDEX_MEMBER)
        except KeyError:
            index_member = None
        if index_member is None:
            raise BackupError(f"{source} não tem índice: não é um backup do portal")
        index = json.loads(index_member.read())
        if index.get("format_version") != FORMAT_VERSION:
            raise BackupError(
                f"Backup em formato {index.get('format_version')!r}; "
                f"esperado {FORMAT_VERSION}"
            )

        for entry in index["objects"]:
            key = str(entry["key"])
            _validate_member_name(key)
            try:
                member = tar.extractfile(key)
            except KeyError:
                member = None
            if member is None:
                result.rejected[key] = "ausente no tar"
                continue
            data = member.read()
            digest = hashlib.sha256(data).hexdigest()
            if digest != entry["sha256"]:
                result.rejected[key] = "sha256 divergente"
                continue
            storage.put_object(
                settings, key, data, entry.get("content_type")  # type: ignore[arg-type]
            )
            result.objects += 1
            result.total_bytes += len(data)

    if result.rejected:
        logger.error(
            "backup.objects.rejected",
            extra={"rejected": len(result.rejected), "keys": sorted(result.rejected)},
        )
        raise BackupError(
            f"{len(result.rejected)} objeto(s) recusado(s) no restore: "
            + ", ".join(f"{k} ({v})" for k, v in sorted(result.rejected.items()))
        )

    logger.info(
        "backup.objects.restored",
        extra={
            "objects": result.objects,
            "total_bytes": result.total_bytes,
            "bucket": settings.storage_bucket,
        },
    )
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    from portal_api.telemetry import configure_logging

    parser = argparse.ArgumentParser(
        prog="python -m portal_api.backup",
        description="Backup e restore dos objetos do storage (ADR 0019).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    dump = sub.add_parser("dump", help="grava os objetos num tar")
    dump.add_argument("destination", type=Path)
    dump.add_argument(
        "--prefix",
        default="",
        help="limita a um prefixo, p.ex. org/<uuid>/ para uma organização só",
    )

    restore = sub.add_parser("restore", help="devolve os objetos de um tar")
    restore.add_argument("source", type=Path)

    args = parser.parse_args(argv)
    configure_logging()
    settings = get_settings()

    if args.command == "dump":
        result = dump_objects(settings, args.destination, prefix=args.prefix)
    else:
        result = restore_objects(settings, args.source)

    print(f"objects={result.objects} bytes={result.total_bytes}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entrada de linha de comando
    raise SystemExit(main())
