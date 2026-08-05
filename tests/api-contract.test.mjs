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

import { DASHBOARD, ME } from "./fixtures/dashboard.mjs";

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
  for (const name of ["MeOut", "MyDashboardOut", "ResultsOut", "NotificationsOut"]) {
    assert.ok(schemas[name], `o contrato não define ${name}`);
  }
});

test("a resposta de /api/v1/me na fixture é a que a API declara", () => {
  check("MeOut", ME);
});

test("a resposta de /api/v1/me/dashboard na fixture é a que a API declara", () => {
  check("MyDashboardOut", DASHBOARD);
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
