/**
 * A fixture do teste de SSR, conferida contra o contrato publicado (ADR 0020).
 *
 * `tests/fixtures/dashboard.mjs` afirma no próprio cabeçalho que suas respostas
 * "espelham o que `GET /api/v1/me` e `GET /api/v1/me/dashboard` devolvem".
 * Até esta fatia **nada conferia isso**. A API que `rendered-html.test.mjs`
 * sobe é de mentira, e uma API de mentira é livre para mentir: no dia em que
 * `build_dashboard` renomear uma chave, a fixture continua com o nome velho, o
 * `page.tsx` continua lendo o nome velho, e o teste continua verde — provando
 * que dois enganos combinam entre si.
 *
 * O que fecha isso não é um terceiro teste do web: é o esquema, que agora sai
 * do código Python e está versionado em `docs/api/openapi.json`. Validar a
 * fixture contra ele faz o verde do teste de SSR significar alguma coisa, e é o
 * nível 6 da pirâmide de `docs/testing-strategy.md` chegando também ao BFF.
 *
 * Não roda o Next: é comparação de JSON, e por isso é rápido e não precisa de
 * build.
 */
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, posix, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import Ajv2020 from "ajv/dist/2020.js";

import { DASHBOARD, ME, SEARCH } from "./fixtures/dashboard.mjs";

const SCHEMA_PATH = fileURLToPath(new URL("../docs/api/openapi.json", import.meta.url));
const document = JSON.parse(readFileSync(SCHEMA_PATH, "utf8"));

// `strict: false` porque o documento é OpenAPI, não JSON Schema puro: ele traz
// `paths`, `info` e outras chaves que o Ajv não conhece e que não são erro.
// `validateFormats: false` é deliberado e vale a explicação: os campos de data
// saem da API como texto de `.isoformat()`, e o modelo os declara como texto —
// checar `format: date-time` aqui seria checar uma promessa que o contrato não
// faz (ver o docstring de `portal_api/schemas.py`).
const ajv = new Ajv2020({ strict: false, validateFormats: false, allErrors: true });
ajv.addSchema({ ...document, $id: "openapi" });

function validator(name) {
  return ajv.compile({ $ref: `openapi#/components/schemas/${name}` });
}

function check(name, payload) {
  const validate = validator(name);
  const ok = validate(payload);
  assert.ok(
    ok,
    `a fixture não casa com ${name} do contrato publicado:\n` +
      (validate.errors ?? [])
        .map((e) => `  ${e.instancePath || "/"} ${e.message}`)
        .join("\n") +
      "\n\nRegenere o esquema (python -m portal_api.openapi --write) ou " +
      "corrija a fixture — uma das duas está descrevendo uma API que não existe.",
  );
}

test("o esquema publicado descreve as rotas que o BFF consome", () => {
  const schemas = document.components.schemas;
  for (const name of ["MeOut", "MyDashboardOut", "ResultsOut", "NotificationsOut", "SearchOut"]) {
    assert.ok(schemas[name], `o contrato não define ${name}`);
  }
});

test("a resposta de /api/v1/me na fixture é a que a API declara", () => {
  check("MeOut", ME);
});

test("a resposta de /api/v1/me/dashboard na fixture é a que a API declara", () => {
  check("MyDashboardOut", DASHBOARD);
});

test("a resposta de /api/v1/me/search na fixture é a que a API declara", () => {
  check("SearchOut", SEARCH);
});

test("um campo renomeado na fixture é recusado", () => {
  // A prova negativa: sem ela, este arquivo poderia estar validando contra um
  // esquema permissivo e passando por acidente.
  const renomeado = { ...DASHBOARD, organizacao: DASHBOARD.organization };
  delete renomeado.organization;
  const validate = validator("MyDashboardOut");
  assert.equal(validate(renomeado), false);
});

test("o contrato não deixa passar um campo que ninguém declarou", () => {
  // `extra="forbid"` do lado Python vira `additionalProperties: false` aqui, e
  // é o que impede o esquema de aceitar em silêncio o que a API descartaria.
  assert.equal(document.components.schemas.MyDashboardOut.additionalProperties, false);
  const validate = validator("MeOut");
  assert.equal(validate({ ...ME, campo_que_ninguem_declarou: 1 }), false);
});

