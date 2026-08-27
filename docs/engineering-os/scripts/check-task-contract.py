#!/usr/bin/env python3
"""Confere um Task Contract contra os requisitos de portabilidade.

    scripts/check-task-contract.py docs/features/F-012/tasks/T01.md ...

[workflows/execution.md](../workflows/execution.md) define oito requisitos e o estado
`TASK_CONTRACT_NOT_PORTABLE` para o contrato que falha algum deles. Nenhum código
produzia esse estado: era uma promessa. O custo de descobrir tarde está escrito no
próprio template — *"is returned as TASK_CONTRACT_NOT_PORTABLE by a correct executor, at
the cost of a full contract round trip"*.

## O que é verificado, por requisito

1. **Self-contained** — as seções obrigatórias existem e não estão vazias.
2. **Commands are real and named** — o bloco de validação declara `required:` com valor.
3. **Baseline is declared** — `baseline:` existe e não é `none` nem marcador.
4. **Scope is bounded** — `Out of Scope` existe e não está vazia.
5. **Gates are named** — `Human Gates` existe e não está vazia.
6. **Report format is fixed** — `Reporting` existe e cita o `BUILD REPORT`.
7. **Capabilities are verifiable** — `READ`, `WRITE`, `VALIDATE` e `COMMIT` declarados,
   com `COMMIT` em `allowed | forbidden`.

## O que não é verificado, e por quê

**Requisito 8, ownership de execução, não é verificável daqui.** Branch, worktree e
Builder ativo são estado de execução, não texto do contrato; quem confere isso é o
workflow de worktree, no momento em que a tarefa é atribuída.

Do requisito 2, este checker vê que um comando foi **escrito**, não que ele existe nem
que roda. O template manda rodar cada comando de critério antes de publicar o contrato, e
isso continua sendo trabalho de quem publica. Do requisito 1, vê que a seção tem
conteúdo, não que o conteúdo é suficiente para quem nunca viu a conversa que gerou o
plano — que é o ponto inteiro de ser self-contained, e não é decidível por regex.

Verde aqui significa: **o contrato tem a forma**. Não significa que ele é portável.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eos_artifacts import (  # noqa: E402
    PLACEHOLDER,
    Document,
    Finding,
    fenced_blocks,
    fields_in,
    first_token,
)

ROOT = Path(__file__).resolve().parents[1]

#: Seções obrigatórias do requisito 1, e o requisito que cada uma serve.
SECTIONS = (
    ("Identity", 1),
    ("Goal", 1),
    ("Scope", 1),
    ("Out of Scope", 4),
    ("Acceptance Criteria", 1),
    ("Validation", 2),
    ("Required Capabilities", 7),
    ("Context to Read First", 1),
    ("Human Gates", 5),
    ("Reporting", 6),
)

IDENTITY = ("feature_id", "task_id", "parent_plan", "depends_on")
CAPABILITIES = ("READ", "WRITE", "VALIDATE", "COMMIT")
COMMIT_VALUES = ("allowed", "forbidden")


def unset(value: str) -> bool:
    return not value or value.lower() == "none" or bool(PLACEHOLDER.fullmatch(value))


def check(path: Path) -> list[Finding]:
    document = Document.read(path)
    findings: list[Finding] = []

    def fail(line: int, requirement: int, message: str) -> None:
        findings.append(
            Finding(path, line, f"TASK_CONTRACT_NOT_PORTABLE (requisito {requirement}): {message}")
        )

    opened_at: dict[str, int] = {}
    for name, requirement in SECTIONS:
        opened = document.has_heading(name)
        opened_at[name] = opened
        if not opened:
            fail(0, requirement, f"seção `{name}` ausente")
        elif document.section_is_empty(opened):
            fail(opened, requirement, f"seção `{name}` vazia")

    blocks = [body for _, body in fenced_blocks(document)]
    declared = {}
    for body in blocks:
        declared.update(fields_in(body))

    for name in IDENTITY:
        value = declared.get(name, ("", 0))[0]
        if name not in declared:
            fail(opened_at.get("Identity", 0), 1, f"identidade sem `{name}`")
        elif unset(value) and name != "depends_on":
            fail(opened_at.get("Identity", 0), 1, f"`{name}` sem valor: {value!r}")

    baseline = declared.get("baseline", ("", 0))[0]
    if "baseline" not in declared:
        fail(opened_at.get("Validation", 0), 3, "bloco de validação sem `baseline:`")
    elif unset(baseline):
        fail(
            opened_at.get("Validation", 0),
            3,
            "`baseline:` sem valor; o executor precisa saber quais falhas já existem",
        )

    required = declared.get("required", ("", 0))[0]
    if "required" not in declared:
        fail(opened_at.get("Validation", 0), 2, "bloco de validação sem `required:`")
    elif unset(required):
        fail(opened_at.get("Validation", 0), 2, "`required:` sem comando nomeado")

    for name in CAPABILITIES:
        value = declared.get(name, ("", 0))[0]
        if name not in declared:
            fail(opened_at.get("Required Capabilities", 0), 7, f"capacidade `{name}` não declarada")
        elif unset(value):
            fail(opened_at.get("Required Capabilities", 0), 7, f"capacidade `{name}` sem valor")
        elif name == "COMMIT" and first_token(value).lower() not in COMMIT_VALUES:
            fail(
                opened_at.get("Required Capabilities", 0),
                7,
                f"`COMMIT` fora do enum: {value!r}. Um de: {', '.join(COMMIT_VALUES)}",
            )

    reporting = opened_at.get("Reporting", 0)
    if reporting and "BUILD REPORT" not in "\n".join(document.section_body(reporting)):
        fail(reporting, 6, "`Reporting` não exige o `BUILD REPORT` completo")

    return findings


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    findings = [f for name in argv for f in check(Path(name).resolve())]
    for finding in findings:
        print(finding.render(ROOT), file=sys.stderr)
    if findings:
        print(f"\n{len(findings)} problema(s) em {len(argv)} contrato(s).", file=sys.stderr)
        return 1
    print(f"Task Contract com a forma exigida: {len(argv)} contrato(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
