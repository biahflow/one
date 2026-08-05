/**
 * O portão de dependências, testado no que ele tem de perigoso (ADR 0023).
 *
 * Não precisa de build nem de rede — como `api-contract.test.mjs`, e ao
 * contrário de `rendered-html.test.mjs`. O que se exercita é o núcleo puro de
 * `scripts/audit.mjs`, com o dia entrando por parâmetro.
 *
 * O que estes testes existem para impedir é **um mecanismo de exceção que vira
 * passe geral**. Foi exatamente assim que as três asserções que dão sentido ao
 * backup passaram semanas pulando em silêncio (ADR 0020): ninguém testa o que
 * decide não testar. Um portão cuja lista de exceções nunca foi exercitada é
 * indistinguível, no verde do CI, de um portão desligado.
 *
 * As duas amostras de relatório são **reais**, recortadas da saída das
 * ferramentas contra os pins que este repositório tinha antes desta fatia. Uma
 * amostra inventada testaria o parser contra a minha ideia do formato, que é a
 * mesma classe de erro que a fixture do web tinha antes da ADR 0020.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { evaluate, normalizeNpm, normalizePip } from "../scripts/audit.mjs";

const HOJE = "2026-08-05";

/** Recorte real de `npm audit --json` com `next@16.2.6` (3 pacotes, 14 avisos). */
const NPM_REPORT = {
  vulnerabilities: {
    next: {
      name: "next",
      severity: "high",
      via: [
        {
          source: 1124170,
          name: "next",
          title: "Next.js: Middleware / Proxy bypass in App Router applications using Turbopack and single locale",
          url: "https://github.com/advisories/GHSA-6gpp-xcg3-4w24",
          severity: "high",
        },
        {
          source: 1124171,
          name: "next",
          title: "Next.js: Denial of Service in App Router using Server Actions",
          url: "https://github.com/advisories/GHSA-m99w-x7hq-7vfj",
          severity: "high",
        },
        // As duas strings são o motivo de `next` aparecer por causa de outros
        // pacotes; o aviso em si mora na entrada deles.
        "postcss",
        "sharp",
      ],
      fixAvailable: { name: "next", version: "16.3.0", isSemVerMajor: false },
    },
    postcss: {
      name: "postcss",
      severity: "high",
      via: [
        {
          source: 1124288,
          name: "postcss",
          title: "PostCSS: Path Traversal in Previous Source Map Auto-Loading (sourceMappingURL)",
          url: "https://github.com/advisories/GHSA-r28c-9q8g-f849",
          severity: "high",
        },
      ],
      fixAvailable: { name: "next", version: "16.3.0", isSemVerMajor: false },
    },
  },
};

/** Recorte real de `pip-audit --format json` com `python-multipart==0.0.20`. */
const PIP_REPORT = {
  dependencies: [
    { name: "fastapi", version: "0.115.12", vulns: [] },
    {
      name: "python-multipart",
      version: "0.0.20",
      vulns: [
        {
          id: "PYSEC-2026-1852",
          fix_versions: ["0.0.22"],
          aliases: ["GHSA-wp53-j4wj-2cfg", "CVE-2026-24486"],
          description: "Path Traversal com UPLOAD_DIR e UPLOAD_KEEP_FILENAME=True.",
        },
        // O mesmo id repetido: o pip-audit emite uma vez por fonte consultada.
        {
          id: "PYSEC-2026-1852",
          fix_versions: ["0.0.22"],
          aliases: ["CVE-2026-24486"],
          description: "Path Traversal com UPLOAD_DIR e UPLOAD_KEEP_FILENAME=True.",
        },
      ],
    },
  ],
};

test("lê o relatório do npm sem contar duas vezes o que é transitivo", () => {
  const findings = normalizeNpm(NPM_REPORT);

  // Quatro entradas em `via` do `next`, mas duas são strings apontando para
  // outros pacotes — contá-las produziria o mesmo GHSA sob dois nomes.
  assert.equal(findings.length, 3);
  assert.deepEqual(
    findings.map((f) => f.id),
    ["GHSA-6gpp-xcg3-4w24", "GHSA-m99w-x7hq-7vfj", "GHSA-r28c-9q8g-f849"],
  );
  assert.equal(findings[0].package, "next");
  assert.deepEqual(findings[2].fixedIn, ["next@16.3.0"]);
});