/**
 * O contrato precisa ser **consumido**, não só casado (ADR 0029).
 *
 * As asserções acima provam que a fixture descreve a API de verdade. Nenhuma
 * delas olha o outro lado: se `build_dashboard` entrega um campo e o
 * mapeamento do BFF não o lê, o dado atravessa a rede, é tipado em
 * `app/page.tsx` e é jogado fora — a tela fica sem ele, a rota responde 200, e
 * nada fica vermelho.
 *
 * É exatamente o defeito que a ADR 0020 recusou acrescentar do lado Python
 * quando escolheu `extra="forbid"`, um passo adiante no caminho. Foi assim que
 * `priority` — coluna com enum desde a Fase 1, projetada pelo sync, declarada
 * em `PendingOut` e **declarada até no tipo `ApiPending`** — nunca chegou à
 * aba onde o cliente decide o que fazer primeiro.
 *
 * A asserção é sobre `.<chave>`, e não sobre a chave solta: `priority` aparecia
 * na declaração de tipo, então uma guarda sobre o nome nasceria verde em cima
 * do defeito que ela existe para pegar. O mapeamento é o único lugar onde estes
 * nomes são desreferenciados.
 *
 * **E ela mesma tinha o defeito que existe para pegar (ADR 0033).** Era um `for`
 * sobre oito nomes escritos à mão lendo um arquivo, num contrato com 56 esquemas
 * de resposta: os outros 48 nunca foram olhados, e a allowlist seguia vazia
 * porque nada a consultava — não porque nada escapava. A forma da ADR 0023, em
 * que o `dependency-review` *parecia* varredura e olhava só o diff de um PR.
 *
 * O limite fica declarado: a asserção é por **corpus**, então um `.confidence`
 * em qualquer arquivo de `app/` satisfaz `ConversationMessageOut.confidence`
 * ainda que o caminho do chat o descarte. O escopo por rota foi medido e
 * recusado — rotas de passagem põem o consumidor noutro arquivo, e a versão
 * estrita acusou 49 campos, quase todos falsos.
 */
const APP_DIR = fileURLToPath(new URL("../app", import.meta.url));

/**
 * Sem comentários: `POST /api/v1/agent-events` aparece em `app/` **só** dentro
 * de um comentário de `drive-callback/route.ts`, e sem esta linha a rota do
 * agente contaria como consumida pelo BFF — deixando de fora a única rota que
 * legitimamente não tem chamador aqui.
 */
function withoutComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

const SOURCE = new Map(
  readdirSync(APP_DIR, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && /\.tsx?$/.test(entry.name))
    .map((entry) => join(entry.parentPath ?? entry.path, entry.name))
    .map((file) => [
      "app/" + relative(APP_DIR, file).split(sep).join("/"),
      withoutComments(readFileSync(file, "utf8")),
    ]),
);

const CORPUS = [...SOURCE.values()].join("\n");

const segments = (path) => path.split("/").filter(Boolean);

/**
 * Quem consome o que cada arquivo produz — e é isto que faz a guarda ser
 * precisa em vez de só ampla (ADR 0033).
 *
 * **Um corpus único sobre todo `app/` foi medido e recusado**: ele deixa
 * `PendingOut.priority` passar, porque `.priority` também é o nome do campo na
 * *view*, num arquivo que recebe o valor por prop e não do JSON. Ou seja, a
 * versão ampla nasceria verde em cima do defeito exato da ADR 0029 — o mesmo
 * erro que a guarda existe para não repetir, cometido pela guarda.
 *
 * E o corpus estrito (só quem chama a rota) também não serve: as rotas de
 * `app/api/**` são **passagem** — devolvem o JSON sem mapear — e o consumidor
 * de verdade é quem as chama. Daí os dois elos:
 *
 * 1. `import` relativo: `KnowledgeClient.tsx` importa `../actions`, então ele
 *    entra no corpus de quem chamou a API por lá (`authorize_url` vive assim).
 * 2. `fetch("/api/…")`: `DashboardClient.tsx` não *importa*
 *    `app/api/chat/route.ts`, ele o chama por URL. Sem este elo, os oito campos
 *    de `ConversationMessageOut` apareceriam como descartados.
 *
 * Nada disso alcança `app/page.tsx`: ninguém o importa e ninguém o chama — é
 * um segmento de rota do Next. É por isso que `priority` volta a ser pego.
 */
