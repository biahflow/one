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
  // `PreferencesOut.notify_by_email` estava aqui como "eco do valor que a tela
  // acabou de mandar; ela já sabe o que gravou", e a ADR 0043 tornou a frase falsa:
  // a tela passou a **adotar** o que o servidor devolve, porque o telefone é
  // normalizado lá e o `phone_hint` é derivado de lá. A linha saiu porque o campo
  // é lido de verdade agora — e foi a guarda de allowlist obsoleta que a cobrou,
  // que é o segundo lado dela funcionando.
  "AssistantSignalOut.project_id": {
    reason: "eco do projeto que a tela escolheu para montar a URL — é ela quem o pôs lá.",
  },
  "DocumentDownloadOut.expires_at": {
    reason:
      "a tela navega para a URL assinada no mesmo clique e não a guarda; o vencimento importa " +
      "a quem retém o link, que aqui é ninguém (ADR 0017).",
  },
  // Quatro das seis linhas de frescor da F-028 saíram aqui, e é o prazo funcionando: elas
  // diziam "a superfície está gated pelo Design Approval", o DAP r1 foi aprovado e a
  // superfície existe — `app/page.tsx` lê `observed_at` e `synced_at` e a jornada carimba.
  //
  // `projection_version` fica, com o motivo **verdadeiro** desta vez, e não com o do
  // recorte: ele não é para a tela mostrar. Existe para "o Biahflow parou de avançar" ser
  // respondível sem abrir o Postgres e para dar sentido ao `applied_version` do
  // `projection.stale_rejected` — nada disso é pergunta de cliente. Mapeá-lo no BFF só para
  // esvaziar esta lista seria o código morto que a guarda daria por consumido, que é o
  // defeito exato que a ADR 0033 existe para pegar.
  //
  // **Sem prazo, e não é sedimento**: o precedente é o `PINNED_BY_EXCEPTION` da ADR 0063 e
  // não o `advisories.json` — a razão não vence por calendário, e quem a vence é a asserção
  // de obsolescência abaixo, no dia em que o campo ganhar leitor de verdade.
  "DashboardOut.projection_version": {
    reason:
      "a versão da projeção não é para a tela: existe para 'o Biahflow parou de avançar' " +
      "ser respondível sem abrir o Postgres, e para dar sentido ao `applied_version` do " +
      "`projection.stale_rejected` (ADR 0076).",
  },
  "MyDashboardOut.projection_version": {
    reason: "o mesmo campo, na rota que o BFF chama de fato. Ver `DashboardOut.projection_version`.",
  },
  // O aceite do entregável (ADR 0077). As duas primeiras são **eco**, na forma
  // exata do `PendingCommentsOut.pending_item_id`: o BFF acabou de pedir o
  // histórico *por este* `external_ref`, e ele já o tem em mãos.
  "DeliverableAcceptancesOut.deliverable_external_ref": {
    reason: "eco do id que o BFF acabou de mandar no caminho da rota.",
  },
  "DeliverableAcceptanceOut.deliverable_external_ref": {
    reason: "idem, na linha: é a chave por onde o histórico foi pedido.",
  },
  // As duas seguintes não são eco, e a razão é outra: elas existem **para o outro
  // lado**. `phase_name` e `deliverable_name` são congelados na escrita para que o
  // registro continue dizendo sobre o quê alguém decidiu depois de o entregável
  // sumir do read model — e quem projeta esse registro é o Biahflow, não a tela. O
  // card de revisão nasce da jornada, que é a verdade de hoje, e repetir na linha
  // do histórico o rótulo que está no cabeçalho do card seria ruído.
  //
  // **E é esta linha que decidiu o nome do campo novo da ADR 0088.** A asserção de
  // obsolescência pergunta se o corpus daquele esquema contém `.phase_name`, e o
  // corpus é por *arquivo*: `app/page.tsx` mapeia o dashboard inteiro, então está no
  // corpus de `DeliverableAcceptanceOut` **e** no de `DecisionOut`. Um
  // `DecisionOut.phase_name` faria esta linha ser cobrada como obsoleta — sobre um
  // campo que a tela continua sem ler — e apagá-la deixaria a metade de cobertura
  // verde por coincidência com outro identificador, que é o `.priority` da ADR 0033
  // outra vez. Medido: com `phase_name`, vermelho aqui; com `journey_phase_name`, os
  // dois campos ficam verificáveis um a um (e a mutação confirma o elo do novo).
  "DeliverableAcceptanceOut.phase_name": {
    reason:
      "denormalizado na escrita para o registro sobreviver ao read model (ADR 0077); " +
      "quem o lê é o outro lado, e a tela monta o card a partir da jornada.",
  },
  "DeliverableAcceptanceOut.deliverable_name": {
    reason: "idem — o nome congelado no momento da decisão, para o outro lado.",
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
  "/api/v1/integrations/whatsapp/webhook": {
    reason:
      "quem chama é o fornecedor do canal, com recibo de entrega e resposta do cliente — " +
      "não o navegador (FDD 021, ADR 0043). Mesma isenção do webhook acima, e pelo mesmo motivo.",
  },
  "/api/v1/projects/{project_id}/results": {
    reason:
      "mesma projeção que o dashboard já embute em `MyDashboardOut.measured` (um `$ref` para `ResultsOut`), " +
      "e é por lá que os campos chegam à tela. Existe para o detalhamento por período, que ainda não tem tela.",
    review_by: "2027-02-01",
  },
};