test("lê o relatório do pip-audit deduplicando o mesmo aviso", () => {
  const findings = normalizePip(PIP_REPORT);

  assert.equal(findings.length, 1);
  assert.equal(findings[0].id, "PYSEC-2026-1852");
  assert.equal(findings[0].package, "python-multipart");
  assert.ok(findings[0].aliases.includes("CVE-2026-24486"));
});

test("um aviso sem entrada no registro reprova", () => {
  const findings = normalizeNpm(NPM_REPORT);

  const resultado = evaluate(findings, [], HOJE);

  assert.equal(resultado.ok, false);
  assert.equal(resultado.blocking.length, 3);
  assert.match(resultado.blocking[0].why, /sem entrada/);
});

test("um aviso aceito com prazo no futuro passa", () => {
  const findings = normalizePip(PIP_REPORT);
  const registro = [
    {
      id: "PYSEC-2026-1852",
      package: "python-multipart",
      reason: "Só afeta UPLOAD_DIR + UPLOAD_KEEP_FILENAME, que o portal não usa.",
      review_by: "2026-12-31",
    },
  ];

  const resultado = evaluate(findings, registro, HOJE);

  assert.equal(resultado.ok, true);
  assert.equal(resultado.accepted.length, 1);
  assert.equal(resultado.blocking.length, 0);
});

test("o alias serve para aceitar, porque é por ele que o aviso é citado", () => {
  // Quem escreve a exceção lendo um CVE não deveria precisar descobrir qual dos
  // nomes o pip-audit escolheu naquele dia.
  const findings = normalizePip(PIP_REPORT);
  const registro = [
    {
      id: "CVE-2026-24486",
      package: "python-multipart",
      reason: "Mesmo aviso, citado pelo CVE.",
      review_by: "2026-12-31",
    },
  ];

  assert.equal(evaluate(findings, registro, HOJE).ok, true);
});

test("uma exceção vencida reprova — risco aceito tem prazo", () => {
  const findings = normalizePip(PIP_REPORT);
  const registro = [
    {
      id: "PYSEC-2026-1852",
      package: "python-multipart",
      reason: "Aceito na época, e ninguém voltou.",
      review_by: "2026-08-04",
    },
  ];

  const resultado = evaluate(findings, registro, HOJE);

  assert.equal(resultado.ok, false);
  assert.equal(resultado.accepted.length, 0);
  assert.match(resultado.blocking[0].why, /venceu em 2026-08-04/);
});

test("uma entrada que não casa com aviso nenhum reprova, para o arquivo não apodrecer", () => {
  const registro = [
    {
      id: "GHSA-6gpp-xcg3-4w24",
      package: "next",
      reason: "Corrigido no bump para 16.3.0 — a linha ficou para trás.",
      review_by: "2027-01-01",
    },
  ];

  const resultado = evaluate([], registro, HOJE);

  assert.equal(resultado.ok, false);
  assert.equal(resultado.stale.length, 1);
  assert.equal(resultado.stale[0].id, "GHSA-6gpp-xcg3-4w24");
});

test("a exceção é por pacote, não só por id", () => {
  // Um id certo com o pacote errado nunca valeu para o aviso que quem escreveu
  // achava estar aceitando. Reprovar dos dois lados — o aviso segue bloqueando e
  // a entrada aparece como obsoleta — é o que faz o engano ficar visível em vez
  // de virar uma exceção que não protege nada.
  const findings = normalizePip(PIP_REPORT);
  const registro = [
    {
      id: "PYSEC-2026-1852",
      package: "starlette",
      reason: "Pacote errado.",
      review_by: "2026-12-31",
    },
  ];

  const resultado = evaluate(findings, registro, HOJE);

  assert.equal(resultado.ok, false);
  assert.equal(resultado.blocking.length, 1);
  assert.equal(resultado.stale.length, 1);
});

test("o registro versionado é JSON válido e começa vazio", async () => {
  const { readFile } = await import("node:fs/promises");
  const { REGISTRY_PATH } = await import("../scripts/audit.mjs");
  const registro = JSON.parse(await readFile(REGISTRY_PATH, "utf8"));

  assert.ok(Array.isArray(registro.accepted));
  // Não é uma exigência de que fique vazio para sempre — é a afirmação de que
  // esta fatia consertou em vez de aceitar. Quando alguém acrescentar uma
  // entrada, este teste vira a conferência do formato.
  for (const entry of registro.accepted) {
    assert.ok(entry.id && entry.package && entry.reason && entry.review_by);
    assert.match(entry.review_by, /^\d{4}-\d{2}-\d{2}$/);
  }
});
