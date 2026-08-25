#!/usr/bin/env node
/**
 * O número da ADR, alocado num ponto de coordenação (ADR 0072).
 *
 *     npm run adr -- "A flag que o casador não conhecia"
 *     node scripts/adr.mjs "A flag que o casador não conhecia"
 *
 * Mora em `scripts/` pela razão do `backup.sh`, do `audit.mjs` e do `pins.mjs`: é
 * **operação**. Não sobe rota, não é importado pela aplicação, e roda quando
 * alguém o chama.
 *
 * ## Por que existe
 *
 * O número era escolhido quando a branch nascia — alguém olhava `docs/adr/`,
 * pegava o seguinte — e só era reivindicado no merge. Entre os dois momentos,
 * outra branch levava o mesmo número. Aconteceu três vezes em 25/08/2026, e a
 * terceira foi a fatia que consertava a segunda.
 *
 * **Detecção não fecha corrida.** `test_no_two_adr_files_share_the_same_number`
 * acha a colisão depois de ela existir, e a colisão só existe depois do merge —
 * o número livre de dez minutos atrás não é o número livre de agora. O que fecha
 * é `docs/adr/number-registry.tsv`: um arquivo ordenado a que toda ADR
 * acrescenta uma linha **no fim**, no mecanismo do `schema.rb` do Rails e do
 * `max_migration.txt` do django-linear-migrations. Dois appends na mesma posição
 * conflitam no git, e o conflito é a coordenação que faltava.
 *
 * ## As três decisões
 *
 * **1. O próximo número sai do maior reivindicado, dos dois lados.** Registro e
 * diretório, unidos: uma ADR cujo arquivo existe sem linha (ou o contrário) é
 * vermelho no `api-quality`, mas enquanto ela existir a ferramenta não pode
 * entregar um número já tomado por um dos dois. É o mesmo fail-closed das
 * guardas — na dúvida, o número seguinte, nunca o buraco.
 *
 * **2. Ele escreve as duas coisas ou nenhuma.** O arquivo da ADR e a linha do
 * registro saem do mesmo comando porque separá-los reintroduz o defeito: um
 * arquivo sem linha é um número que ninguém reivindicou.
 *
 * **3. A linha do `ROADMAP.md` continua sendo de quem escreve.** Ela é prosa
 * sobre o que mudou de estado publicado, e nenhum esqueleto sabe escrevê-la —
 * quem a cobra é `test_roadmap_index.py` (ADR 0054). O comando lembra, e para.
 */

import { readFile, readdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ADR_DIR = path.join(REPO_ROOT, "docs", "adr");
const REGISTRY = path.join(ADR_DIR, "number-registry.tsv");

// --- o núcleo, puro ---------------------------------------------------------
//
// Sem processo, sem rede e sem relógio: o dia entra por parâmetro, na forma do
// `evaluate()` do `audit.mjs` e do `references()` do `pins.mjs`.

/** A mesma forma que a guarda em pytest exige: `NNNN<TAB>slug`. */
const REGISTRY_LINE = /^(\d{4})\t([a-z0-9]+(?:-[a-z0-9]+)*)$/;

/** As linhas válidas do registro, na ordem em que estão. */
export function registryRows(text) {
  const rows = [];
  for (const line of text.split("\n")) {
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    const found = REGISTRY_LINE.exec(line);
    if (found) rows.push({ number: Number(found[1]), slug: found[2] });
  }
  return rows;
}

/**
 * O título em kebab-case, sem acento.
 *
 * A decomposição NFD separa o acento da letra e a faixa combinante o remove, que
 * é o que faz `Decisão` virar `decisao` sem uma tabela de pares digitada à mão —
 * o defeito que as ADRs 0033 e 0071 catalogaram.
 */
export function slugify(title) {
  return title
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** O menor número que ninguém reivindicou — registro e diretório juntos. */
export function nextNumber(claimed) {
  return claimed.length === 0 ? 1 : Math.max(...claimed) + 1;
}

/** O esqueleto de cabeçalho da casa. O corpo é de quem escreve. */
export function skeleton(number, title, today) {
  const day = String(today.getDate()).padStart(2, "0");
  const month = String(today.getMonth() + 1).padStart(2, "0");
  return `# ADR ${String(number).padStart(4, "0")} — ${title}

**Status:** aceito
**Data:** ${day}/${month}/${today.getFullYear()}
**Fase:**

## Contexto

## Decisão

## Consequências
`;
}

/** A linha nova vai para o **fim**, e é o append que produz o conflito. */
export function withLine(text, number, slug) {
  const body = text.endsWith("\n") || text === "" ? text : `${text}\n`;
  return `${body}${String(number).padStart(4, "0")}\t${slug}\n`;
}

// --- as bordas, impuras -----------------------------------------------------

async function adrNumbersOnDisk() {
  const names = await readdir(ADR_DIR);
  return names
    .filter((name) => /^\d{4}-.+\.md$/.test(name))
    .map((name) => Number(name.slice(0, 4)));
}

async function main() {
  const title = process.argv.slice(2).join(" ").trim();
  if (!title) {
    console.error(
      'uso: npm run adr -- "Título da decisão"\n' +
        "O título vira o slug do arquivo e a linha do registro; o número não se escolhe.",
    );
    return 2;
  }

  const slug = slugify(title);
  if (!slug) {
    console.error(
      `o título ${JSON.stringify(title)} não produz slug — ele precisa de ao menos` +
        " uma letra ou dígito.",
    );
    return 2;
  }

  const registryText = await readFile(REGISTRY, "utf8");
  const rows = registryRows(registryText);
  if (rows.length === 0) {
    console.error(
      `o registro \`${path.relative(REPO_ROOT, REGISTRY)}\` não tem nenhuma linha` +
        " válida — sem ele não há número reivindicado, e alocar por conta própria" +
        " seria voltar a escolher à mão (ADR 0072).",
    );
    return 2;
  }

  const claimed = [...rows.map((row) => row.number), ...(await adrNumbersOnDisk())];
  const number = nextNumber(claimed);
  const file = path.join(ADR_DIR, `${String(number).padStart(4, "0")}-${slug}.md`);

  await writeFile(file, skeleton(number, title, new Date()), { flag: "wx" });
  await writeFile(REGISTRY, withLine(registryText, number, slug), "utf8");

  console.log(path.relative(REPO_ROOT, file));
  console.log(path.relative(REPO_ROOT, REGISTRY));
  console.log(
    `\nADR ${String(number).padStart(4, "0")} alocada. A linha no \`ROADMAP.md\`` +
      " continua sendo sua, e `test_roadmap_index.py` a cobra no mesmo commit (ADR 0054).",
  );
  return 0;
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
