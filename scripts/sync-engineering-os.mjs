#!/usr/bin/env node
/**
 * Espelha a camada global da Engineering OS dentro deste repositório.
 *
 *     npm run eos:sync                  # ou: node scripts/sync-engineering-os.mjs
 *     node scripts/sync-engineering-os.mjs --tag v0.2.0
 *
 * Mora em `scripts/` pela razão do `pins.mjs` e do `audit.mjs`: é **operação**.
 * Não sobe rota, não é importado pela aplicação, e roda quando alguém o chama.
 *
 * ## Por que existe
 *
 * `docs/project-context.md` declarava que a camada global "está disponível em
 * `~/workspace/engineeringOS/`" — um caminho absoluto da máquina de uma pessoa,
 * escrito num arquivo versionado de um repositório que tem remote. O CI nunca
 * alcançou esse caminho; um colaborador novo nunca alcançou; um agente em nuvem
 * nunca alcançou. E no dia em que o diretório mudou de lugar, ele parou de
 * alcançar também para quem o escreveu — em silêncio, porque um import que não
 * resolve não é um erro, é uma ausência.
 *
 * O repositório se declarava `ENGINEERING_OS_COMPLIANT` o tempo todo. Uma regra
 * que só um executor enxerga não é regra do repositório: é contexto privado de
 * uma sessão. `workflows/project-adoption.md` da própria camada global chama
 * isso pelo nome — "dead text, not a reference".
 *
 * ## As três decisões
 *
 * **1. O núcleo é puro e o corpus é derivado.** `plan()` decide o que copiar,
 * o que remover e o que já está idêntico a partir de duas listas de arquivos;
 * não tem processo, rede nem relógio, e é isso que
 * `tests/eos-sync-harness.test.mjs` exercita. A lista de arquivos sai de
 * `git ls-files` na origem, nunca de uma lista digitada aqui — mesma razão da
 * ADR 0033: um nome de arquivo escrito à mão é a lista que deixa de descrever
 * a origem no dia seguinte.
 *
 * **2. O pino é uma tag SemVer, e o que não é tag é recusado.** `PINNED_TAG` é
 * constante versionada: avançar o pino é um diff de uma linha, revisado como
 * qualquer outra mudança. Uma branch se move; um pino que se move não é pino.
 * `--tag main` falha, com essa frase.
 *
 * **3. O espelho continua vendorizado, e é isso que o torna offline.** Só a
 * *sincronização* precisa de rede. Depois dela, CI, colaborador novo e agente em
 * nuvem leem as regras do próprio checkout, sem rede e sem credencial. Um
 * submodule apontando para a tag resolveria a alcançabilidade e destruiria essa
 * propriedade.
 *
 * O `PROVENANCE.md` registra a tag **e** o commit que ela resolve, de modo que o
 * pino continue conferível se alguém quebrar a promessa de imutabilidade da tag.
 */

import { execFileSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmdirSync,
  rmSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DESTINATION = join(ROOT, "docs", "engineering-os");
const DEFAULT_ORIGIN = "https://github.com/biahflow/engineeringOS.git";
const PINNED_TAG = "v0.2.0";
const PROVENANCE_NAME = "PROVENANCE.md";

// Um `.gitignore` aninhado mudaria a semântica de ignore deste repositório dentro
// do diretório vendorizado; o espelho é documentação, não um checkout funcional.
const EXCLUDED_NAMES = new Set([".gitignore"]);

// Campos voláteis do PROVENANCE: reescrever o arquivo só para trocar a data
// produziria diff sem fato novo. O snapshot continua sendo o da data em que entrou.
const VOLATILE_PREFIXES = ["Última revisão:", "| Sincronizado em"];

class SyncFailure extends Error {}

/**
 * O núcleo puro: dadas as listas de arquivos da origem e do destino, decide o
 * que fazer. Sem processo, sem rede, sem relógio.
 *
 * @param {string[]} source arquivos rastreados na origem, relativos à raiz dela
 * @param {string[]} mirrored arquivos hoje presentes no espelho, relativos a ele
 * @returns {{ keep: string[], remove: string[] }}
 */
export function plan(source, mirrored) {
  const keep = source.filter((entry) => !EXCLUDED_NAMES.has(entry.split("/").pop()));
  const expected = new Set([...keep, PROVENANCE_NAME]);
  const remove = mirrored.filter((entry) => !expected.has(entry));
  return { keep: [...keep].sort(), remove: [...remove].sort() };
}

/** Remove da renderização do PROVENANCE os campos que mudam sem fato novo. */
export function stable(text) {
  return text
    .split("\n")
    .filter((line) => !VOLATILE_PREFIXES.some((prefix) => line.startsWith(prefix)))
    .join("\n");
}

export function provenanceText({ origin, tag, commit, count, today }) {
  return `# Proveniência do snapshot da Engineering OS

Status: Generated
Responsável: Engineering
Última revisão: ${today}

Este diretório é um **espelho pinado** da camada global da Engineering OS, vendorizado para
que CI, colaborador novo e agente em nuvem enxerguem as mesmas regras que o operador carrega
por fora. Os arquivos são cópia fiel da origem, em inglês, e **não são editados aqui** — nem
este registro, que é gerado pelo script.

| Campo | Valor |
|---|---|
| Origem | \`${origin}\` |
| Tag de origem | \`${tag}\` |
| Commit de origem | \`${commit}\` |
| Sincronizado em | ${today} |
| Arquivos espelhados | ${count} |

## Ressincronizar

Avançar o pino é trocar \`PINNED_TAG\` em \`scripts/sync-engineering-os.mjs\` e rodar:

\`\`\`bash
npm run eos:sync
\`\`\`

Ressincronizar é ato deliberado, não rotina automática: o script recusa referência que não
seja tag publicada, e o diff resultante é revisado como qualquer outra mudança do
repositório. Enquanto não houver nova sincronização, a tag acima é a versão da camada global
que vale para este repositório.
`;
}

function git(args, options = {}) {
  try {
    return execFileSync("git", args, { encoding: "utf8", ...options });
  } catch (error) {
    throw new SyncFailure(`git ${args.join(" ")} falhou: ${String(error.stderr ?? error).trim()}`);
  }
}

function origin() {
  return process.env.ONE_EOS_ORIGIN || DEFAULT_ORIGIN;
}

/**
 * Resolve a tag para o commit que ela aponta, recusando o que não for tag.
 *
 * Tag anotada tem dois refs no remoto: o objeto de tag e o commit sob `^{}`. O
 * pino é o commit — é ele que o PROVENANCE declara e que alguém consegue conferir.
 */
function resolveTag(source, tag) {
  const listing = git(["ls-remote", "--tags", source, `refs/tags/${tag}`, `refs/tags/${tag}^{}`]);
  const resolved = new Map();
  for (const line of listing.split("\n")) {
    const [commit, reference] = line.split("\t");
    if (reference) resolved.set(reference.trim(), commit.trim());
  }
  if (resolved.size === 0) {
    throw new SyncFailure(
      `tag inexistente no remoto: ${tag} em ${source}. O pino é uma tag SemVer publicada; ` +
        "branch se move e não serve de pino.",
    );
  }
  return resolved.get(`refs/tags/${tag}^{}`) ?? resolved.get(`refs/tags/${tag}`);
}

function trackedFiles(checkout) {
  return git(["-C", checkout, "ls-files", "-z"])
    .split("\0")
    .filter(Boolean);
}

function mirroredFiles(directory, prefix = "") {
  let entries;
  try {
    entries = readdirSync(directory, { withFileTypes: true });
  } catch {
    return [];
  }
  const found = [];
  for (const entry of entries) {
    const path = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) found.push(...mirroredFiles(join(directory, entry.name), path));
    else found.push(path);
  }
  return found;
}

