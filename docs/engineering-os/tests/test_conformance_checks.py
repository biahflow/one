"""Os checkers de conformidade, testados onde eles erram.

Sem rede, sem git, sem dependência fora da stdlib — `python3 -m unittest discover tests`.

O que estes testes defendem é o **falso vermelho**. Um portão que reprova artefato bom é
desligado pela primeira pessoa que o encontra, e depois disso ele não protege mais nada.
Cada caso abaixo veio de um artefato real de um projeto consumidor que uma versão anterior
de um checker reprovou por engano:

- valor multi-linha (`Files changed:` seguido de bullets indentados) lido como "em branco";
- campo `snake_case` (`round`, `feature_id`) não casado por um regex que exigia maiúscula;
- enum com explicação (`COMMIT: forbidden — a entrega é o diff…`) tido como fora do enum;
- seção que abre com subseção (`## 8.` seguido de `### Desvio`) lida como vazia.

O falso verde é o outro lado, e tem seus próprios casos: `BUILD_COMPLETE` sem validação
executada, e `BUILDER_VALIDATION_BLOCKED` que não diz o que ficou por validar.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name: str):
    """Carrega um script com hífen no nome, que não é importável por `import`."""
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_report = load("check-build-report")
task_contract = load("check-task-contract")
evidence = load("check-evidence")
pin = load("check-pin-freshness")

import eos_artifacts  # noqa: E402


def written(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return Path(handle.name)


COMPLETE_REPORT = """BUILD REPORT

Status: BUILD_COMPLETE
Files changed:
  - apps/web/src/route.ts — a porta de entrada ganha representação
  - apps/web/src/App.tsx — aplica a decisão
Validation executed: make check → exit 0
Validation skipped: none
Unavailable capabilities: none
Review repair trigger: none
Review feedback iteration: 0
CI repair trigger: none
CI repair iteration: 0
Assumptions: none
Remaining risks: none
Human decisions required: none
"""


class LeituraDeArtefato(unittest.TestCase):
    def test_valor_multilinha_nao_e_branco(self):
        fields = eos_artifacts.fields_in(COMPLETE_REPORT.splitlines())
        self.assertIn("route.ts", fields["Files changed"][0])
        self.assertIn("App.tsx", fields["Files changed"][0])

    def test_campo_snake_case_casa(self):
        fields = eos_artifacts.fields_in(["round: 1", "reviewed_commit_or_state: abc"])
        self.assertEqual(fields["round"][0], "1")
        self.assertEqual(fields["reviewed_commit_or_state"][0], "abc")

    def test_enum_casa_pelo_primeiro_token(self):
        self.assertEqual(eos_artifacts.first_token("forbidden — a entrega é o diff"), "forbidden")
        self.assertEqual(eos_artifacts.first_token(""), "")

    def test_secao_com_subsecao_nao_e_vazia(self):
        document = eos_artifacts.Document.read(
            written("# T\n\n## 8. Desvios\n\n### Desvio de plano\n\nPLAN_DEVIATION 01\n")
        )
        opened = document.has_heading("8. Desvios")
        self.assertFalse(document.section_is_empty(opened))


class BuildReport(unittest.TestCase):
    def test_relatorio_completo_passa(self):
        self.assertEqual(build_report.check(written(COMPLETE_REPORT)), [])

    def test_build_complete_sem_validacao_reprova(self):
        text = COMPLETE_REPORT.replace("Validation executed: make check → exit 0", "Validation executed: none")
        findings = build_report.check(written(text))
        self.assertTrue(any("sem evidência determinística" in f.message for f in findings))

    def test_campo_ausente_e_contract_incomplete(self):
        text = COMPLETE_REPORT.replace("CI repair iteration: 0\n", "")
        findings = build_report.check(written(text))
        self.assertTrue(any("BUILDER_CONTRACT_INCOMPLETE" in f.message for f in findings))

    def test_status_fora_do_enum_reprova(self):
        text = COMPLETE_REPORT.replace("Status: BUILD_COMPLETE", "Status: DONE")
        findings = build_report.check(written(text))
        self.assertTrue(any("fora do enum" in f.message for f in findings))

    def test_iteracao_nao_inteira_reprova(self):
        text = COMPLETE_REPORT.replace("CI repair iteration: 0", "CI repair iteration: primeira")
        findings = build_report.check(written(text))
        self.assertTrue(any("não é inteiro" in f.message for f in findings))

    def test_validation_blocked_precisa_dizer_o_que_ficou(self):
        text = (
            COMPLETE_REPORT.replace("Status: BUILD_COMPLETE", "Status: BUILDER_VALIDATION_BLOCKED")
        )
        findings = build_report.check(written(text))
        messages = " ".join(f.message for f in findings)
        self.assertIn("Validation skipped: none", messages)
        self.assertIn("VALIDATE", messages)

    def test_sem_bloco_nenhum_reprova(self):
        findings = build_report.check(written("# Sem relatório\n\nnada aqui\n"))
        self.assertTrue(any("nenhum bloco" in f.message for f in findings))


PORTABLE_CONTRACT = """# T1 — Nome

## Identity

```text
feature_id: F-007
task_id: T1
parent_plan: ../plan.md
depends_on: none
```

## Goal

Um resultado checável.

## Scope

`apps/web/src/route.ts`

## Out of Scope

Não tocar em `App.tsx`.

## Acceptance Criteria

`npm test` passa.

## Validation

```text
baseline: make check → exit 0
required: lint: npm run lint
```

## Required Capabilities

