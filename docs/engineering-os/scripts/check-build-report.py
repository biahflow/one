#!/usr/bin/env python3
"""Confere um `BUILD REPORT` contra o contrato do Builder.

    scripts/check-build-report.py docs/features/F-012/evidence.md ...

O `BUILD REPORT` completo é `PRIMARY_EXECUTION_EVIDENCE` de uma tarefa
([agents/builder.md](../agents/builder.md)). Todo o modelo — revisão, reparo limitado,
paridade entre harnesses — lê esse relatório e assume que ele diz a verdade sobre o que
foi executado. Era o artefato menos protegido da camada: o formato estava definido e
nada verificava que um relatório entregue o tinha.

## O que é verificado

- os doze campos existem; campo faltando é `BUILDER_CONTRACT_INCOMPLETE`, e é o próprio
  contrato que diz isso;
- nenhum valor está em branco — o contrato manda escrever `none`, e branco é ambíguo
  entre "nada a declarar" e "esqueci";
- `Status` está no enum, e as duas iterações são inteiras;
- nenhum marcador de template (`<value>`) sobreviveu;
- **`BUILD_COMPLETE` com `Validation executed: none` reprova.** O Builder "may not claim
  completion without deterministic validation evidence"; um relatório assim é a forma
  escrita do falso verde;
- **`BUILDER_VALIDATION_BLOCKED` exige o que o template da tarefa manda**: o check que
  não rodou listado em `Validation skipped`, e `VALIDATE` nomeado em
  `Unavailable capabilities`. Sem isso o bloqueio não diz o que ficou por validar.

## O que não é verificado, e por quê

Se os arquivos listados em `Files changed` foram mesmo os alterados, se os comandos em
`Validation executed` rodaram e com que resultado, e se as suposições declaradas são as
que o executor de fato fez. Nada disso está no texto; conferir exige o diff e os logs da
execução. Este checker confere **forma declarada**, e um verde dele não é evidência de
que o build aconteceu.

`Files changed: none` num `BUILD_COMPLETE` **não** reprova, apesar de suspeito: uma
rodada de reparo que não achou o que reparar é legítima, e um portão com falso positivo
é um portão que as pessoas aprendem a ignorar.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eos_artifacts import PLACEHOLDER, Document, Finding, fields_in, first_token  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

ANCHOR = "BUILD REPORT"

REQUIRED = (
    "Status",
    "Files changed",
    "Validation executed",
    "Validation skipped",
    "Unavailable capabilities",
    "Review repair trigger",
    "Review feedback iteration",
    "CI repair trigger",
    "CI repair iteration",
    "Assumptions",
    "Remaining risks",
    "Human decisions required",
)

STATUSES = (
    "BUILD_COMPLETE",
    "BUILD_BLOCKED",
    "BUILDER_VALIDATION_BLOCKED",
    "BUILDER_CONTRACT_INCOMPLETE",
)

INTEGERS = ("Review feedback iteration", "CI repair iteration")

def reports(document: Document) -> list[tuple[int, list[str]]]:
    """Cada bloco que começa numa linha `BUILD REPORT`, com a linha de abertura.

    O bloco vai até a cerca fechar ou até o próximo título — sem teto de linhas. Um teto
    fixo corta relatório longo no meio e reporta como ausentes os campos que vieram
    depois do corte; um relatório real, com os arquivos alterados descritos um a um,
    passa folgado de quarenta linhas.
    """
    found: list[tuple[int, list[str]]] = []
    for number, line in enumerate(document.lines, 1):
        if line.strip() != ANCHOR:
            continue
        body: list[str] = []
        for following in document.lines[number:]:
            stripped = following.strip()
            if stripped.startswith("```") or stripped.startswith("#"):
                break
            body.append(following)
        found.append((number, body))
    return found


def check_report(path: Path, opened: int, body: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    present = fields_in(body)

    def at(name: str) -> int:
        return opened + present[name][1] + 1 if name in present else opened

    missing = [name for name in REQUIRED if name not in present]
    if missing:
        findings.append(
            Finding(
                path,
                opened,
                f"BUILDER_CONTRACT_INCOMPLETE: campos ausentes: {', '.join(missing)}",
            )
        )

    for name in REQUIRED:
        if name not in present:
            continue
        value, _ = present[name]
        if not value:
            findings.append(
                Finding(path, at(name), f"`{name}` em branco; o contrato manda escrever `none`")
            )
        elif PLACEHOLDER.fullmatch(value):
            findings.append(
                Finding(path, at(name), f"`{name}` ainda tem o marcador do template: {value}")
            )

    status = first_token(present.get("Status", ("", 0))[0])
    if status and status not in STATUSES:
        findings.append(
            Finding(path, at("Status"), f"Status fora do enum: {status!r}. Um de: {', '.join(STATUSES)}")
        )

    for name in INTEGERS:
        value = present.get(name, ("", 0))[0]
        if value and not value.lstrip("-").isdigit():
            findings.append(Finding(path, at(name), f"`{name}` não é inteiro: {value!r}"))

    executed = present.get("Validation executed", ("", 0))[0].lower()
    if status == "BUILD_COMPLETE" and executed == "none":
        findings.append(
            Finding(
                path,
                at("Validation executed"),
                "BUILD_COMPLETE com `Validation executed: none`. O Builder não pode "
                "declarar conclusão sem evidência determinística de validação",
            )
        )

    if status == "BUILDER_VALIDATION_BLOCKED":
        skipped = present.get("Validation skipped", ("", 0))[0].lower()
        if skipped == "none":
            findings.append(
                Finding(
                    path,
                    at("Validation skipped"),
                    "BUILDER_VALIDATION_BLOCKED com `Validation skipped: none`; o check "
                    "que não rodou precisa estar listado, com a razão",
                )
            )
        capabilities = present.get("Unavailable capabilities", ("", 0))[0]
        if "VALIDATE" not in capabilities.upper():
            findings.append(
                Finding(
                    path,
                    at("Unavailable capabilities"),
                    "BUILDER_VALIDATION_BLOCKED sem `VALIDATE` em "
                    "`Unavailable capabilities`",
                )
            )

    return findings


def check(path: Path) -> list[Finding]:
    document = Document.read(path)
    found = reports(document)
    if not found:
        return [Finding(path, 0, f"nenhum bloco `{ANCHOR}` encontrado")]
    return [f for opened, body in found for f in check_report(path, opened, body)]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    findings = [f for name in argv for f in check(Path(name).resolve())]
    for finding in findings:
        print(finding.render(ROOT), file=sys.stderr)
    if findings:
        print(f"\n{len(findings)} problema(s) em {len(argv)} arquivo(s).", file=sys.stderr)
        return 1
    print(f"BUILD REPORT conforme: {len(argv)} arquivo(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