const CORPUS_BY_SCHEMA = schemaCorpus();

/**
 * `.<campo>` desreferenciado, e **não** só contido (ADR 0061).
 *
 * `String.includes(".${key}")` dá um campo por consumido quando o corpus contém outro
 * campo cujo nome o **prefixa**: `.project_id` contém `.project`. É a quarta vez que
 * esta família aparece — o `.priority` da ADR 0033, o `date`/`dated_at` da ADR 0038, o
 * `.item`/`.items` da ADR 0057 — e as duas últimas foram resolvidas renomeando o
 * campo, o que aqui não serve: `project_id` é o nome que `AssistantSignalOut` e
 * `PendingCommentsOut` já usam, e um sinônimo seria um segundo vocabulário.
 *
 * **E o sufixo sozinho não bastou** — a medição achou uma segunda frouxidão, esta
 * anterior à fatia: `...project` é um *spread* da variável, não uma leitura do JSON, e
 * contém `.project`. `app/page.tsx` tem um, e com ele a mutação abaixo continuava
 * verde. Daí as duas âncoras: nada de `.` antes (exclui o spread) e nada de `\w`
 * depois (exclui o prefixo). Um acesso encadeado — `a.b.project` — segue casando,
 * porque ali o caractere anterior ao ponto é uma letra.
 *
 * Medido no commit que publicou `MyDashboardOut.project_id`, apagando o `data.project`
 * de `app/page.tsx` — o único consumidor de `DashboardOut.project`: por `includes`,
 * verde; só com o sufixo, verde; com as duas, `project`.
 */
function dereferences(text, key) {
  return new RegExp(`(?<!\\.)\\.${key}(?![A-Za-z0-9_])`).test(text);
}

