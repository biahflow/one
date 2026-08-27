# Working in this repository

Engineering OS is the vendor-neutral source of truth for AI-assisted software delivery.
[`README.md`](../README.md) states the model, [`MILESTONES.md`](../MILESTONES.md) states where
it is going, and [`adapters/README.md`](../adapters/README.md) states how a harness reaches it.

**This file does not restate them.** It used to, across 372 lines, and it drifted: it declared
"M1–M6 complete" while `MILESTONES.md` declared M2–M6 "planned but not yet detailed", and it
declared adapters to be worker bridges rather than harness bootstraps while `README.md` and
`adapters/README.md` declared the opposite. Two documents describing the same thing produce a
third state that is neither. Where a rule already has a home, link to it.

## The one thing that changes how you work here

A consumer project does not read this repository over the network. It **vendors a complete
pinned mirror** of it and advances that pin as a reviewed change. What is tracked here is
copied into every consumer, and what breaks here breaks inside a repository that cannot fix
it — its own documentation gate fails on a link that only this repository can repair.

That is why the gates below are not ceremony, and why the mirror once went from 144 KB to
25 MB when five compiled binaries were tracked here by accident.

## What is real and what is intended

Real: the Core documents, the agent contracts, the workflow conventions, the bootstrap
adapters, and [`scripts/install-adapters.sh`](../scripts/install-adapters.sh), which renders a
harness bootstrap with an absolute path at install time.

Intended, and **not implemented**: the `biah` orchestrator. Every one of its subcommands exits
non-zero. Its capability manifests and routing model are real and read by other code; planning,
execution, worktree management, evidence collection and gates are not. `MILESTONES.md` calls
this M7.

The operating model today is the convention in [`workflows/`](../workflows/), followed by a
harness and verified by a human. A harness may commit, push and open a pull request; **a human
merges.** That boundary is in
[`workflows/git-publishing-and-human-merge.md`](../workflows/git-publishing-and-human-merge.md)
and no change here weakens it.

## Gates

Run before opening a pull request; [`.github/workflows/ci.yml`](workflows/ci.yml) runs the same
set, and [`.github/workflows/release.yml`](workflows/release.yml) runs it again before a tag
publishes.

```bash
scripts/check-links.py               # every relative markdown link resolves
scripts/check-tracked-artifacts.py   # no generated artifact, no file over 1 MB
scripts/check-operator-paths.py      # no absolute machine path in a versioned file
scripts/check-yaml.py                # every tracked YAML parses            (needs pyyaml)
scripts/install-adapters.sh --dry-run
python3 -m unittest discover -s tests -q   # os checkers de conformidade

cd biah && gofmt -l . && go vet ./... && go build ./... && go test ./...
```

Os checkers de conformidade não rodam sozinhos aqui: eles recebem caminhos, e os
artefatos que eles conferem vivem nos projetos consumidores, que vendorizam `scripts/` e
os apontam para os próprios contratos, relatórios e pacotes de evidência.

```bash
scripts/check-task-contract.py  <contrato>...     # os requisitos de portabilidade
scripts/check-build-report.py   <relatório>...    # os doze campos do BUILD REPORT
scripts/check-evidence.py       <pacote>...       # as oito seções do handoff de revisão
scripts/check-pin-freshness.py  <PROVENANCE.md>   # o pino contra a última tag publicada
```

Aponte-os para os **arquivos alterados**, não para o histórico: um artefato escrito contra
uma versão anterior desta camada reprova por ser antigo, não por estar errado.

## Rules for editing

- **An adapter carries `{{EOS_ROOT}}`, never a path.** The placeholder is resolved at install
  time so the repository stays portable. A versioned absolute path works for exactly one
  executor and dies for everyone the day a directory moves — which has happened.
- **Generated output is not tracked.** Build artifacts, coverage and reports are ignored; the
  `biah` Makefile's `clean` target names them.
- **A rule belongs in exactly one document.** Add constraints in the layer that owns them:
  Core → project instructions → task contract. A lower layer may tighten a rule and may never
  weaken a guardrail or a human gate.
- **Vendor-neutrality decides placement.** If a statement would not hold identically for
  Claude, Codex, Copilot or a future worker, it belongs in an adapter, not in the Core.
- **Do not report work that did not happen.** A command that prints a checkmark for a step it
  skipped, or a `BUILD_COMPLETE` with no files changed and no validation executed, is worse
  than a missing command: the false green survives inside output that looks fine.

## Versioning

Consumers pin by tag, so a tag is immutable and is cut from `main`.
[`VERSIONING.md`](../VERSIONING.md) defines `MAJOR`/`MINOR`/`PATCH` against one question — does
a project that was compliant before this change stay compliant after it — and answers `MAJOR`
whenever that is arguable.
