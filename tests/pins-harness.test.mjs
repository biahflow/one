/**
 * O núcleo do atualizador de pinos, testado no que ele tem de perigoso (ADR 0063).
 *
 * Não precisa de build, de rede nem de docker — como `audit-harness.test.mjs` e
 * `api-contract.test.mjs`, e ao contrário de `rendered-html.test.mjs`. O que se
 * exercita é o núcleo puro de `scripts/pins.mjs`: `references()`, que produz o
 * inventário, e `rewrite()`, que aplica os pinos.
 *
 * **As amostras são recortes reais** dos arquivos deste repositório, como no
 * harness do `audit.mjs`, e pela mesma razão: uma amostra inventada testaria o
 * casador contra a minha ideia do formato. Há **uma** exceção, declarada onde
 * aparece — o `FROM <etapa>` de build encadeado, que nenhum Dockerfile daqui usa
 * hoje e cuja ausência do corpus é justamente o que precisa ficar garantido
 * antes de o primeiro existir.
 *
 * O que estes testes existem para impedir é a **reescrita que estraga o
 * arquivo**. `--update` mexe em `ci.yml`, `deploy-hml.yml` e `infra-hml.yml` —
 * os três workflows que carregam credencial de deploy e de infraestrutura — e um
 * `rewrite` que come indentação, comentário ou a linha vizinha produziria um
 * diff que ninguém revisa de verdade porque é grande demais. Daí as asserções
 * serem sobre o **arquivo inteiro**, e não só sobre a linha trocada.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { references, rewrite } from "../scripts/pins.mjs";

/** Recorte real de `.github/workflows/ci.yml` (linhas 18-33). */
const WORKFLOW = `    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 24.12.0
          cache: npm
      - run: npm ci
      - run: npm run lint
      - run: npm test

  api-quality:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    services:
      postgres:
        image: pgvector/pgvector:pg16
`;

/** Recorte real de `Dockerfile` (linhas 9-20) — as duas etapas do BFF. */
const DOCKERFILE = `FROM node:24.12.0-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build


FROM node:24.12.0-alpine AS runtime
`;

/** Recorte real de `docker-compose.yml` (linhas 67-79). */
const COMPOSE = `  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
`;

/** Recorte real de `infra/terraform/ambientes/hml-biahflow/variables.tf`
 *  (linhas 23-52), com as duas variáveis de imagem: a que é composta com o SHA
 *  do commit e nasce vazia, e a que traz o placeholder do Cloud Run. */
const TERRAFORM = `variable "tag_imagem" {
  description = <<-TXT
    A tag das imagens a implantar. **SHA do commit, nunca \`latest\`**.
  TXT
  type        = string
  default     = ""
}

variable "imagem_bootstrap" {
  description = <<-TXT
    A imagem com que um serviço **nasce**, antes de o primeiro deploy existir.
  TXT
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "bucket_estado" {
  description = "Onde ler o state da fundação."
  type        = string
  default     = "biahflow-hml-tfstate"
}
`;

test("lê as actions e as imagens de um workflow, com linha e estado do pino", () => {
  const found = references(WORKFLOW, "workflow");

  assert.deepEqual(
    found.map((r) => [r.line, r.type, r.ref, r.pinned]),
    [
      [3, "action", "actions/checkout@v4", false],
      [4, "action", "actions/setup-node@v4", false],
      [17, "image", "pgvector/pgvector:pg16", false],
    ],
  );
  // `node-version: 24.12.0` e os três `run:` não são referência nenhuma: o
  // casador é ancorado na palavra-chave, não em "algo que parece versão".
  assert.equal(found.length, 3);
});

test("a `image:` de um bloco `services:` cai no mesmo casador da do compose", () => {
  // São a mesma coisa — uma imagem de terceiro que sobe ao lado do job — e uma
  // superfície separada para elas seria uma segunda lista para envelhecer em
  // paralelo.
  const doWorkflow = references(WORKFLOW, "workflow").find((r) => r.type === "image");
  const doCompose = references(COMPOSE, "compose")[0];

  assert.equal(doWorkflow.name, "pgvector/pgvector");
  assert.equal(doWorkflow.tag, "pg16");
  assert.equal(doCompose.name, "redis");
  assert.equal(doCompose.tag, "7-alpine");
});

