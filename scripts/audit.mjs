#!/usr/bin/env node
/**
 * O portão de dependências vulneráveis, nos dois ecossistemas (Fase 5, ADR 0023).
 *
 *     npm run audit          # ou: node scripts/audit.mjs
 *
 * Mora em `scripts/` pela razão do `backup.sh` e do `loadtest.py`: é **operação**.
 * Não sobe rota, não é importado pela aplicação, e roda quando o CI ou alguém o
 * chama.
 *
 * ## Por que existe, se o CI já tinha `dependency-review`
 *
 * Porque eles respondem perguntas diferentes, e só uma delas estava sendo feita.
 * O `dependency-review-action` olha o **diff** de dependências de um pull
 * request: ele pega a biblioteca ruim *entrando*. O que já estava no
 * `package-lock.json` não é diff nenhum, e passava verde a cada push — foi assim
 * que nove avisos do `next`, seis do `python-multipart` e sete do `starlette`
 * conviveram meses com um CI de seis portões. Este script pergunta a outra
 * metade: o que está instalado **agora** tem aviso publicado?
 *
 * ## As três decisões
 *
 * **1. Uma porta só para os dois ecossistemas.** `npm audit` e `pip-audit`
 * respondem em formatos diferentes e são normalizados aqui, na forma do
 * `queue_document_scan`. Duas listas de exceção em dois formatos seriam duas
 * coisas para envelhecer em paralelo — e a metade Python é justamente a que não
 * existia.
 *
 * **2. Não há limiar de severidade.** Um `--audit-level=high` seria um segundo
 * mecanismo de exceção, e silencioso: tudo abaixo do corte passaria sem ninguém
 * escrever nada. Aqui só existe um jeito de um aviso não reprovar — alguém
 * escrever uma linha datada em `docs/security/advisories.json`, com motivo. É a
 * mesma regra do `skipped` não ser `clean` no `scanner.py`: a ausência de
 * verificação não vira afirmação de segurança. (O `pip-audit` sequer publica
 * severidade, então um limiar também não teria como valer para os dois lados.)
 *
 * **3. A exceção expira, e o registro não apodrece.** Uma entrada com
 * `review_by` no passado **reprova** — risco aceito é decisão com prazo, não
 * permissão permanente. E uma entrada que não casa com aviso nenhum também
 * reprova, pedindo que a linha saia: é o mesmo gate de deriva do `alembic
 * check`, do `openapi.json` e do `prompt-registry.json`.
 *
 * Note a diferença com o `prompt-registry.json`, que é **append-only**: lá a
 * história é o portão, e reescrever o passado é o que se quer impedir. Aqui a
 * entrada precisa poder sumir no dia em que o aviso é corrigido, senão o arquivo
 * vira uma lista de coisas que já não são verdade.
 */

import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const REGISTRY_PATH = path.join(REPO_ROOT, "docs", "security", "advisories.json");
const PIP_REQUIREMENTS = path.join("apps", "api", "requirements-dev.txt");

// --- o núcleo, puro ---------------------------------------------------------
//
// Sem processo, sem rede e sem relógio: `today` entra por parâmetro, na forma do
// `results.py` (que recebe o dia do evento em vez de olhar o calendário). É o
// que torna o próprio portão testável — e um mecanismo de exceção que ninguém
// testa vira passe geral, que foi a lição das asserções de backup da ADR 0020.

/**
 * @param {{id: string, aliases?: string[], package: string, ecosystem: string,
 *          severity?: string, title?: string, fixedIn?: string[]}[]} findings
 * @param {{id: string, package: string, reason: string, review_by: string}[]} registry
 * @param {string} today  data ISO (`YYYY-MM-DD`)
 */
export function evaluate(findings, registry, today) {
  const matches = (entry, finding) => {
    const ids = new Set([finding.id, ...(finding.aliases ?? [])]);
    return ids.has(entry.id) && entry.package === finding.package;
  };

  const accepted = [];
  const blocking = [];

  for (const finding of findings) {
    const entry = registry.find((candidate) => matches(candidate, finding));
    if (!entry) {
      blocking.push({ finding, why: "sem entrada em advisories.json" });
    } else if (entry.review_by < today) {
      blocking.push({
        finding,
        why: `exceção venceu em ${entry.review_by} — reavalie ou conserte`,
      });
    } else {
      accepted.push({ finding, entry });
    }
  }

  // Uma entrada que não casa com nada: ou o aviso foi corrigido (e a linha deve
  // sair), ou o `id`/`package` foram escritos errado — caso em que a exceção
  // nunca valeu para o aviso que alguém achou que estivesse aceitando, e o
  // arquivo dizia uma coisa enquanto o portão fazia outra.
  const stale = registry.filter(
    (entry) => !findings.some((finding) => matches(entry, finding)),
  );

  return { accepted, blocking, stale, ok: blocking.length === 0 && stale.length === 0 };
}

// --- as bordas, impuras -----------------------------------------------------

