import { expect, test, type Page } from "@playwright/test";

import { STACK_REASON, serviceIsUp, stackIsMissing } from "./stack";

/**
 * Prioridade e filtro na aba onde o cliente decide o que fazer (ADR 0029).
 *
 * O que só este nível prova: que o dado atravessa a corrente inteira até um
 * navegador de verdade. A prioridade é coluna no Postgres desde a Fase 1, o
 * sync a projeta, o contrato a declara — e o mapeamento do BFF a descartava,
 * de modo que toda pendência aparecia igual. `api-contract.test.mjs` pega o
 * descarte no código-fonte; aqui se vê o selo e o filtro funcionando com a
 * sessão real e o read model semeado.
 */

const CLIENT = { username: "marina.farias", password: "portal_local_only" };

async function signIn(page: Page, user: { username: string; password: string }) {
  // Limpa coladinho no `goto`, pelo motivo longo em `login.spec.ts`.
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByRole("button", { name: /Entrar com SSO/ }).click();
  await page.waitForURL(/\/realms\/portal-local\/protocol\/openid-connect\/auth/);
  await page.locator("#username").fill(user.username);
  await page.locator("#password").fill(user.password);
  await page.locator("#kc-login").click();
  await page.waitForURL(
    (url) => !url.pathname.startsWith("/login") && !url.pathname.startsWith("/realms"),
  );
}

test.beforeEach(() => {
  test.skip(stackIsMissing(serviceIsUp("api")), STACK_REASON);
});

test("o filtro de prioridade encolhe a lista e o caminho de volta existe", async ({ page }) => {
  await signIn(page, CLIENT);
  // Sem `exact`: o item da navegação carrega a contagem de abertas num `<em>`,
  // então o nome acessível é "Pendências 3", não "Pendências".
  await page.getByRole("button", { name: /^Pendências/ }).click();
  await expect(page.getByRole("heading", { name: "Pendências do projeto" })).toBeVisible();

  // Escopado ao painel de abertas: a aba tem dois, e o de resolvidas também usa
  // `.pending-row` — sem o escopo, a contagem inclui o que o filtro não toca.
  const rows = page.locator(".pending-panel .pending-row");
  const total = await rows.count();
  expect(total).toBeGreaterThan(0);

  // O chip diz quantas são antes de clicar — sem o número, escolher é adivinhar.
  const alta = page.getByRole("button", { name: /^Alta/ });
  const declared = Number((await alta.textContent())?.match(/\d+/)?.[0] ?? "-1");
  await alta.click();

  await expect(rows).toHaveCount(declared);
  expect(declared).toBeLessThan(total);

  // "Todas" é sempre a primeira opção: um filtro sem volta esconde dado e
  // parece lista vazia.
  await page.getByRole("button", { name: /^Todas/ }).click();
  await expect(rows).toHaveCount(total);
});

test("a pendência aberta pela IA leva de volta à pergunta que a gerou", async ({ page }) => {
  await signIn(page, CLIENT);
  await page.getByRole("button", { name: /^Pendências/ }).click();

  // As do Biahflow não vieram de conversa nenhuma; a da IA veio, e o FK que diz
  // qual turno era lido só como booleano até a ADR 0031.
  const row = page.locator(".pending-row", { hasText: "aberta pela IA" }).first();
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Ver a pergunta" }).click();

  // O chat abre e o turno apontado é o que fica em destaque — não o último.
  await expect(page.locator(".chat-panel")).toBeVisible();
  await expect(page.locator(".message--focused")).toHaveCount(1);
});