test("a tag `latest` não conta como pino, com ou sem digest", () => {
  const [, minio] = references(COMPOSE, "compose");
  assert.equal(minio.ref, "minio/minio:latest");
  assert.equal(minio.pinned, false);

  const comDigest = COMPOSE.replace(
    "minio/minio:latest",
    `minio/minio:latest@sha256:${"a".repeat(64)}`,
  );
  assert.equal(references(comDigest, "compose")[1].pinned, false);
});

test("lê os `FROM` de um Dockerfile, os dois da mesma imagem", () => {
  const found = references(DOCKERFILE, "dockerfile");

  assert.deepEqual(
    found.map((r) => [r.line, r.ref]),
    [
      [1, "node:24.12.0-alpine"],
      [10, "node:24.12.0-alpine"],
    ],
  );
});

test("um `FROM <etapa>` não entra no corpus — não é imagem, é o próprio build", () => {
  // **Amostra construída**, e é a única do arquivo: nenhum Dockerfile daqui
  // encadeia por `FROM <etapa>` hoje (os dois usam `COPY --from=builder`). Sem
  // esta cláusula, o primeiro que encadeasse faria a guarda cobrar o digest de
  // uma imagem que ainda não existe — vermelho que ninguém consegue atender.
  const encadeado = `FROM node:24.12.0-alpine AS builder
RUN npm ci

FROM builder AS testes
RUN npm test

FROM scratch AS artefato
COPY --from=builder /app/.next /
`;

  assert.deepEqual(
    references(encadeado, "dockerfile").map((r) => r.ref),
    ["node:24.12.0-alpine"],
  );
});

test("no Terraform só o `default` de variável de imagem entra", () => {
  const found = references(TERRAFORM, "terraform");

  // `tag_imagem` tem `default = ""` — vazio significa "primeiro apply" e não é
  // referência —, e `bucket_estado` é literal de outra coisa: um casador por
  // *forma de string* traria toda URL e todo id do repositório junto.
  assert.deepEqual(
    found.map((r) => r.ref),
    ["us-docker.pkg.dev/cloudrun/container/hello"],
  );
  assert.equal(found[0].line, 14);
  assert.equal(found[0].tag, null);
});

test("reescreve o pino da action preservando indentação, hífen e a linha vizinha", () => {
  const sha = "11bd71901bbe5b1630ceea73d27597364c9af683";
  const depois = rewrite(WORKFLOW, {
    "actions/checkout@v4": { ref: `actions/checkout@${sha}`, version: "v4" },
  });

  const antes = WORKFLOW.split("\n");
  const linhas = depois.split("\n");

  assert.equal(linhas[2], `      - uses: actions/checkout@${sha} # v4`);
  // Todas as outras linhas, byte por byte: um `rewrite` que reindenta ou
  // reserializa o YAML produziria um diff que ninguém revisa.
  for (let i = 0; i < antes.length; i += 1) {
    if (i === 2) continue;
    assert.equal(linhas[i], antes[i], `linha ${i + 1} mudou sem precisar`);
  }
  assert.equal(references(depois, "workflow")[0].pinned, true);
});

test("reescreve o digest da imagem sem inventar comentário de versão", () => {
  // Na imagem a versão mora na própria tag, então não há `# vX` a acrescentar —
  // e acrescentá-lo duplicaria a informação em dois lugares que podem divergir.
  const digest = `sha256:${"b".repeat(64)}`;
  const depois = rewrite(COMPOSE, {
    "redis:7-alpine": { ref: `redis:7.4.10-alpine@${digest}` },
  });

  assert.equal(depois.split("\n")[1], `    image: redis:7.4.10-alpine@${digest}`);
  assert.ok(!depois.includes("#"));
  assert.equal(references(depois, "compose")[0].pinned, true);
});