for (const [schema, files] of [...CORPUS_BY_SCHEMA].sort(([a], [b]) => a.localeCompare(b))) {
  test(`o BFF consome todo campo que ${schema} entrega`, () => {
    const properties = document.components.schemas[schema]?.properties ?? {};
    const reachable = [...files].map((file) => SOURCE.get(file)).join("\n");

    const dropped = Object.keys(properties).filter(
      (key) => !NOT_CONSUMED[`${schema}.${key}`] && !dereferences(reachable, key),
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

/**
 * E o mesmo defeito na direção de **entrada**: um parâmetro que o contrato
 * publica e que ninguém envia (ADR 0059).
 *
 * A guarda de consumo acima pergunta se o BFF **lê** o que a API entrega. Ela é
 * cega para o outro sentido, e o custo disso foi medido: `ChatIn.project_id`
 * existe desde a Fase 3, `POST /api/v1/chat` o usa para escolher o projeto por
 * `access.scoped_project`, e **o BFF nunca o mandou** — o corpo saía com
 * `{question, conversation_id}` e o projeto acabava sendo a membership mais
 * recente. É o espelho exato do achado da ADR 0033 (painel sobre campo sem
 * escritor); aqui é campo de entrada sem remetente.
 *
 * Alcance: `query` e `requestBody`. Parâmetro de **caminho** fica de fora — a
 * URL o carrega por construção, e a guarda de rota acima já prova que a URL é
 * montada.
 *
 * **Corpus por rota, nunca único, e isto foi medido** (a terceira vez, depois do
 * `.priority` da ADR 0033 e do `date`/`dated_at` da ADR 0038): com um corpus
 * único sobre `app/**`, `ChatIn.project_id` passa verde, porque as três
 * ocorrências de `project_id` em `app/` são leitura de **resposta** — o painel de
 * `/admin/assistant` e o callback do Drive —, nunca envio.
 *
 * **E o casamento é sobre a posição de envio, não sobre o nome solto.** Também
 * medido: `\bproject\b` casa com `app/page.tsx` em `projects.map((project) =>` e
 * em `project: (data.project as string)`, de modo que a guarda daria o
 * `?project=` da caixa de avisos como enviado **antes de ele existir**. Um
 * parâmetro de query só é enviado numa URL (`?nome=`/`&nome=`) ou por nome citado
 * (`searchParams.get("nome")`); um campo de corpo só é enviado como chave de
 * objeto (`nome:`, ou a forma curta `{ nome }`) ou por nome citado
 * (`formData.append("nome", …)`). É a mesma razão pela qual a guarda de consumo
 * casa `.chave` e não `chave`: o lugar onde o nome aparece de verdade.
 */
function requestBodySchemas(operation) {
  return Object.values(operation.requestBody?.content ?? {}).map((media) => ({
    name: media.schema?.$ref?.split("/").pop() ?? "(inline)",
    schema: media.schema?.$ref
      ? document.components.schemas[media.schema.$ref.split("/").pop()]
      : media.schema,
  }));
}

/** Os parâmetros de entrada de uma operação, cada um com o kind que o casa. */
function inputsOf(operation) {
  const inputs = (operation.parameters ?? [])
    .filter((parameter) => parameter.in === "query")
    .map((parameter) => ({ name: parameter.name, kind: "query", owner: "query" }));
  for (const { name, schema } of requestBodySchemas(operation)) {
    for (const key of Object.keys(schema?.properties ?? {})) {
      inputs.push({ name: key, kind: "body", owner: name });
    }
  }
  return inputs;
}

const quoted = (name) => new RegExp(`["'\`]${name}["'\`]`);

function isSent(text, { name, kind }) {
  if (kind === "query") {
    // **Ler não é mandar, e isto foi medido.** Com a aspa solta valendo para
    // query, apagar o repasse de `?project=` dentro de `app/api/search/route.ts`
    // deixa a guarda verde: o proxy continua contendo `query.get("project")` — o
    // parâmetro que ele recebe do navegador e **não** repassa à API. Um parâmetro
    // de query só sai de dentro de uma URL, ou de quem a monta peça por peça.
    return (
      new RegExp(`[?&]${name}=`).test(text) ||
      new RegExp(`(set|append)\\(\\s*["'\`]${name}["'\`]`).test(text)
    );
  }
  if (quoted(name).test(text)) return true;
  return (
    // chave explícita: `folder_id: folderId`
    new RegExp(`(^|[{,(\\s])${name}\\s*:`, "m").test(text) ||
    // forma curta: `{ question, conversation_id: … }`
    new RegExp(`[{,]\\s*${name}\\s*(,|\\}|$)`, "m").test(text)
  );
}

/**
 * O arquivo que **monta a requisição** de cada rota, e só ele.
 *
 * Deliberadamente mais estreito que o corpus da guarda de rota acima, que inclui
 * os consumidores: lá a pergunta é "alguém chega a esta rota?", e um `fetch`
 * numa tela que passa por `app/api/**` conta. Aqui a pergunta é "quem manda este
 * parâmetro?", e a resposta é o arquivo que escreve a URL ou o corpo — o proxy,
 * quando há um.
 *
 * **Medido**: com os consumidores no corpus, apagar o repasse de `?project=`
 * **dentro** de `app/api/search/route.ts` deixa a guarda verde, porque o
 * `&project=` do `DashboardClient.tsx` — que fala com o proxy, não com a API —
 * satisfaz a busca do nome. O parâmetro sairia do navegador e morreria no BFF,
 * que é exatamente o defeito desta fatia acontecendo um andar acima.
 */
function routeCorpus() {
  const corpus = new Map(Object.keys(document.paths).map((path) => [path, new Set()]));
  for (const [file, text] of SOURCE) {
    const calls = apiCalls(text);
    if (calls.length === 0) continue;
    for (const path of Object.keys(document.paths)) {
      if (!calls.some((call) => matches(path, call))) continue;
      corpus.get(path).add(file);
    }
  }
  return corpus;
}

/**
 * Parâmetros que o BFF deliberadamente não envia, com o motivo escrito. Mesma
 * regra das duas allowlists acima: a linha some quando o motivo some.
 */
const NOT_THE_BFF = {
  reason:
    "rota de agente, autenticada por chave: quem monta este corpo é o produtor de eventos, " +
    "não o navegador (ADR 0013). Mesma isenção que a rota tem em NOT_CALLED.",
};
const NO_SCREEN_YET = {
  reason:
    "o recorte por período de `GET /projects/{id}/results`, que ainda não tem tela — a rota " +
    "inteira está isenta em NOT_CALLED pelo mesmo motivo.",
  review_by: "2027-02-01",
};

const NOT_SENT = {
  "POST /api/v1/agent-events agent_key": NOT_THE_BFF,
  "POST /api/v1/agent-events avoided_cost_cents": NOT_THE_BFF,
  "POST /api/v1/agent-events event_id": NOT_THE_BFF,
  "POST /api/v1/agent-events event_type": NOT_THE_BFF,
  "POST /api/v1/agent-events human_intervention": NOT_THE_BFF,
  "POST /api/v1/agent-events occurred_at": NOT_THE_BFF,
  "POST /api/v1/agent-events outcome": NOT_THE_BFF,
  "POST /api/v1/agent-events project_id": NOT_THE_BFF,
  "POST /api/v1/agent-events run_reference": NOT_THE_BFF,
  "POST /api/v1/agent-events time_saved_seconds": NOT_THE_BFF,
  "GET /api/v1/projects/{project_id}/results from": NO_SCREEN_YET,
  "GET /api/v1/projects/{project_id}/results to": NO_SCREEN_YET,
  "GET /api/v1/me/notifications unread_only": {
    reason:
      "a caixa do sino mostra lidos e não lidos juntos, então o BFF fica com o padrão `false`; " +
      "o filtro existe para quem quiser só o que falta ler, e ninguém quer ainda.",
  },
  "GET /api/v1/me/notifications limit": {
    reason: "o padrão de 50 é a página inteira do popover; não há paginação na tela.",
  },
  "GET /api/v1/admin/projects/{project_id}/assistant-signal limit": {
    reason:
      "o painel de `/admin/assistant` mostra a janela padrão; recortá-la é pergunta que " +
      "a tela ainda não faz.",
  },
  "POST /api/v1/admin/projects/{project_id}/keys expires_in_days": {
    reason:
      "a tela cria a chave com o vencimento padrão da API; escolher o prazo é decisão que " +
      "o formulário de `/admin` ainda não oferece.",
  },
};

const CORPUS_BY_ROUTE = routeCorpus();

/** Todo par (rota, parâmetro) que o corpus da rota não mostra sendo enviado. */
function unsentInputs() {
  const missing = new Map();
  for (const [path, operations] of Object.entries(document.paths)) {
    const reachable = [...CORPUS_BY_ROUTE.get(path)]
      .map((file) => SOURCE.get(file))
      .join("\n");
    for (const [method, operation] of Object.entries(operations)) {
      if (!operation || typeof operation !== "object") continue;
      for (const input of inputsOf(operation)) {
        if (isSent(reachable, input)) continue;
        missing.set(`${method.toUpperCase()} ${path} ${input.name}`, { path, ...input });
      }
    }
  }
  return missing;
}

const UNSENT = unsentInputs();

for (const path of Object.keys(document.paths).sort()) {
  const inputs = Object.values(document.paths[path]).flatMap((operation) =>
    operation && typeof operation === "object" ? inputsOf(operation) : [],
  );
  if (inputs.length === 0) continue;

  test(`o BFF envia todo parâmetro que ${path} recebe`, () => {
    const orphans = [...UNSENT]
      .filter(([key, input]) => input.path === path && !NOT_SENT[key])
      .map(([key]) => key);

    assert.deepEqual(
      orphans,
      [],
      `estes parâmetros existem no contrato e nenhum chamador de ${path} os envia: ` +
        `${orphans.join(", ")}. Mande-os, tire-os da API, ou declare o motivo em NOT_SENT` +
        " — um parâmetro de entrada sem remetente é o espelho do campo sem leitor (ADR 0033/0059).",
    );
  });
}

test("a allowlist de parâmetros não guarda entrada que deixou de ser necessária", () => {
  const obsolete = Object.keys(NOT_SENT).filter((key) => !UNSENT.has(key));

  assert.deepEqual(
    obsolete,
    [],
    `NOT_SENT guarda estas linhas e elas não são mais necessárias: ${obsolete.join(", ")}.`,
  );
});

test("uma exceção de parâmetro com prazo vencido reprova", () => {
  const today = new Date().toISOString().slice(0, 10);
  const expired = Object.entries(NOT_SENT)
    .filter(([, entry]) => entry.review_by && entry.review_by < today)
    .map(([name, entry]) => `${name} (venceu em ${entry.review_by})`);

  assert.deepEqual(expired, [], `estas exceções venceram: ${expired.join(", ")}.`);
});

/**
 * ============================================================================
 * O guard de visibilidade: as nove proibições (ADR 0082).
 * ============================================================================
 *
 * A metade de **cobertura** — "todo campo que sai para o cliente está
 * classificado" — vive em `apps/api/tests/test_visibility.py`, do lado da API,
 * porque é a API quem decide o que sai: as seis rotas de `app/api/**` são
 * passagem crua (`Response.json(await response.json())`, nenhuma filtra campo),
 * e filtrar aqui seria uma segunda autoridade sobre a mesma pergunta.
 *
 * Esta metade afirma outra coisa: que o que sai **não é nenhuma das nove coisas
 * proibidas** pela §3 do Language Map. E afirma sobre duas superfícies — o
 * contrato publicado e as **fixtures** deste diretório —, porque a fixture é
 * onde uma resposta forjada é livre para mentir, que é a razão de este arquivo
 * existir desde a ADR 0020.
 *
 * As duas metades leem **um artefato só**, `docs/contracts/one-visibility.json`,
 * inclusive o recorte do corpus. Não é o defeito da ADR 0034 (duas guardas sobre
 * o mesmo arquivo divergem): lá eram duas guardas afirmando a mesma coisa; aqui
 * são duas afirmações distintas sobre um dado só, e o corpus está no artefato
 * justamente para as duas metades não o reimplementarem cada uma do seu jeito.
 *
 * As nove, e onde cada uma é afirmada:
 *
 *   1. `Lead` .......................... termo em `forbidden_resources`
 *   2. `Qualification` e seu resultado . termo em `forbidden_resources`
 *   3. `CommercialOpportunity`,
 *      `PipelineStage`, valor,
 *      probabilidade .................. dois termos + `forbidden_field_names`
 *   4. Evidence não revisada e
 *      transcrição bruta .............. `reviewed_resources` (a marca) e
 *                                       `forbidden_field_names` (o texto bruto)
 *   5. `PriorityAssessment.rationale` .. `forbidden_pairs`
 *   6. preço de tabela, margem,
 *      `Service.price` ................ `forbidden_field_names` + um par
 *   7. Case de outros clientes ......... termo em `forbidden_resources`
 *   8. qualquer dado de outra Account .. `account_identifier_inputs` aqui, e a
 *                                       linha do banco em `test_authorization.py`
 *                                       (404 derivado do contrato, ADR 0035) e
 *                                       `test_rls_isolation.py`. Foi verificado:
 *                                       nenhuma rota de cliente ficou sem prova,
 *                                       e esta fatia deliberadamente **não**
 *                                       constrói uma terceira guarda de tenant.
 *   9. `epistemic_status=hypothesis`
 *      como fato ...................... `epistemic_resources` (a marca)
 *
 * **Proibição por recurso e por par explícito, nunca por substring solta.**
 * `DecisionOut.rationale` existe, é legítimo (FDD 032 do Pulse, ADR 0049) e é o
 * que justifica a aba de decisões existir; o proibido é o `rationale` do
 * `PriorityAssessment`. Um banimento da palavra nasceria vermelho em cima de
 * campo correto — é o `.priority` da ADR 0033 outra vez. Pela mesma razão
 * `MeetingOut.has_transcript` (booleano) e `recording_url` (a gravação da
 * reunião do próprio cliente) continuam passando: o proibido é o texto bruto,
 * banido por **nome inteiro**, e `has_transcript` não é `transcript`.
 */
const VISIBILITY = JSON.parse(
  readFileSync(fileURLToPath(new URL("../docs/contracts/one-visibility.json", import.meta.url)), "utf8"),
);

/** A razão escrita pela qual uma rota não é superfície de cliente, ou `null`. */
function excludedReason(path) {
  const rules = VISIBILITY.corpus;
  const named = rules.excluded_paths.find((entry) => entry.path === path);
  if (named) return named.reason;
  const prefixed = rules.excluded_prefixes.find((entry) => path.startsWith(entry.prefix));
  return prefixed ? prefixed.reason : null;
}

const CLIENT_PATHS = Object.keys(document.paths).filter((path) => excludedReason(path) === null);

/** Só o que **sai** de uma rota de cliente, fechado transitivamente por `$ref`. */
function clientResponseSchemas() {
  const names = new Set();
  for (const path of CLIENT_PATHS) {
    for (const operation of Object.values(document.paths[path])) {
      if (!operation || typeof operation !== "object") continue;
      for (const name of referenced(operation.responses ?? {})) names.add(name);
    }
  }
  return withNested(names);
}

const CLIENT_SCHEMAS = [...clientResponseSchemas()].sort();

/**
 * Os tokens de um identificador, em minúsculas — `CamelCase` e `snake_case` na
 * mesma moeda. `LeadOut` → `[lead, out]`; `has_transcript` → `[has,
 * transcript]`; `ShowcaseOut` → `[showcase, out]`, e é por isso que o termo
 * `case` não o alcança.
 */
function tokens(identifier) {
  return identifier
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

/**
 * O identificador **nomeia** o recurso: os tokens do termo aparecem em
 * sequência contígua nos tokens do identificador, com plural tolerado no
 * último. É o que separa "proibir o recurso" de "proibir a palavra".
 */
function namesResource(identifier, term) {
  const have = tokens(identifier);
  const want = tokens(term);
  for (let i = 0; i + want.length <= have.length; i += 1) {
    const fits = want.every((token, j) => {
      const found = have[i + j];
      return found === token || (j === want.length - 1 && found === `${token}s`);
    });
    if (fits) return true;
  }
  return false;
}

const propertiesOf = (definitions, name) => Object.keys(definitions[name]?.properties ?? {});

/** Esquema de resposta de cliente cujo **nome** é um recurso proibido. */
function forbiddenSchemas(names) {
  const offenders = [];
  for (const name of names) {
    for (const { term } of VISIBILITY.forbidden_resources) {
      if (namesResource(name, term)) offenders.push(`${name} (recurso \`${term}\`)`);
    }
  }
  return offenders.sort();
}

/** Campo cujo **nome** nomeia um recurso proibido (`lead_id`, `case_title`…). */
function forbiddenFieldsByResource(definitions, names) {
  const offenders = [];
  for (const name of names) {
    for (const field of propertiesOf(definitions, name)) {
      for (const { term } of VISIBILITY.forbidden_resources) {
        if (namesResource(field, term)) offenders.push(`${name}.${field} (recurso \`${term}\`)`);
      }
    }
  }
  return offenders.sort();
}

/** Campo proibido por **nome inteiro** — nunca por substring. */
function forbiddenFieldsByName(definitions, names) {
  const banned = new Set(VISIBILITY.forbidden_field_names.map((entry) => entry.name));
  const offenders = [];
  for (const name of names) {
    for (const field of propertiesOf(definitions, name)) {
      if (banned.has(field)) offenders.push(`${name}.${field}`);
    }
  }
  return offenders.sort();
}

/** O par explícito (recurso, campo): o recurso pode sair, aquele campo dele não. */
function forbiddenPairs(definitions, names) {
  const offenders = [];
  for (const name of names) {
    for (const pair of VISIBILITY.forbidden_pairs) {
      if (!namesResource(name, pair.resource)) continue;
      if (propertiesOf(definitions, name).includes(pair.field)) {
        offenders.push(`${name}.${pair.field} (par \`${pair.resource}.${pair.field}\`)`);
      }
    }
  }
  return offenders.sort();
}

/**
 * A regra positiva: esquema listado **tem** de declarar a marca.
 *
 * É a forma honesta de escrever hoje a proibição que só morde amanhã. Nem
 * `Finding` nem `Evidence` existem neste repositório (issue #90), e um
 * banimento não serviria: a evidência revisada e a não revisada são a **mesma**
 * entidade, e o que as separa é uma marca. Quando o recurso chegar, tirar a
 * marca da resposta reprova.
 */
function missingMarker(definitions, block) {
  return block.members
    .filter((name) => !propertiesOf(definitions, name).includes(block.field))
    .sort();
}

/** As chaves de um payload de fixture, recursivamente. */
function keysOf(value, found = new Set()) {
  if (Array.isArray(value)) {
    for (const item of value) keysOf(item, found);
  } else if (value && typeof value === "object") {
    for (const [key, nested] of Object.entries(value)) {
      found.add(key);
      keysOf(nested, found);
    }
  }
  return found;
}

test("o corpus de rotas de cliente não está vazio", () => {
  // Fail-closed, e pela terceira vez neste arquivo: o `dependency-review` da
  // ADR 0023 e o `for` sobre oito nomes da ADR 0033 eram verdes por não terem
  // olhado. Um prefixo de exclusão escrito largo demais faria o mesmo aqui.
  assert.ok(CLIENT_PATHS.length > 0, "nenhuma rota sobrou no corpus de cliente");
  assert.ok(CLIENT_SCHEMAS.length > 0, "nenhum esquema de resposta de cliente no corpus");
  assert.ok(VISIBILITY.forbidden_resources.length > 0, "a lista de recursos proibidos está vazia");
  assert.ok(VISIBILITY.forbidden_field_names.length > 0, "a lista de campos proibidos está vazia");
  assert.ok(VISIBILITY.forbidden_pairs.length > 0, "a lista de pares proibidos está vazia");
});

test("nenhum recurso proibido é esquema de resposta de cliente", () => {
  // Proibições 1, 2, 3 e 7: Lead, Qualification, CommercialOpportunity,
  // PipelineStage e Case não têm o que fazer numa resposta do One (§3).
  assert.deepEqual(
    forbiddenSchemas(CLIENT_SCHEMAS),
    [],
    "estes esquemas saem para o cliente e nomeiam um recurso que a §3 do Language Map" +
      " proíbe no One. Tire-os do contrato de cliente — ou, se a decisão mudou, tire a" +
      " linha de `forbidden_resources` com razão escrita e ADR.",
  );
});

test("nenhum campo de cliente nomeia um recurso proibido", () => {
  assert.deepEqual(
    forbiddenFieldsByResource(document.components.schemas, CLIENT_SCHEMAS),
    [],
    "estes campos saem para o cliente e nomeiam um recurso proibido (§3).",
  );
});

test("nenhum campo de cliente é preço, margem, valor de negócio ou transcrição bruta", () => {
  // Proibições 3, 4 e 6. Por **nome inteiro**: `kpi_value` é medição do projeto
  // do cliente e `has_transcript` é o booleano que diz que existe transcrição —
  // os dois continuam legítimos, e é isso que separa esta guarda de um
  // banimento por substring.
  assert.deepEqual(
    forbiddenFieldsByName(document.components.schemas, CLIENT_SCHEMAS),
    [],
    "estes campos saem para o cliente e a §3 do Language Map os proíbe.",
  );
});

test("nenhum par proibido (recurso, campo) sai para o cliente", () => {
  // Proibições 5 e 6: `PriorityAssessment.rationale` e `Service.price`. Os dois
  // recursos podem legitimamente aparecer no One — o primeiro como Opportunity
  // Score (D5), o segundo como nome do produto contratado; o que não pode é
  // aquele campo deles.
  assert.deepEqual(
    forbiddenPairs(document.components.schemas, CLIENT_SCHEMAS),
    [],
    "estes campos saem para o cliente e o par (recurso, campo) está proibido (§3).",
  );
});

test("o par proibido não alcança um campo de mesmo nome em outro recurso", () => {
  // A prova de que a proibição **não** é por substring, e ela é sobre o campo
  // que existe hoje: `DecisionOut.rationale` é o racional da decisão publicada.
  assert.ok(
    document.components.schemas.DecisionOut.properties.rationale,
    "DecisionOut.rationale sumiu do contrato — reveja esta asserção e o artefato",
  );
  assert.deepEqual(forbiddenPairs(document.components.schemas, ["DecisionOut"]), []);
  // E o mesmo campo, no recurso proibido, reprova.
  const synthetic = { PriorityAssessmentOut: { properties: { rationale: {}, score: {} } } };
  assert.deepEqual(forbiddenPairs(synthetic, ["PriorityAssessmentOut"]), [
    "PriorityAssessmentOut.rationale (par `PriorityAssessment.rationale`)",
  ]);
});

test("esquema com marca epistêmica declarada tem de declarar o campo", () => {
  // Proibição 9. A lista de membros deixou de ser vazia na ADR 0086: `FindingOut`
  // existe, atravessa e declara `epistemic_status` — então esta asserção percorre
  // um ramo real. A amostra sintética **fica**, e não era um remendo para lista
  // vazia: é o par que prova que a regra é estreita (o esquema sem o campo reprova,
  // o mesmo esquema com o campo passa). Sem ela, um casador quebrado passaria verde
  // por cima do membro de verdade.
  const block = VISIBILITY.epistemic_resources;
  assert.ok(block.members.length > 0, "a lista de membros voltou a ficar vazia");
  assert.deepEqual(missingMarker(document.components.schemas, block), []);

  const synthetic = { FindingOut: { properties: { id: {}, text: {} } } };
  const armed = { field: block.field, members: ["FindingOut"] };
  assert.deepEqual(missingMarker(synthetic, armed), ["FindingOut"]);
  synthetic.FindingOut.properties[block.field] = {};
  assert.deepEqual(missingMarker(synthetic, armed), []);
});

test("esquema de evidência declarado tem de declarar a marca de revisão", () => {
  // Proibição 4, a metade que não é banimento: Evidence revisada e não revisada
  // são a mesma entidade, e o que as separa é a marca. Mesma amostra sintética,
  // pelo mesmo motivo.
  const block = VISIBILITY.reviewed_resources;
  assert.deepEqual(missingMarker(document.components.schemas, block), []);

  const synthetic = { EvidenceOut: { properties: { id: {}, excerpt: {} } } };
  const armed = { field: block.field, members: ["EvidenceOut"] };
  assert.deepEqual(missingMarker(synthetic, armed), ["EvidenceOut"]);
  synthetic.EvidenceOut.properties[block.field] = {};
  assert.deepEqual(missingMarker(synthetic, armed), []);
});

/**
 * Os esquemas que a exclusão de `reviewed_resources` protege, e o que ela promete:
 * que eles **não** declaram marca de publicação nenhuma.
 *
 * É a metade que faz a divergência ser verificável em vez de escrita. `members` está
 * vazia porque o produtor não emite a marca — ele filtra por `published_at` antes de
 * montar o payload, e a presença no array é a prova (pulse#106, ADR 0086). Uma lista
 * vazia sem esta asserção seria exatamente o que a ADR 0033 nomeou: uma regra que
 * segue verde porque nada a consulta.
 */
function declaredMarks(definitions, block) {
  const marks = new Set(block.publication_marks);
  const offenders = [];
  for (const entry of block.excluded ?? []) {
    for (const field of propertiesOf(definitions, entry.schema)) {
      if (marks.has(field)) offenders.push(`${entry.schema}.${field}`);
    }
  }
  return offenders.sort();
}

test("o esquema excluído da marca de revisão não declara marca nenhuma", () => {
  const block = VISIBILITY.reviewed_resources;

  // Fail-closed nos dois sentidos, na forma do `test_the_exclusions_are_still_real`:
  // uma exclusão que aponta para esquema que não sai mais é linha órfã, e o esquema
  // excluído tem de existir para a asserção estar olhando alguma coisa.
  const orphans = (block.excluded ?? [])
    .map((entry) => entry.schema)
    .filter((name) => !CLIENT_SCHEMAS.includes(name));
  assert.deepEqual(
    orphans,
    [],
    `estas exclusões apontam para esquema que não sai para o cliente: ${orphans}. Apague a linha.`,
  );

  assert.deepEqual(
    declaredMarks(document.components.schemas, block),
    [],
    "este esquema está excluído da exigência de marca de revisão porque o produtor não" +
      " emite marca nenhuma — e passou a declarar uma. A decisão do outro lado mudou:" +
      " tire a linha de `excluded`, ponha o esquema em `members` e ajuste `field` para o" +
      " nome que a origem usa (ADR 0086).",
  );

  // E o par que prova a estreiteza: o mesmo esquema, com a marca, reprova.
  const synthetic = { EvidenceOut: { properties: { id: {}, published_at: {} } } };
  assert.deepEqual(declaredMarks(synthetic, block), ["EvidenceOut.published_at"]);
});

test("a lista de marcas não guarda esquema que saiu do contrato", () => {
  // Mesma regra do `NOT_CONSUMED`: a linha some quando o motivo some. Sem isto,
  // um `FindingOut` removido deixaria a exigência apontando para o vazio — e
  // uma exigência que não alcança nada passa verde para sempre.
  const orphans = [VISIBILITY.epistemic_resources, VISIBILITY.reviewed_resources]
    .flatMap((block) => block.members)
    .filter((name) => !CLIENT_SCHEMAS.includes(name));
  assert.deepEqual(orphans, [], `estes esquemas estão listados e não saem para o cliente: ${orphans}`);
});

test("nenhuma rota de cliente aceita o cliente nomear uma Account", () => {
  // Proibição 8, a metade que um contrato consegue afirmar. A outra — "token de
  // uma Account nunca lê linha de outra" — já tem duas guardas
  // (`test_authorization.py`, derivada do contrato, e `test_rls_isolation.py`),
  // e esta fatia deliberadamente não constrói uma terceira. O que sobra é a
  // superfície: onde a organização é parâmetro, a rota é de admin — e admin está
  // fora do corpus. É a regra 1 do `AGENTS.md` na forma em que um esquema
  // consegue dizê-la.
  const banned = new Set(VISIBILITY.account_identifier_inputs.forbidden_parameter_names);
  const offenders = [];
  for (const path of CLIENT_PATHS) {
    for (const [method, operation] of Object.entries(document.paths[path])) {
      if (!operation || typeof operation !== "object") continue;
      for (const parameter of operation.parameters ?? []) {
        if (banned.has(parameter.name)) offenders.push(`${method.toUpperCase()} ${path} ${parameter.name}`);
      }
      for (const { schema } of requestBodySchemas(operation)) {
        for (const key of Object.keys(schema?.properties ?? {})) {
          if (banned.has(key)) offenders.push(`${method.toUpperCase()} ${path} ${key}`);
        }
      }
    }
  }
  assert.deepEqual(
    offenders.sort(),
    [],
    "estas rotas de cliente aceitam um identificador de Account vindo do cliente." +
      " O vínculo é resolvido no servidor a partir do token, nunca nomeado por quem chama.",
  );
});

test("as fixtures do BFF não fabricam nenhuma das nove proibições", () => {
  // A fixture é uma API de mentira, e uma API de mentira é livre para mentir —
  // é o motivo de este arquivo existir (ADR 0020). O `ajv` acima já a casa com o
  // contrato, então uma chave proibida só entraria por um esquema proibido; esta
  // asserção é a que sobra caso o contrato mude junto, e é barata.
  const banned = new Set(VISIBILITY.forbidden_field_names.map((entry) => entry.name));
  const offenders = [];
  for (const [name, payload] of [["ME", ME], ["DASHBOARD", DASHBOARD], ["SEARCH", SEARCH]]) {
    for (const key of keysOf(payload)) {
      if (banned.has(key)) offenders.push(`${name}.${key}`);
      for (const { term } of VISIBILITY.forbidden_resources) {
        if (namesResource(key, term)) offenders.push(`${name}.${key} (recurso \`${term}\`)`);
      }
    }
  }
  assert.deepEqual(offenders.sort(), [], "as fixtures trazem chaves que a §3 proíbe no One.");
});
