/**
 * O núcleo do espelhamento da camada global, testado no que ele tem de perigoso.
 *
 * Não precisa de build, de rede nem de docker — como `pins-harness.test.mjs` e
 * `audit-harness.test.mjs`. O que se exercita é o núcleo puro de
 * `scripts/sync-engineering-os.mjs`: `plan()`, que decide o que copiar e o que
 * remover, e `stable()`, que decide quando o `PROVENANCE.md` merece ser reescrito.
 *
 * O que estes testes existem para impedir é a **poda que apaga demais**.
 * `plan().remove` vira `unlinkSync` sem confirmação, dentro de um diretório
 * versionado. Um `remove` que inclua o `PROVENANCE.md` apagaria justamente o
 * registro do pino; um que inclua arquivo ainda presente na origem produziria um
 * diff de exclusão que ninguém pediu. As asserções são sobre as duas listas
 * inteiras, não sobre um item.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { plan, provenanceText, stable } from "../scripts/sync-engineering-os.mjs";

/** Recorte real da listagem de `git ls-files` da Engineering OS v0.1.0. */
const SOURCE = [
  "README.md",
  "core/definition-of-done.md",
  "core/guardrails/git.md",
  "agents/builder.md",
  ".gitignore",
];

test("plan copia os rastreados da origem e ignora o .gitignore dela", () => {
  const { keep } = plan(SOURCE, []);
  assert.deepEqual(keep, [
    "README.md",
    "agents/builder.md",
    "core/definition-of-done.md",
    "core/guardrails/git.md",
  ]);
  assert.ok(!keep.includes(".gitignore"), "um .gitignore aninhado mudaria o ignore deste repo");
});

test("plan remove do espelho o que saiu da origem", () => {
  const mirrored = ["README.md", "workflows/removido-da-origem.md", "core/definition-of-done.md"];
  const { remove } = plan(SOURCE, mirrored);
  assert.deepEqual(remove, ["workflows/removido-da-origem.md"]);
});

test("plan nunca remove o PROVENANCE, que não vem da origem", () => {
  const { remove } = plan(SOURCE, ["PROVENANCE.md", "README.md"]);
  assert.deepEqual(remove, [], "o registro do pino é gerado aqui, não espelhado");
});

test("plan sobre espelho vazio não remove nada", () => {
  assert.deepEqual(plan(SOURCE, []).remove, []);
});

test("stable ignora a data, para que ressincronizar a mesma tag não produza diff", () => {
  const base = { origin: "https://exemplo/eos.git", tag: "v0.1.0", commit: "abc1234", count: 4 };
  const ontem = provenanceText({ ...base, today: "2026-08-25" });
  const hoje = provenanceText({ ...base, today: "2026-08-26" });

  assert.notEqual(ontem, hoje, "as datas de fato diferem no texto");
  assert.equal(stable(ontem), stable(hoje), "mas nenhum fato novo mudou");
});

test("stable enxerga a troca de tag, que é fato novo", () => {
  const base = { origin: "https://exemplo/eos.git", commit: "abc1234", count: 4, today: "2026-08-26" };
  const anterior = provenanceText({ ...base, tag: "v0.1.0" });
  const nova = provenanceText({ ...base, tag: "v0.2.0" });

  assert.notEqual(stable(anterior), stable(nova));
});