/** Roda um comando e devolve o stdout, aceitando saída != 0.
 *
 *  As duas ferramentas saem com código 1 **quando encontram vulnerabilidade** —
 *  que aqui é o caso normal e não um erro de execução. Distinguir os dois é o
 *  motivo de olhar o stdout: se não veio JSON, aí sim a ferramenta falhou. */
function run(command, args) {
  return new Promise((resolve, reject) => {
    execFile(command, args, { cwd: REPO_ROOT, maxBuffer: 64 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (stdout.trim()) return resolve(stdout);
      const hint =
        error?.code === "ENOENT"
          ? `\n  ${command} não está no PATH. Instale com:` +
            "\n    pip install \"$(grep '^pip-audit==' apps/api/requirements-dev.txt)\""
          : "";
      reject(new Error(`${command} não produziu saída: ${stderr || error?.message}${hint}`));
    });
  });
}

/** `npm audit --json` → a forma comum.
 *
 *  O id que vale é o GHSA, extraído da `url`: o `source` numérico é interno do
 *  registro do npm e não é o que alguém lê num aviso. */
export function normalizeNpm(report) {
  const findings = [];
  for (const [name, vulnerability] of Object.entries(report.vulnerabilities ?? {})) {
    for (const via of vulnerability.via ?? []) {
      // Uma string em `via` é "este pacote é vulnerável porque aquele é"; o
      // aviso em si aparece na entrada daquele outro pacote, então contá-la aqui
      // duplicaria o mesmo GHSA sob dois nomes.
      if (typeof via === "string") continue;
      const id = String(via.url ?? "").split("/").pop() || `npm-${via.source}`;
      findings.push({
        ecosystem: "npm",
        id,
        package: name,
        severity: via.severity,
        title: via.title,
        fixedIn: vulnerability.fixAvailable?.version
          ? [`${vulnerability.fixAvailable.name}@${vulnerability.fixAvailable.version}`]
          : [],
      });
    }
  }
  return findings;
}

/** `pip-audit --format json` → a forma comum.
 *
 *  O id é o PYSEC; os `aliases` (CVE, GHSA) entram porque é por eles que um
 *  aviso costuma ser citado, e quem escreve a exceção não deveria precisar
 *  descobrir qual dos nomes o `pip-audit` escolheu naquele dia. */
export function normalizePip(report) {
  const findings = [];
  for (const dependency of report.dependencies ?? []) {
    for (const vulnerability of dependency.vulns ?? []) {
      findings.push({
        ecosystem: "pip",
        id: vulnerability.id,
        aliases: vulnerability.aliases ?? [],
        package: dependency.name,
        title: (vulnerability.description ?? "").split("\n")[0].slice(0, 120),
        fixedIn: vulnerability.fix_versions ?? [],
      });
    }
  }
  // O mesmo PYSEC aparece mais de uma vez quando vem de fontes distintas.
  const seen = new Set();
  return findings.filter((finding) => {
    const key = `${finding.package}|${finding.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

async function collect() {
  const npmReport = JSON.parse(await run("npm", ["audit", "--json"]));
  const pipReport = JSON.parse(
    await run("pip-audit", ["-r", PIP_REQUIREMENTS, "--format", "json", "--progress-spinner", "off"]),
  );
  return [...normalizeNpm(npmReport), ...normalizePip(pipReport)];
}

function describe(finding) {
  const fix = finding.fixedIn?.length ? ` → corrigido em ${finding.fixedIn.join(", ")}` : "";
  return `[${finding.ecosystem}] ${finding.package}: ${finding.id}${fix}\n      ${finding.title ?? ""}`.trimEnd();
}

async function main() {
  const registry = JSON.parse(await readFile(REGISTRY_PATH, "utf8")).accepted ?? [];
  const findings = await collect();
  const today = new Date().toISOString().slice(0, 10);
  const { accepted, blocking, stale, ok } = evaluate(findings, registry, today);

  for (const { finding, entry } of accepted) {
    console.log(`aceito até ${entry.review_by}: ${describe(finding)}\n      motivo: ${entry.reason}`);
  }
  for (const { finding, why } of blocking) {
    console.error(`REPROVA ${describe(finding)}\n      ${why}`);
  }
  for (const entry of stale) {
    console.error(
      `REPROVA entrada obsoleta em docs/security/advisories.json: ${entry.id} (${entry.package})\n` +
        "      nenhum aviso corresponde a ela. Se o aviso foi corrigido, remova a linha.",
    );
  }

  if (ok) {
    console.log(
      `auditoria limpa: ${findings.length} aviso(s), ${accepted.length} aceito(s) com prazo.`,
    );
    return 0;
  }
  console.error(`\n${blocking.length + stale.length} pendência(s). Ver docs/runbooks/dependency-advisory.md`);
  return 1;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().then(
    (code) => process.exit(code),
    (error) => {
      console.error(error.message);
      process.exit(2);
    },
  );
}