test("reescreve o `default` do HCL por dentro das aspas", () => {
  const digest = `sha256:${"c".repeat(64)}`;
  const depois = rewrite(TERRAFORM, {
    "us-docker.pkg.dev/cloudrun/container/hello": {
      ref: `us-docker.pkg.dev/cloudrun/container/hello:1@${digest}`,
    },
  });

  assert.ok(
    depois.includes(
      `  default     = "us-docker.pkg.dev/cloudrun/container/hello:1@${digest}"`,
    ),
  );
  // O alinhamento do `=` do HCL é o que o `terraform fmt -check` confere.
  assert.ok(depois.includes('  default     = ""'));
  assert.ok(depois.includes('  default     = "biahflow-hml-tfstate"'));
});

test("uma referência sem resolução não é tocada", () => {
  // `--update` deixa em paz o que não sabe resolver — tag `latest`, ausência de
  // tag —, porque escolher a versão é decisão de uma pessoa. O texto tem de
  // voltar idêntico, e não "quase idêntico".
  assert.equal(rewrite(COMPOSE, {}), COMPOSE);
  assert.equal(rewrite(WORKFLOW, { "outra/coisa@v1": { ref: "x" } }), WORKFLOW);
});

test("reescrever um pino já anotado troca a versão em vez de acrescentar outra", () => {
  const antigo = "      - uses: actions/checkout@" + "a".repeat(40) + " # v4\n";
  const novo = rewrite(antigo, {
    [`actions/checkout@${"a".repeat(40)}`]: {
      ref: `actions/checkout@${"d".repeat(40)}`,
      version: "v5",
    },
  });

  assert.equal(novo, `      - uses: actions/checkout@${"d".repeat(40)} # v5\n`);
});

test("uma superfície desconhecida falha em vez de devolver lista vazia", () => {
  // Lista vazia é o vermelho que fica verde: seria uma superfície inteira
  // saindo do inventário sem que ninguém notasse (ADR 0033).
  assert.throws(() => references(COMPOSE, "helm"), /superfície desconhecida/);
});

// --- `docker run`, a referência que nenhum `image:` alcança (ADR 0063) -------
//
// O recorte é o `Boot MinIO` do `ci.yml` reduzido: importa que o comando quebre
// em continuação de linha e que a imagem venha depois de flags que tomam valor,
// porque foi exatamente essa forma que passou despercebida.

const DOCKER_RUN_WORKFLOW = `jobs:
  backup-restore:
    steps:
      - name: Boot MinIO
        run: |
          docker run -d --name minio -p 9000:9000 \\
            -e MINIO_ROOT_USER=portal-minio \\
            minio/minio:latest server /data
`;

test("acha a imagem de um `docker run` quebrado em continuação de linha", () => {
  const found = references(DOCKER_RUN_WORKFLOW, "workflow");
  const image = found.find((reference) => reference.name === "minio/minio");

  assert.ok(image, "a imagem do `docker run` tem de entrar no corpus");
  assert.equal(image.line, 8, "a linha é a da imagem, não a do subcomando (que está na 6)");
  assert.equal(image.tag, "latest");
  assert.equal(image.pinned, false);
});

test("o valor de `--name` e o de `-p` não são tomados por imagem", () => {
  const found = references(DOCKER_RUN_WORKFLOW, "workflow");
  const refs = found.map((reference) => reference.ref);

  assert.deepEqual(refs, ["minio/minio:latest"]);
  assert.ok(!refs.includes("minio"), "`--name minio` é valor de flag, não imagem");
  assert.ok(!refs.includes("9000:9000"), "`-p 9000:9000` é valor de flag, não imagem");
});

test("um `docker run` sem imagem alguma falha em vez de passar em silêncio", () => {
  const semImagem = `jobs:
  x:
    steps:
      - run: docker run --rm
`;

  assert.throws(
    () => references(semImagem, "workflow"),
    /não achei a imagem/,
    "não achar a imagem não pode valer como não haver imagem",
  );
});

test("o pino de um `docker run` é reescrito como o de qualquer outra imagem", () => {
  const alvo = "minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:" + "1".repeat(64);
  const saida = rewrite(DOCKER_RUN_WORKFLOW, {
    "minio/minio:latest": { ref: alvo },
  });

  assert.match(saida, /^ {12}minio\/minio:RELEASE[^\s]+ server \/data$/m);
  assert.ok(saida.includes("--name minio -p 9000:9000"), "o resto do comando não se mexe");
});
