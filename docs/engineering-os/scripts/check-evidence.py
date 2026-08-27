#!/usr/bin/env python3
"""Confere um pacote de evidência contra o template da camada global.

    scripts/check-evidence.py docs/features/F-012/evidence.md ...

O pacote é o handoff para revisão ([templates/evidence.md](../templates/evidence.md)). O
Reviewer decide `REVIEW_PASS`, `REVIEW_FINDINGS` ou `REVIEW_EVIDENCE_INCOMPLETE` a partir
dele, e o terceiro estado existe justamente porque um pacote incompleto é comum. Descobrir
a incompletude na revisão custa uma rodada inteira; descobrir aqui custa nada.

## O que é verificado

- o bloco `round` traz `round`, `reviewed_commit_or_state` e `authorization` com valor —
  sem a autorização, ninguém sabe qual decisão humana abriu a rodada;
- as oito seções numeradas existem;
- **`2. BASELINE` não está vazia.** É a seção com consequência escrita no template: *"a
  preexisting failure recorded here is not attributable to this work; one that is not
  recorded here will be"*. Vazia, toda falha preexistente passa a ser atribuída a este
  trabalho;
- `3. CHANGE` cita o `BUILD REPORT` de cada tarefa, ou uma referência a ele;
- `7. Review` declara um resultado do enum.

`5. Integration` pode estar vazia: o template a condiciona a *"when integration
occurred"*.

## O que não é verificado, e por quê

Se as referências apontam para artefatos que existem e que o Reviewer alcança, se o
baseline declarado é o baseline real, e se os perfis listados em `4. Validation` foram os
que rodaram. O template exige que toda referência seja *"accessible to the Reviewer,
unambiguous, stable for the review round"* — accessibility é resolvível por link checker
no repositório do projeto, o resto exige a execução. Verde aqui é forma, não veracidade.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eos_artifacts import PLACEHOLDER, Document, Finding, fenced_blocks, fields_in  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

ROUND_FIELDS = ("round", "reviewed_commit_or_state", "authorization")

#: (número, nome curto, exige conteúdo)
SECTIONS = (
    (1, "Contract and plan", True),
    (2, "BASELINE", True),
    (3, "CHANGE", True),
    (4, "Validation", True),
    (5, "Integration", False),
    (6, "FINAL", True),
    (7, "Review", True),
    (8, "Deviations", True),
)

RESULTS = ("REVIEW_PASS", "REVIEW_FINDINGS", "REVIEW_EVIDENCE_INCOMPLETE")


def numbered_sections(document: Document) -> dict[int, int]:
    """Seções `## <n>. ...` mapeadas do número para a linha, tolerante ao título."""
    found: dict[int, int] = {}
    for number, line in enumerate(document.lines, 1):
        match = re.match(r"^#{1,6}\s+(\d+)\.\s", line)
        if match:
            found.setdefault(int(match.group(1)), number)
    return found


def check(path: Path) -> list[Finding]:
    document = Document.read(path)
    findings: list[Finding] = []

    declared: dict[str, tuple[str, int]] = {}
    for _, body in fenced_blocks(document):
        declared.update(fields_in(body))

    for name in ROUND_FIELDS:
        value = declared.get(name, ("", 0))[0]
        if name not in declared:
            findings.append(Finding(path, 0, f"bloco `round` sem `{name}`"))
        elif not value or PLACEHOLDER.fullmatch(value):
            findings.append(Finding(path, 0, f"`{name}` sem valor: {value!r}"))

    present = numbered_sections(document)
    for index, name, needs_content in SECTIONS:
        opened = present.get(index)
        if opened is None:
            findings.append(Finding(path, 0, f"seção `{index}. {name}` ausente"))
            continue
        if needs_content and document.section_is_empty(opened):
            message = f"seção `{index}. {name}` vazia"
            if index == 2:
                message += (
                    "; falha preexistente não registrada aqui passa a ser atribuída a "
                    "este trabalho"
                )
            findings.append(Finding(path, opened, message))

    change = present.get(3)
    if change and not document.section_is_empty(change):
        body = "\n".join(document.section_body(change))
        if "BUILD REPORT" not in body:
            findings.append(
                Finding(
                    path,
                    change,
                    "`3. CHANGE` não traz nem referencia o `BUILD REPORT` de cada tarefa",
                )
            )

    review = present.get(7)
    if review and not document.section_is_empty(review):
        body = "\n".join(document.section_body(review))
        if not any(result in body for result in RESULTS):
            findings.append(
                Finding(
                    path,
                    review,
                    f"`7. Review` sem resultado do enum: {', '.join(RESULTS)}",
                )
            )

    return findings


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    findings = [f for name in argv for f in check(Path(name).resolve())]
    for finding in findings:
        print(finding.render(ROOT), file=sys.stderr)
    if findings:
        print(f"\n{len(findings)} problema(s) em {len(argv)} pacote(s).", file=sys.stderr)
        return 1
    print(f"Pacote de evidência com a forma exigida: {len(argv)} arquivo(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
