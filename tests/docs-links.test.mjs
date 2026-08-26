/**
 * Todo link relativo de Markdown do repositório resolve.
 *
 * Não precisa de build, de rede nem de docker — como `pins-harness.test.mjs`.
 * O corpus é derivado de `git ls-files`, nunca digitado (ADR 0033): uma lista de
 * arquivos escrita à mão aqui deixaria de descrever o repositório no dia seguinte.
 *
 * ## Por que existe
 *
 * `AGENTS.md`, `docs/project-context.md` e `docs/features/README.md` citavam "o
 * Definition of Done global", "o contrato do Planner" e "os estados da
 * Engineering OS" em texto corrido, sem link — as únicas referências do
 * repositório que nenhum portão podia conferir, porque não apontavam para lugar
 * nenhum. Uma delas chegou a apontar: para `~/workspace/engineeringOS/`, um
 * caminho da máquina de uma pessoa, e ninguém percebeu quando ele morreu.
 *
 * Com a camada global vendorizada em `docs/engineering-os/`, essas citações
 * viram links relativos — e este teste é o que faz delas referências de verdade.
 * `workflows/project-adoption.md` da própria camada global põe a condição:
 * as referências devem apontar para o espelho "so the project's own
 * documentation gates validate them; a textual mention of a global document that
 * no link can reach is dead text, not a reference".
 *
 * O espelho entra no corpus de propósito. Um espelho incompleto quebraria os
 * links internos entre os documentos globais, que é exatamente o sinal desejado.
 */

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const LINK = /\[([^\]]*)\]\(([^)\s]+)\)/g;
const EXTERNAL = ["http://", "https://", "mailto:", "#"];

/** Os Markdown rastreados, derivados por glob e nunca digitados. */
function markdownFiles() {
  return execFileSync("git", ["-C", ROOT, "ls-files", "-z", "*.md"], { encoding: "utf8" })
    .split("\0")
    .filter(Boolean);
}

function brokenLinks(file) {
  const text = readFileSync(join(ROOT, file), "utf8");
  const base = dirname(join(ROOT, file));
  const failures = [];

  text.split("\n").forEach((line, index) => {
    for (const [, , target] of line.matchAll(LINK)) {
      if (EXTERNAL.some((prefix) => target.startsWith(prefix))) continue;
      // `{{EOS_ROOT}}` é placeholder de adapter, resolvido só na instalação.
      if (target.includes("{{")) continue;
      const path = target.split("#")[0];
      if (!path) continue;
      if (!existsSync(resolve(base, path))) failures.push(`${file}:${index + 1} -> ${target}`);
    }
  });

  return failures;
}

test("o corpus de Markdown não está vazio", () => {
  // Fail-closed, como as superfícies do `test_supply_chain_pins.py`: um glob que
  // devolve zero arquivos passaria por engano, dizendo que nada está quebrado.
  assert.ok(markdownFiles().length > 50, "git ls-files '*.md' devolveu quase nada");
});

test("todo link relativo de Markdown resolve", () => {
  const failures = markdownFiles().flatMap(brokenLinks);
  assert.deepEqual(failures, [], `links quebrados:\n  ${failures.join("\n  ")}`);
});