```text
READ:     apps/web
WRITE:    apps/web/src/route.ts
VALIDATE: lint
COMMIT:   forbidden — a entrega é o diff na árvore
```

## Context to Read First

`docs/fdd/007.md`

## Human Gates

Merge.

## Reporting

Termine com o `BUILD REPORT` completo.
"""


class TaskContract(unittest.TestCase):
    def test_contrato_portavel_passa(self):
        self.assertEqual(task_contract.check(written(PORTABLE_CONTRACT)), [])

    def test_commit_com_explicacao_passa(self):
        self.assertEqual(
            [f for f in task_contract.check(written(PORTABLE_CONTRACT)) if "COMMIT" in f.message], []
        )

    def test_sem_out_of_scope_e_requisito_4(self):
        text = PORTABLE_CONTRACT.replace("## Out of Scope\n\nNão tocar em `App.tsx`.\n", "")
        findings = task_contract.check(written(text))
        self.assertTrue(any("requisito 4" in f.message for f in findings))

    def test_sem_baseline_e_requisito_3(self):
        text = PORTABLE_CONTRACT.replace("baseline: make check → exit 0\n", "")
        findings = task_contract.check(written(text))
        self.assertTrue(any("requisito 3" in f.message for f in findings))

    def test_marcador_de_template_reprova(self):
        text = PORTABLE_CONTRACT.replace("feature_id: F-007", "feature_id: <value>")
        findings = task_contract.check(written(text))
        self.assertTrue(any("feature_id" in f.message for f in findings))

    def test_commit_fora_do_enum_reprova(self):
        text = PORTABLE_CONTRACT.replace("COMMIT:   forbidden", "COMMIT:   talvez")
        findings = task_contract.check(written(text))
        self.assertTrue(any("fora do enum" in f.message for f in findings))

    def test_reporting_sem_build_report_reprova(self):
        text = PORTABLE_CONTRACT.replace("Termine com o `BUILD REPORT` completo.", "Reporte algo.")
        findings = task_contract.check(written(text))
        self.assertTrue(any("requisito 6" in f.message for f in findings))


COMPLETE_EVIDENCE = """# F-007 — Evidence

## Round

```text
round: 1
reviewed_commit_or_state: branch X, de abc a HEAD
authorization: seleção humana em 25/08/2026
```

## 1. Contrato e plano

`plan.md`

## 2. BASELINE

`make check` → exit 0 antes da mudança.

## 3. CHANGE

O `BUILD REPORT` de cada tarefa está em `tasks/T1-build-report.md`.

## 4. Validação

lint, testes.

## 5. Integração

## 6. FINAL

Diff em `HEAD`.

## 7. Revisão

`REVIEW_PASS` na rodada 1.

## 8. Desvios, riscos e decisões humanas pendentes

### Desvio de plano

`PLAN_DEVIATION 01`.
"""


class Evidencia(unittest.TestCase):
    def test_pacote_completo_passa(self):
        self.assertEqual(evidence.check(written(COMPLETE_EVIDENCE)), [])

    def test_integracao_pode_estar_vazia(self):
        findings = evidence.check(written(COMPLETE_EVIDENCE))
        self.assertEqual([f for f in findings if "Integration" in f.message], [])

    def test_baseline_vazia_reprova_dizendo_a_consequencia(self):
        text = COMPLETE_EVIDENCE.replace("`make check` → exit 0 antes da mudança.\n", "")
        findings = evidence.check(written(text))
        self.assertTrue(any("passa a ser atribuída" in f.message for f in findings))

    def test_sem_autorizacao_reprova(self):
        text = COMPLETE_EVIDENCE.replace("authorization: seleção humana em 25/08/2026\n", "")
        findings = evidence.check(written(text))
        self.assertTrue(any("authorization" in f.message for f in findings))

    def test_review_sem_resultado_do_enum_reprova(self):
        text = COMPLETE_EVIDENCE.replace("`REVIEW_PASS` na rodada 1.", "Correu bem.")
        findings = evidence.check(written(text))
        self.assertTrue(any("sem resultado do enum" in f.message for f in findings))

    def test_change_sem_build_report_reprova(self):
        text = COMPLETE_EVIDENCE.replace(
            "O `BUILD REPORT` de cada tarefa está em `tasks/T1-build-report.md`.", "Mudou coisas."
        )
        findings = evidence.check(written(text))
        self.assertTrue(any("CHANGE" in f.message for f in findings))


class FrescorDoPino(unittest.TestCase):
    def test_major_atras_e_quebravel(self):
        self.assertEqual(pin.classify((1, 4, 0), (2, 0, 0)), ("MAJOR", True))

    def test_minor_atras_com_major_zero_e_quebravel(self):
        self.assertEqual(pin.classify((0, 1, 0), (0, 2, 0)), ("MINOR", True))

    def test_minor_atras_com_major_estavel_nao_e(self):
        self.assertEqual(pin.classify((1, 1, 0), (1, 2, 0)), ("MINOR", False))

    def test_patch_nunca_e_quebravel(self):
        self.assertEqual(pin.classify((0, 1, 0), (0, 1, 9)), ("PATCH", False))

    def test_provenance_e_lido_nos_dois_rotulos(self):
        table = (
            "| Campo | Valor |\n|---|---|\n"
            "| Origem | `https://exemplo/eos.git` |\n"
            "| Tag de origem | `v0.1.0` |\n"
        )
        self.assertEqual(
            pin.parse_provenance(written(table)), ("https://exemplo/eos.git", "v0.1.0")
        )


if __name__ == "__main__":
    unittest.main()