const CONSUMERS = new Map([...SOURCE.keys()].map((file) => [file, new Set([file])]));
const ROUTE_FILES = [...SOURCE.keys()].filter((file) => file.endsWith("/route.ts"));

for (const [file, text] of SOURCE) {
  for (const spec of text.match(/from\s+["'][^"']+["']/g) ?? []) {
    const target = spec.slice(spec.indexOf('"') === -1 ? spec.indexOf("'") : spec.indexOf('"')).slice(1, -1);
    if (!target.startsWith(".")) continue;
    const base = posix.normalize(posix.join(posix.dirname(file), target));
    for (const candidate of [`${base}.tsx`, `${base}.ts`, `${base}/index.tsx`, `${base}/index.ts`]) {
      if (CONSUMERS.has(candidate)) CONSUMERS.get(candidate).add(file);
    }
  }
  // A rota interna do BFF que este arquivo chama por URL. `[documentId]` casa
  // com o `${documentId}` do template, e a query string é cortada.
  for (const hit of text.match(/\/api\/(?!v1\/)[^\s`"'),]*/g) ?? []) {
    const wanted = segments(hit.split("?")[0].replace(/\$\{[^}]*\}/g, "*"));
    for (const route of ROUTE_FILES) {
      const have = segments(route.slice("app".length, -"/route.ts".length));
      if (have.length !== wanted.length) continue;
      if (have.every((seg, i) => seg === wanted[i] || seg.startsWith("["))) {
        CONSUMERS.get(route).add(file);
      }
    }
  }
}

/** As rotas da API que um arquivo chama, no formato de caminho do OpenAPI. */
function apiCalls(text) {
  return (text.match(/api\/v1\/[^\s`"']*/g) ?? []).map(
    (path) => "/" + path.split("?")[0].replace(/\$\{[^}]*\}/g, "{x}").replace(/[`"']+$/, ""),
  );
}

function matches(openapiPath, called) {
  const wanted = segments(openapiPath);
  const got = segments(called);
  if (got.length !== wanted.length) return false;
  return wanted.every((seg, i) => seg === got[i] || seg.startsWith("{") || got[i] === "{x}");
}

const isCalled = (openapiPath) => apiCalls(CORPUS).some((call) => matches(openapiPath, call));

/** Todo `$ref` alcançável a partir de um nó do documento. */
function referenced(node, found = new Set()) {
  if (Array.isArray(node)) {
    for (const item of node) referenced(item, found);
  } else if (node && typeof node === "object") {
    if (typeof node.$ref === "string") found.add(node.$ref.split("/").pop());
    for (const value of Object.values(node)) referenced(value, found);
  }
  return found;
}

/** Um esquema e todos os que ele alcança por `$ref`. */
function withNested(names) {
  const all = new Set(names);
  for (let grew = true; grew; ) {
    grew = false;
    for (const name of [...all]) {
      for (const nested of referenced(document.components.schemas[name] ?? {})) {
        if (!all.has(nested)) {
          all.add(nested);
          grew = true;
        }
      }
    }
  }
  return all;
}

/**
 * Para cada esquema de resposta, os arquivos em que ele **pode** ser lido.
 *
 * O escopo sai do contrato, não de uma lista escrita à mão — foi a lista à mão
 * que produziu o defeito, e uma lista nova envelheceria igual. Rota nova com
 * esquema novo entra sozinha, no commit que a cria.
 */
function schemaCorpus() {
  const corpus = new Map();
  for (const [file, text] of SOURCE) {
    const calls = apiCalls(text);
    if (calls.length === 0) continue;
    for (const [path, operations] of Object.entries(document.paths)) {
      if (!calls.some((call) => matches(path, call))) continue;
      for (const operation of Object.values(operations)) {
        if (!operation || typeof operation !== "object") continue;
        for (const [code, response] of Object.entries(operation.responses ?? {})) {
          if (!code.startsWith("2")) continue;
          for (const name of withNested(referenced(response))) {
            if (!corpus.has(name)) corpus.set(name, new Set());
            for (const consumer of CONSUMERS.get(file)) corpus.get(name).add(consumer);
          }
        }
      }
    }
  }
  return corpus;
}

/**
 * Campos que a tela deliberadamente não usa, na forma `Esquema.campo`, com o
 * motivo escrito. Uma allowlist que cresce é o contrato dizendo que entrega o
 * que ninguém pediu.
 *
 * Até a ADR 0033 estava vazia — e não porque nada escapava: a guarda percorria
 * oito nomes escritos à mão de um contrato com 56 esquemas de resposta, então
 * nada a consultava. Generalizada, ela nasceu vermelha.
 *
 * As cinco que sobraram têm a mesma forma, e é a forma que as torna aceitáveis:
 * **eco**. São campos que a resposta devolve e que quem chamou já tinha em mãos
 * antes de chamar — não há o que a tela aprenda lendo-os.
 */
const NOT_CONSUMED = {
  "NotificationsReadOut.marked": {
    reason:
      "eco da própria escrita — quantas linhas o PATCH marcou. A tela recarrega a lista e conta sozinha.",
  },
  "PendingCommentsOut.pending_item_id": {
    reason: "eco do id que o BFF acabou de mandar no caminho da rota; o chamador já o tem em mãos.",
  },
  "PreferencesOut.notify_by_email": {
    reason: "eco do valor que a tela acabou de mandar no corpo; ela já sabe o que gravou.",
  },
  "AssistantSignalOut.project_id": {
    reason: "eco do projeto que a tela escolheu para montar a URL — é ela quem o pôs lá.",
  },
  "DocumentDownloadOut.expires_at": {
    reason:
      "a tela navega para a URL assinada no mesmo clique e não a guarda; o vencimento importa " +
      "a quem retém o link, que aqui é ninguém (ADR 0017).",
  },
  "MeProjectOut.slug": {
    reason:
      "o slug identifica o projeto no Biahflow; aqui a chave é o `id` e o rótulo é o `name`. " +
      "Fica no contrato porque `/admin` o usa para casar com a origem.",
    review_by: "2027-02-01",
  },
};

/**
 * Rotas que o BFF legitimamente não chama, com o motivo. Ao contrário dos
 * campos, aqui a lista não é sintoma: são as quatro superfícies do produto que
 * não têm navegador do outro lado.
 */
const NOT_CALLED = {
  "/health": { reason: "sonda de liveness; quem chama é o compose/orquestrador." },
  "/health/ready": { reason: "sonda de readiness, idem." },
  "/api/v1/agent-events": {
    reason:
      "rota de agente, autenticada por chave — a única exceção ao Bearer humano (ADR 0013).",
  },
  "/api/v1/integrations/biahflow/webhook": {
    reason: "quem chama é o Biahflow, não o navegador (ADR 0006).",
  },
  "/api/v1/projects/{project_id}/results": {
    reason:
      "mesma projeção que o dashboard já embute em `MyDashboardOut.measured` (um `$ref` para `ResultsOut`), " +
      "e é por lá que os campos chegam à tela. Existe para o detalhamento por período, que ainda não tem tela.",
    review_by: "2027-02-01",
  },
};

const CORPUS_BY_SCHEMA = schemaCorpus();

for (const [schema, files] of [...CORPUS_BY_SCHEMA].sort(([a], [b]) => a.localeCompare(b))) {
  test(`o BFF consome todo campo que ${schema} entrega`, () => {
    const properties = document.components.schemas[schema]?.properties ?? {};
    const reachable = [...files].map((file) => SOURCE.get(file)).join("\n");

    const dropped = Object.keys(properties).filter(
      (key) => !NOT_CONSUMED[`${schema}.${key}`] && !reachable.includes(`.${key}`),
    );

    assert.deepEqual(
      dropped,
      [],
      `o BFF recebe estes campos de ${schema} e não os lê: ${dropped.join(", ")}.` +
        " Mapeie-os, ou tire-os do contrato — um campo que a tela não usa é uma" +
        " pergunta para a API, não para o BFF (ADR 0029/0033).",
    );
  });
}

/**
 * O mesmo defeito um nível acima: uma rota inteira sem chamador.
 *
 * Foi assim que `GET /api/v1/projects/{project_id}/results` ficou de fora —
 * rota completa, com `response_model`, testada, cujo docstring diz que "é aqui
 * que o cliente vê a origem e a premissa de todo indicador deixa de ser
 * promessa", e que nenhum arquivo do BFF chama.
 */
test("toda rota do contrato tem quem a chame", () => {
  const orphans = Object.keys(document.paths).filter(
    (path) => !NOT_CALLED[path] && !isCalled(path),
  );

  assert.deepEqual(
    orphans,
    [],
    `estas rotas existem no contrato e nenhum arquivo de app/ as chama: ${orphans.join(", ")}.` +
      " Ligue-as à tela, tire-as da API, ou declare o motivo em NOT_CALLED (ADR 0033).",
  );
});

test("a allowlist não guarda entrada que deixou de ser necessária", () => {
  // A mesma regra do `advisories.json` (ADR 0023): a linha some quando o
  // motivo some. Sem isto a allowlist vira sedimento e a guarda afrouxa sozinha.
  const schemas = document.components.schemas;
  const obsolete = Object.keys(NOT_CONSUMED).filter((entry) => {
    const [schema, key] = entry.split(".");
    if (!schemas[schema]?.properties?.[key]) return true;
    const files = CORPUS_BY_SCHEMA.get(schema);
    if (!files) return true;
    return [...files].map((file) => SOURCE.get(file)).join("\n").includes(`.${key}`);
  });

  assert.deepEqual(
    obsolete,
    [],
    `NOT_CONSUMED guarda estas linhas e elas não são mais necessárias: ${obsolete.join(", ")}.`,
  );
});

/**
 * A metade que faltava: a ADR 0033 deu guarda de obsolescência ao `NOT_CONSUMED`
 * e não ao `NOT_CALLED`, de modo que uma rota que ganhasse chamador mantinha a
 * isenção para sempre — a assimetria é o defeito, como no `web.request_error`.
 */
test("a allowlist de rotas não guarda entrada que deixou de ser necessária", () => {
  const obsolete = Object.keys(NOT_CALLED).filter(
    (path) => !document.paths[path] || isCalled(path),
  );

  assert.deepEqual(
    obsolete,
    [],
    `NOT_CALLED guarda estas linhas e elas não são mais necessárias: ${obsolete.join(", ")}.`,
  );
});

/**
 * E o prazo vence de verdade.
 *
 * Até a ADR 0035 as duas entradas com prazo o traziam como **prosa dentro da
 * string de motivo** ("Rever em 02/2027"), e nada lia aquela data — enquanto o
 * `advisories.json`, citado como precedente na mesma decisão, reprova em
 * `review_by < today` (`scripts/audit.mjs`). Uma exceção sem vencimento é
 * permanente por omissão, que é o modo de falha que a ADR 0023 nomeou.
 */
test("uma exceção com prazo vencido reprova", () => {
  const today = new Date().toISOString().slice(0, 10);
  const expired = [
    ...Object.entries(NOT_CONSUMED),
    ...Object.entries(NOT_CALLED),
  ]
    .filter(([, entry]) => entry.review_by && entry.review_by < today)
    .map(([name, entry]) => `${name} (venceu em ${entry.review_by})`);

  assert.deepEqual(
    expired,
    [],
    `estas exceções venceram e precisam ser reavaliadas ou removidas: ${expired.join(", ")}.` +
      " Aceitar uma lacuna é decisão com prazo, não para sempre (ADR 0023/0035).",
  );
});
