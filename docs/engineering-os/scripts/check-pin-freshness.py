#!/usr/bin/env python3
"""Compara o pino da camada global com a última tag publicada na origem.

    scripts/check-pin-freshness.py docs/engineering-os/PROVENANCE.md
    scripts/check-pin-freshness.py --origin <url> --tag v0.1.0

Um espelho vendorizado envelhece em silêncio: quem muda a camada global precisa lembrar
de trazê-la, e o repositório consumidor não avisa sozinho. Este é o portão que avisa —
na divisão do resto da camada, ele **detecta** e o conserto é de uma pessoa.

## Quando reprova, e por que só aí

Reprova quando o pino está atrás no **nível quebrável**. É a definição do
[VERSIONING.md](../VERSIONING.md): `MAJOR` significa que um projeto que era conforme pode
ter deixado de ser — **e enquanto o major é `0`, é o `MINOR` que carrega isso**, porque a
camada ainda está se assentando.

Foi exatamente o que aconteceu quando quatro campos obrigatórios entraram no
`BUILD REPORT`: todo relatório escrito antes passou a ser `BUILDER_CONTRACT_INCOMPLETE`, e
nenhum consumidor foi avisado.

Abaixo do nível quebrável, apenas relata. Reprovar neles quebraria a CI de todo consumidor a cada
release da origem, o que treina as pessoas a ignorar o portão e transformaria avançar o
pino em urgência em vez de mudança revisada.

## Rede

A ressincronização já exige rede; esta checagem também. Origem inalcançável **não** é
violação de política: relata e passa. Com `--require-network`, reprova — para quem quiser
o portão estrito num ambiente onde a rede é garantida.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SEMVER = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

#: A linha da tabela do PROVENANCE, em qualquer um dos rótulos em uso.
ROWS = {
    "origin": ("origem", "origin"),
    "tag": ("tag de origem", "source tag", "tag"),
}


def parse_provenance(path: Path) -> tuple[str, str]:
    origin = tag = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip().strip("`") for cell in line.split("|") if cell.strip()]
        if len(cells) != 2:
            continue
        label = cells[0].lower()
        if not origin and label in ROWS["origin"]:
            origin = cells[1]
        elif not tag and label in ROWS["tag"]:
            tag = cells[1]
    if not origin or not tag:
        raise SystemExit(
            f"{path}: não achei as linhas de origem e tag. A tabela precisa de "
            "`| Origem | <url> |` e `| Tag de origem | vX.Y.Z |`."
        )
    return origin, tag


def classify(current: tuple[int, int, int], latest: tuple[int, int, int]) -> tuple[str, bool]:
    """O nível do atraso, e se ele é quebrável.

    Núcleo puro: sem rede, sem arquivo. Enquanto o major é `0`, é o `MINOR` que carrega
    mudança quebrável — a camada ainda está se assentando, e o VERSIONING.md diz isso.
    """
    if latest[0] > current[0]:
        return "MAJOR", True
    if latest[1] > current[1]:
        return "MINOR", current[0] == 0
    return "PATCH", False


def published_tags(origin: str) -> list[tuple[int, int, int]] | None:
    """As tags SemVer da origem, ou None quando ela está inalcançável."""
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", origin],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    found = []
    for line in result.stdout.splitlines():
        _, _, reference = line.partition("refs/tags/")
        match = SEMVER.match(reference.strip())
        if match:
            found.append(tuple(int(part) for part in match.groups()))
    return sorted(found)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provenance", nargs="?", help="caminho do PROVENANCE.md do espelho")
    parser.add_argument("--origin", help="URL da origem, no lugar do PROVENANCE")
    parser.add_argument("--tag", help="tag pinada, no lugar do PROVENANCE")
    parser.add_argument(
        "--require-network",
        action="store_true",
        help="reprova quando a origem está inalcançável, em vez de relatar",
    )
    arguments = parser.parse_args(argv)

    if arguments.origin and arguments.tag:
        origin, tag = arguments.origin, arguments.tag
    elif arguments.provenance:
        origin, tag = parse_provenance(Path(arguments.provenance))
    else:
        parser.error("informe um PROVENANCE.md, ou --origin junto com --tag")

    pinned = SEMVER.match(tag)
    if not pinned:
        print(f"pino fora de SemVer: {tag!r}", file=sys.stderr)
        return 1
    current = tuple(int(part) for part in pinned.groups())

    tags = published_tags(origin)
    if tags is None:
        message = f"origem inalcançável: {origin}. Pino atual: {tag}"
        print(message, file=sys.stderr if arguments.require_network else sys.stdout)
        return 1 if arguments.require_network else 0
    if not tags:
        print(f"a origem não publicou nenhuma tag SemVer: {origin}", file=sys.stderr)
        return 1

    latest = tags[-1]
    rendered = "v{}.{}.{}".format(*latest)

    if current >= latest:
        print(f"Pino em dia: {tag} é a última publicada em {origin}.")
        return 0

    behind = [t for t in tags if t > current]
    level, breaking = classify(current, latest)

    if breaking:
        note = (
            "MAJOR significa que um projeto conforme antes pode ter deixado de ser"
            if level == "MAJOR"
            else "com major 0, MINOR carrega mudança quebrável"
        )
        print(
            f"Pino atrasado por {level}: {tag} → {rendered}, {len(behind)} release(s) atrás.\n"
            f"{note} (VERSIONING.md). Avance o pino como mudança revisada.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Pino atrasado por {level}: {tag} → {rendered}, {len(behind)} release(s) atrás. "
        "Aditivo; avançar quando fizer sentido."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