/** Copia preservando o modo. Devolve false quando o destino já é idêntico. */
function copy(source, target) {
  const payload = readFileSync(source);
  const { mode } = statSync(source);
  try {
    const current = readFileSync(target);
    if (current.equals(payload) && statSync(target).mode === mode) return false;
  } catch {
    // destino ausente: segue para a escrita
  }
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, payload, { mode });
  return true;
}

function pruneEmptyDirectories(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const path = join(directory, entry.name);
    pruneEmptyDirectories(path);
    if (readdirSync(path).length === 0) rmdirSync(path);
  }
}

function synchronize(tag) {
  const source = origin();
  const commit = resolveTag(source, tag);
  const scratch = mkdtempSync(join(tmpdir(), "eos-sync-"));

  let keep;
  let remove;
  let copied;
  try {
    const checkout = join(scratch, "engineeringOS");
    git(["clone", "--depth", "1", "--branch", tag, "--quiet", source, checkout]);
    const decided = plan(trackedFiles(checkout), mirroredFiles(DESTINATION));
    keep = decided.keep;
    remove = decided.remove;
    if (keep.length === 0) throw new SyncFailure(`origem sem arquivos rastreados: ${source}@${tag}`);

    copied = keep.filter((entry) => copy(join(checkout, entry), join(DESTINATION, entry)));
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }

  for (const entry of remove) unlinkSync(join(DESTINATION, entry));
  pruneEmptyDirectories(DESTINATION);

  const today = new Date().toISOString().slice(0, 10);
  const text = provenanceText({ origin: source, tag, commit, count: keep.length, today });
  const target = join(DESTINATION, PROVENANCE_NAME);
  let rewritten = true;
  try {
    rewritten = stable(readFileSync(target, "utf8")) !== stable(text);
  } catch {
    // PROVENANCE ausente: será escrito
  }
  if (rewritten) writeFileSync(target, text);

  for (const entry of copied) console.log(`atualizado: ${entry}`);
  for (const entry of remove) console.log(`removido: ${entry}`);
  console.log(
    `Engineering OS ${tag} (${commit.slice(0, 7)}): ${keep.length} arquivos espelhados, ` +
      `${copied.length} atualizados, ${remove.length} removidos, ` +
      `${keep.length - copied.length} inalterados, ` +
      `PROVENANCE ${rewritten ? "reescrito" : "inalterado"}.`,
  );
}

function main() {
  const argv = process.argv.slice(2);
  const index = argv.indexOf("--tag");
  const tag = index === -1 ? PINNED_TAG : argv[index + 1];
  if (!tag) {
    console.error("--tag exige um valor, por exemplo --tag v0.1.0");
    process.exit(2);
  }
  try {
    synchronize(tag);
  } catch (error) {
    if (!(error instanceof SyncFailure)) throw error;
    console.error(error.message);
    process.exit(1);
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();

export { DESTINATION, PINNED_TAG, PROVENANCE_NAME };
