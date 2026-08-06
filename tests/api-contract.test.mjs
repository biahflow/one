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
import { readFileSync } from "node:fs";
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
 */
const PAGE = readFileSync(fileURLToPath(new URL("../app/page.tsx", import.meta.url)), "utf8");

/**
 * Campos que a tela deliberadamente não usa, na forma `Esquema.campo`, com o
 * motivo escrito. **Está vazio, e a meta é que continue** — na primeira
 * execução a guarda acusou um campo só, `PendingOut.priority`, e ele virou
 * mapeamento em vez de exceção. Uma allowlist que cresce é o contrato dizendo
 * que entrega o que ninguém pediu.
 */
const NOT_CONSUMED = {};

for (const schema of [
  "PendingOut",
  "MilestoneOut",
  "DashboardDocumentOut",
  "MeetingOut",
  "NextMeetingOut",
  "RoiOut",
  "ProjectHealthOut",
  "DigitalEmployeeOut",
]) {
  test(`o BFF consome todo campo que ${schema} entrega`, () => {
    const properties = document.components.schemas[schema]?.properties;
    assert.ok(properties, `o contrato não define ${schema}`);

    const dropped = Object.keys(properties).filter(
      (key) => !NOT_CONSUMED[`${schema}.${key}`] && !PAGE.includes(`.${key}`),
    );

    assert.deepEqual(
      dropped,
      [],
      `app/page.tsx recebe estes campos de ${schema} e não os lê: ${dropped.join(", ")}.` +
        " Mapeie-os, ou tire-os do contrato — um campo que a tela não usa é uma" +
        " pergunta para a API, não para o BFF (ADR 0029).",
    );
  });
}
