#!/usr/bin/env node
/**
 * A lista de pinos que o runbook mandava revisar, e o atualizador dela (ADR 0063).
 *
 *     npm run pins                    # ou: node scripts/pins.mjs
 *     node scripts/pins.mjs --update  # resolve e reescreve os pinos no lugar
 *
 * Mora em `scripts/` pela razão do `backup.sh`, do `loadtest.py` e do
 * `audit.mjs`: é **operação**. Não sobe rota, não é importado pela aplicação, e
 * roda quando alguém o chama.
 *
 * ## Por que existe
 *
 * `docs/runbooks/dependency-advisory.md` manda "revisar essas duas listas
 * junto, porque nada mais o fará" — as actions do CI e as imagens base — e
 * **as listas não existiam**. Nem no runbook, nem em lugar nenhum: o inventário
 * era um `grep` que ninguém tinha escrito, e a frase vizinha, "as imagens estão
 * fixadas em versão exata", era falsa desde que `docker-compose.yml` ganhou
 * `minio/minio:latest`.
 *
 * `apps/api/tests/test_supply_chain_pins.py` é o portão — ele **detecta**. Este
 * script é a outra metade, e a divisão é a mesma que o `audit.mjs` descreve: o
 * portão reprova, o conserto é de uma pessoa. A ADR 0062 desligou o Dependabot,
 * então não há robô que abra o PR; o que existe é um comando que quem revisa
 * roda, lê e confere no diff.
 *
 * ## As quatro decisões
 *
 * **1. O núcleo é puro e o corpus é derivado.** `references()` e `rewrite()` não
 * têm processo, rede nem relógio — na forma do `evaluate()` do `audit.mjs` —, e
 * é isso que `tests/pins-harness.test.mjs` exercita. As quatro superfícies
 * (workflow, Dockerfile, compose, Terraform) saem de glob, nunca de uma lista
 * digitada: é a ADR 0033 outra vez, e um nome de arquivo escrito à mão aqui
 * seria a lista que deixa de descrever o repositório no dia seguinte.
 *
 * **2. O digest é o do índice multi-arquitetura, nunca o de uma plataforma.**
 * Pinar o manifesto de `linux/amd64` quebra no arm64 de quem desenvolve, e pinar
 * o de `arm64` quebra no runner do GitHub. O digest é calculado **localmente**,
 * como sha256 dos bytes que `docker buildx imagetools inspect --raw` devolve,
 * que é literalmente a definição de digest OCI — e o `mediaType` é conferido
 * para que um índice não seja confundido com um manifesto de plataforma.
 * (`--format '{{.Manifest.Digest}}'` **não** serve no Docker 29: `.Manifest` ali
 * é o *conteúdo* do índice, não um descritor, e o template cai em silêncio na
 * saída padrão — medido.)
 *
 * **3. `--update` resolve, mas não escolhe.** Uma referência sem tag, ou com a
 * tag `latest`, é deixada em paz e apenas anunciada: escolher em que versão o
 * portal vai ficar é decisão de uma pessoa, e um digest colado em `latest`
 * produziria um pino que o portão continua reprovando — a tag existe para ser
 * lida. É a mesma regra do `skipped` não ser `clean` no `scanner.py`.
 *
 * **4. Sem flag ele imprime e sai 0.** O inventário não é um veredito: quem
 * reprova é o pytest. O código 2 fica reservado para **não consegui medir** —
 * sem rede, sem `gh`, sem docker —, mantendo a distinção que o `audit.mjs`
 * estabeleceu entre achar problema e não ter conseguido olhar.
 */

import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** Diretórios que a varredura não atravessa: artefato de instalação e de build. */
const NOT_OURS = new Set([".venv", "node_modules", ".next", ".git", "test-results"]);

// --- o núcleo, puro ---------------------------------------------------------
//
// Sem processo, sem rede e sem relógio. Recebe e devolve texto, na forma do
// `evaluate()` do `audit.mjs` — que é o que permite `tests/pins-harness.test.mjs`
// exercitar o casador contra recortes reais dos arquivos deste repositório sem
// subir nada.

/** `uses:` de workflow. O valor é tudo até o espaço, o que deixa o `# v4` fora
 *  da referência e dentro da linha. */
const USES = /^([ \t]*(?:-[ \t]+)?uses:[ \t]*)(\S+)/;

/** `image:` de compose **e** dos blocos `services:` de workflow — um casador só,
 *  porque são a mesma coisa: uma imagem de terceiro que sobe ao lado do job. */
const IMAGE = /^([ \t]*(?:-[ \t]+)?image:[ \t]*)(\S+)/;

/** `FROM` de Dockerfile. `--platform=` é engolido pelo prefixo para que a
 *  reescrita não o perca. */
const FROM = /^(FROM[ \t]+(?:--platform=\S+[ \t]+)?)(\S+)/i;

/** O `default` literal de um `variable` de imagem. O recorte por **nome da
 *  variável** acontece em `references()`; aqui só se lê a linha. */
const TF_DEFAULT = /^([ \t]+default[ \t]*=[ \t]*")([^"$]+)(")/;

/** Abertura do bloco `variable` cujo nome fala de imagem, e o fim dele: a
 *  próxima linha que começa na coluna zero. Um contador de chaves teria de saber
 *  ler heredoc (`<<-TXT … TXT`), e o conteúdo de heredoc é indentado. */
const TF_IMAGE_VARIABLE = /^variable[ \t]+"[^"]*(?:imagem|image)[^"]*"/i;
const TF_TOP_LEVEL = /^\S/;

/** `docker run|pull|create` dentro de um bloco `run:` de workflow — a imagem
 *  que o CI **de fato** puxa, e que nenhum `image:` alcança. Existe porque a
 *  única referência assim do repositório era a pior de todas, um `latest` no
 *  job que valida o backup (ADR 0063). `docker build` fica de fora: ele nomeia
 *  um Dockerfile, que `FROM` já cobre. */
const DOCKER_CLI = /\bdocker[ \t]+(?:run|pull|create)\b/g;

/** As flags que tomam **valor separado** — a única lista digitada deste arquivo,
 *  e ela envelhece com a CLI do Docker, não com o repositório. Espelha
 *  `_DOCKER_VALUE_FLAGS` da guarda em pytest: as duas leem a mesma regra, e
 *  divergir faria o inventário e o portão discordarem sobre o mesmo comando. */
const DOCKER_VALUE_FLAGS = new Set([
  "-e", "--env", "-p", "--publish", "--name", "-v", "--volume", "--network",
  "-w", "--workdir", "-u", "--user", "-l", "--label", "--entrypoint", "--platform",
]);

/** A linha de uma imagem de `docker run`, para a reescrita. Solta de propósito:
 *  `rewrite()` só troca o que estiver na tabela de resoluções, então a chave é
 *  a referência exata e não o formato da linha. */
const DOCKER_IMAGE_LINE = /^([ \t]*)([^\s-][^\s]*:[^\s]+)/;

/** Ação local: código deste repositório, não dependência de terceiro. */
const LOCAL_ACTION = /^\.{1,2}\//;

const ACTION_PIN = /^([^@\s]+)@([0-9a-f]{40})$/;
const IMAGE_PIN = /^([^@\s]+):([A-Za-z0-9_][\w.\-]*)@sha256:([0-9a-f]{64})$/;
const VERSION_COMMENT = /#[ \t]*(v\d[\w.\-+]*)/;

/** Os casadores de cada superfície, e o tipo de referência que cada um produz. */
const MATCHERS = {
  workflow: [
    { pattern: USES, type: "action" },
    { pattern: IMAGE, type: "image" },
  ],
  compose: [{ pattern: IMAGE, type: "image" }],
  dockerfile: [{ pattern: FROM, type: "image" }],
  terraform: [{ pattern: TF_DEFAULT, type: "image" }],
};

/** Quebra uma referência de imagem em nome, tag e digest. */
function parseImage(ref) {
  const [name, digest] = ref.split("@sha256:");
  const last = name.slice(name.lastIndexOf("/") + 1);
  const colon = last.indexOf(":");
  return {
    name: colon === -1 ? name : name.slice(0, name.length - (last.length - colon)),
    tag: colon === -1 ? null : last.slice(colon + 1),
    digest: digest ?? null,
  };
}

/**
 * As imagens que um `docker run|pull|create` nomeia, com continuação de linha.
 *
 * A partir do subcomando os tokens são percorridos: quem começa com `-` é flag,
 * quem é valor de flag que toma valor é pulado, e o primeiro token que sobra é a
 * imagem. **Fail-closed:** se nada sobrar, é falha deste casador — flag nova ou
 * forma não prevista — e o erro sobe, porque "não achei a imagem" não pode valer
 * como "não há imagem aqui" (ADR 0063). Mesma semântica de `docker_run_images`
 * da guarda em pytest.
 */
function dockerRunImages(text) {
  const lines = text.split("\n");
  const found = [];

  DOCKER_CLI.lastIndex = 0;
  for (const match of text.matchAll(DOCKER_CLI)) {
    const lineStart = text.lastIndexOf("\n", match.index) + 1;
    const firstLine = text.slice(0, match.index).split("\n").length - 1;
    const tokens = [];

    let idx = firstLine;
    let remainder = lines[idx].slice(match.index + match[0].length - lineStart);
    for (;;) {
      const stripped = remainder.replace(/[ \t]+$/, "");
      const continues = stripped.endsWith("\\");
      const content = continues ? stripped.slice(0, -1) : stripped;
      for (const token of content.split(/\s+/).filter(Boolean)) tokens.push([token, idx + 1]);
      if (!continues) break;
      idx += 1;
      if (idx >= lines.length) break;
      remainder = lines[idx];
    }

    let image = null;
    for (let i = 0; i < tokens.length; ) {
      const [token] = tokens[i];
      if (token.startsWith("-")) {
        i += DOCKER_VALUE_FLAGS.has(token) ? 2 : 1;
        continue;
      }
      image = tokens[i];
      break;
    }

    if (!image) {
      throw new Error(
        `não achei a imagem depois de \`docker run|pull|create\` na linha ${firstLine + 1} de um workflow: ` +
          `\`${tokens.map(([t]) => t).join(" ")}\`. Ou o comando não nomeia imagem, ou usa flag que este ` +
          `casador não conhece — as duas pedem revisão humana (ADR 0063).`,
      );
    }

    const [ref, refLine] = image;
    const clean = ref.replace(/^["']|["']$/g, "");
    const parts = parseImage(clean);
    const pin = clean.match(IMAGE_PIN);
    found.push({
      line: refLine,
      type: "image",
      ref: clean,
      ...parts,
      pinned: Boolean(pin) && parts.tag !== "latest",
    });
  }

  return found;
}

/**
 * As referências de terceiro de um texto.
 *
 * `kind` é uma das quatro superfícies. Devolve, por ocorrência, o número da
 * linha, o tipo, a referência crua e o estado do pino — que é exatamente o que o
 * inventário imprime e o que `resolve()` precisa saber para não pedir à rede o
 * que já está resolvido.
 *
 * @param {string} text
 * @param {"workflow"|"compose"|"dockerfile"|"terraform"} kind
 */
export function references(text, kind) {
  const matchers = MATCHERS[kind];
  if (!matchers) throw new Error(`superfície desconhecida: ${kind}`);

  const lines = text.split("\n");
  const found = [];

  // Dockerfile: um `FROM <etapa>` aponta para dentro do próprio build e não é
  // imagem — cobrar digest dele seria cobrar o digest de algo que ainda não
  // existe. Hoje não ocorre (as duas imagens encadeiam por `COPY --from=`), e
  // sem isto o primeiro que encadeasse entraria no corpus como imagem.
  const stages = new Set();

  // Terraform: só as linhas de dentro de um bloco `variable` de imagem contam.
  // Fora dele, `default = "…"` é a porta de saída, o domínio, o id da zona do
  // Cloudflare — literais que ninguém pina.
  let insideImageVariable = false;

  lines.forEach((line, index) => {
    if (kind === "terraform") {
      if (TF_TOP_LEVEL.test(line)) insideImageVariable = TF_IMAGE_VARIABLE.test(line);
      if (!insideImageVariable) return;
    }

    for (const { pattern, type } of matchers) {
      const match = line.match(pattern);
      if (!match) continue;

      const ref = match[2];

      if (type === "action") {
        if (LOCAL_ACTION.test(ref)) return;
        const pin = ref.match(ACTION_PIN);
        const version = line.match(VERSION_COMMENT);
        found.push({
          line: index + 1,
          type,
          ref,
          name: pin ? pin[1] : ref.split("@")[0],
          tag: pin ? null : (ref.split("@")[1] ?? null),
          sha: pin ? pin[2] : null,
          version: version ? version[1] : null,
          pinned: Boolean(pin) && Boolean(version),
        });
        return;
      }

      if (kind === "dockerfile") {
        const stage = line.match(/[ \t]+AS[ \t]+(\S+)/i);
        const isStage = stages.has(ref.toLowerCase()) || ref.toLowerCase() === "scratch";
        if (stage) stages.add(stage[1].toLowerCase());
        if (isStage) return;
      }

      const parts = parseImage(ref);
      const pin = ref.match(IMAGE_PIN);
      found.push({
        line: index + 1,
        type,
        ref,
        ...parts,
        pinned: Boolean(pin) && parts.tag !== "latest",
      });
      return;
    }
  });

  if (kind === "workflow") found.push(...dockerRunImages(text));

  return found.sort((a, b) => a.line - b.line);
}

/**
 * O texto com os pinos aplicados, e **nada mais mudado**.
 *
 * Reescreve só o trecho da referência dentro da linha que a contém: indentação,
 * hífen de lista, aspas do HCL e o resto do arquivo ficam onde estavam. O
 * comentário de versão é a única outra coisa que se mexe, e só nas linhas de
 * action — nas de imagem a versão mora na própria tag.
 *
 * @param {string} text
 * @param {Record<string, {ref: string, version?: string}>} resolutions
 *        referência atual → referência nova (e a versão a anotar ao lado)
 */
export function rewrite(text, resolutions) {
  const patterns = [USES, IMAGE, FROM, TF_DEFAULT, DOCKER_IMAGE_LINE];

  return text
    .split("\n")
    .map((line) => {
      for (const pattern of patterns) {
        const match = line.match(pattern);
        if (!match) continue;

        const resolution = resolutions[match[2]];
        if (!resolution) continue;

        const start = match[1].length;
        let rewritten =
          line.slice(0, start) + resolution.ref + line.slice(start + match[2].length);

        if (resolution.version) {
          rewritten = VERSION_COMMENT.test(rewritten)
            ? rewritten.replace(VERSION_COMMENT, `# ${resolution.version}`)
            : `${rewritten} # ${resolution.version}`;
        }
        return rewritten;
      }
      return line;
    })
    .join("\n");
}

// --- as bordas, impuras -----------------------------------------------------

function run(command, args) {
  return new Promise((resolve, reject) => {
    execFile(command, args, { cwd: REPO_ROOT, maxBuffer: 64 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (!error) return resolve(stdout);
      const hint =
        error.code === "ENOENT"
          ? `\n  ${command} não está no PATH. O inventário roda sem ele; o --update não.`
          : "";
      reject(new Error(`${command} ${args.join(" ")} falhou: ${stderr || error.message}${hint}`));
    });
  });
}

/** Os arquivos de uma superfície, e **reprova se não achar nenhum**.
 *
 *  Mesmo argumento do `_files` da guarda em pytest: um inventário que fica vazio
 *  por não achar arquivo é indistinguível de um repositório sem pinos a rever, e
 *  foi assim que o `dependency-review` passou verde por meses (ADR 0033). */
async function walk(dir, accept, out = []) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    if (NOT_OURS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) await walk(full, accept, out);
    else if (accept(path.relative(REPO_ROOT, full), entry.name)) out.push(full);
  }
  return out;
}

async function surfaces() {
  const collected = [
    {
      kind: "workflow",
      files: await walk(path.join(REPO_ROOT, ".github", "workflows"), (_, name) =>
        /\.ya?ml$/.test(name),
      ),
    },
    {
      kind: "compose",
      files: (await readdir(REPO_ROOT)).filter((name) => /^docker-compose.*\.ya?ml$/.test(name))
        .map((name) => path.join(REPO_ROOT, name)),
    },
    {
      kind: "dockerfile",
      files: await walk(REPO_ROOT, (_, name) => name.startsWith("Dockerfile")),
    },
    {
      kind: "terraform",
      files: await walk(path.join(REPO_ROOT, "infra", "terraform"), (_, name) =>
        name.endsWith(".tf"),
      ),
    },
  ];

  for (const surface of collected) {
    if (surface.files.length === 0) {
      throw new Error(
        `a superfície \`${surface.kind}\` não tem nenhum arquivo. Ou o corpus mudou de` +
          " lugar, ou os arquivos sumiram — nos dois casos esta lista deixaria de" +
          " descrever o repositório (ADR 0063).",
      );
    }
  }
  return collected;
}

async function inventory() {
  const rows = [];
  for (const { kind, files } of await surfaces()) {
    for (const file of files.sort()) {
      const text = await readFile(file, "utf8");
      for (const reference of references(text, kind)) {
        rows.push({ file: path.relative(REPO_ROOT, file), kind, ...reference });
      }
    }
  }
  return rows;
}

/** O SHA de commit de uma tag de action.
 *
 *  O subcaminho é descartado de propósito: `github/codeql-action/init` e
 *  `github/codeql-action/analyze` são duas ações **do mesmo repositório**, e o
 *  SHA é do repositório. */
async function actionSha(name, tag) {
  const [owner, repo] = name.split("/");
  const sha = (await run("gh", ["api", `repos/${owner}/${repo}/commits/${tag}`, "--jq", ".sha"])).trim();
  if (!/^[0-9a-f]{40}$/.test(sha)) {
    throw new Error(`o \`gh\` devolveu algo que não é SHA para ${name}@${tag}: ${sha}`);
  }
  return sha;
}

/** O digest do **índice** de uma imagem, calculado dos bytes do manifesto.
 *
 *  Ver a decisão 2 no topo: o digest OCI é o sha256 dos bytes, então calculá-lo
 *  aqui é mais barato e mais verificável que pedir a um template que o Docker 29
 *  não resolve. O `mediaType` é lido para que um manifesto de plataforma não
 *  passe por índice — pinar `linux/amd64` quebraria no arm64 de quem
 *  desenvolve. */
async function imageDigest(ref) {
  const raw = await run("docker", ["buildx", "imagetools", "inspect", ref, "--raw"]);
  const digest = createHash("sha256").update(raw).digest("hex");
  let mediaType = "";
  try {
    mediaType = JSON.parse(raw).mediaType ?? "";
  } catch {
    throw new Error(`o manifesto de ${ref} não é JSON — não dá para conferir se é índice`);
  }
  const isIndex = /image\.index|manifest\.list/.test(mediaType);
  return { digest: `sha256:${digest}`, mediaType, isIndex };
}

function state(row) {
  if (row.pinned) return "pinado";
  if (row.type === "action") {
    return row.sha ? "sem versão ao lado" : `tag móvel (${row.tag ?? "sem tag"})`;
  }
  if (!row.tag) return row.digest ? "digest sem tag legível" : "sem tag";
  if (row.tag === "latest") return "tag `latest`";
  return "sem digest";
}

async function listing(rows) {
  const width = Math.max(...rows.map((row) => `${row.file}:${row.line}`.length));
  for (const row of rows) {
    const where = `${row.file}:${row.line}`.padEnd(width);
    console.log(`${where}  ${row.ref}  [${state(row)}]`);
  }
  const loose = rows.filter((row) => !row.pinned);
  console.log(
    `\n${rows.length} referência(s) — ${rows.length - loose.length} pinada(s), ${loose.length} sem pino.` +
      "\nO portão é `apps/api/tests/test_supply_chain_pins.py`; `--update` resolve o que for resolúvel.",
  );
  return 0;
}

async function update(rows) {
  const resolutions = {};
  const needsAPerson = [];

  for (const row of rows) {
    if (row.pinned || resolutions[row.ref]) continue;

    if (row.type === "action") {
      if (row.sha) continue; // já tem SHA; o que falta é o comentário, escrito abaixo
      if (!row.tag) {
        needsAPerson.push(`${row.file}:${row.line} ${row.ref}: sem tag, nada a resolver`);
        continue;
      }
      const sha = await actionSha(row.name, row.tag);
      resolutions[row.ref] = { ref: `${row.name}@${sha}`, version: row.tag };
      console.log(`${row.ref} → ${row.name}@${sha} # ${row.tag}`);
      continue;
    }

    if (!row.tag || row.tag === "latest") {
      needsAPerson.push(
        `${row.file}:${row.line} ${row.ref}: ${row.tag ? "tag `latest`" : "sem tag"} —` +
          " escolha a versão à mão e rode de novo, ou declare a isenção em" +
          " `PINNED_BY_EXCEPTION`",
      );
      continue;
    }
    const { digest, mediaType, isIndex } = await imageDigest(row.ref);
    resolutions[row.ref] = { ref: `${row.name}:${row.tag}@${digest}` };
    console.log(
      `${row.ref} → ${resolutions[row.ref].ref}` +
        (isIndex ? "" : `\n      atenção: ${mediaType} não é índice multi-arquitetura`),
    );
  }

  // As ações que já tinham SHA e perderam (ou nunca tiveram) o comentário: o
  // `gh` sabe dizer de que tag aquele SHA saiu, mas perguntar custaria uma
  // chamada por pino a cada execução. Elas ficam para a pessoa, que é quem sabe.
  for (const row of rows) {
    if (row.type === "action" && row.sha && !row.version) {
      needsAPerson.push(
        `${row.file}:${row.line} ${row.ref}: tem SHA e não diz de que versão é —` +
          " escreva `# vX` no fim da linha",
      );
    }
  }

  let touched = 0;
  for (const { kind, files } of await surfaces()) {
    for (const file of files) {
      const before = await readFile(file, "utf8");
      const after = rewrite(before, resolutions);
      if (after !== before) {
        await writeFile(file, after, "utf8");
        touched += 1;
        console.log(`  reescrito ${path.relative(REPO_ROOT, file)} (${kind})`);
      }
    }
  }

  for (const line of needsAPerson) console.log(`escolha necessária: ${line}`);
  console.log(`\n${Object.keys(resolutions).length} referência(s) resolvida(s), ${touched} arquivo(s) reescrito(s).`);
  return 0;
}

async function main() {
  const rows = await inventory();
  return process.argv.includes("--update") ? update(rows) : listing(rows);
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
