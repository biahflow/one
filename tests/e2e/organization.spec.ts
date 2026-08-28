import { expect, test, type Page } from "@playwright/test";

import { STACK_REASON, serviceIsUp, stackIsMissing } from "./stack";

/**
 * A tela das rotas cujo escopo é a organização (Fase 6, ADR 0027).
 *
 * O que só este nível prova: que as seis rotas de organização têm **caller**.
 * Elas existiam completas desde as ADRs 0017 e 0022 e eram chaveadas por um
 * `organization_id` que nenhuma resposta da API devolvia — não havia como
 * chamá-las sem consultar o Postgres à mão. Aqui um navegador com sessão real
 * chega até elas passando por `GET /api/v1/admin/organizations`, que é a peça
 * que faltava.
 *
 * **Nenhum expurgo é pedido de verdade, e não é timidez:** o worker cumpriria,
 * o tenant semeado sumiria e todos os outros specs cairiam junto. O que se
 * afirma é a recusa da confirmação errada — que é a asserção interessante de
 * qualquer forma, porque o 422 do `confirm_slug` é a única negação do portal
 * que não é 404.
 */

const ADMIN = { username: "helena.dias", password: "portal_local_only" };

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

test("a administração alcança a organização a partir do /admin", async ({ page }) => {
  await signIn(page, ADMIN);

  await page.goto("/admin");
  await page
    .getByRole("link", { name: /Retenção, gasto de IA e apagamento/ })
    .click();

  await expect(page).toHaveURL(/\/admin\/organization/);
  await expect(
    page.getByRole("heading", { name: /Por quanto tempo os dados ficam/ }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: /Teto mensal e consumo/ })).toBeVisible();
});

test("um prazo escolhido deixa de ser herdado, e apagá-lo devolve o padrão", async ({
  page,
}) => {
  await signIn(page, ADMIN);
  await page.goto("/admin/organization");

  // O rótulo carrega a distinção que `RetentionPolicyOut` existe para permitir:
  // sem ela, salvar o formulário fixaria o padrão sem querer.
  const field = page.getByLabel(/^Avisos —/);
  await expect(page.getByText(/Avisos —.*\(herdado\)/)).toBeVisible();

  await field.fill("90");
  await page.getByRole("button", { name: /Salvar prazos/ }).click();
  await expect(page.getByText("Prazos atualizados.")).toBeVisible();
  await expect(page.getByText(/Avisos — vale hoje: 90 dias \(escolhido\)/)).toBeVisible();

  // Vazio é "usa o padrão", nunca "guarda para sempre" — e o caminho de volta
  // precisa existir, senão escolher um prazo seria irreversível pela tela.
  await page.getByLabel(/^Avisos —/).fill("");
  await page.getByRole("button", { name: /Salvar prazos/ }).click();
  await expect(page.getByText("Prazos atualizados.")).toBeVisible();
  await expect(page.getByText(/Avisos —.*\(herdado\)/)).toBeVisible();
});

test("o apagamento recusa a confirmação errada e não registra pedido", async ({ page }) => {
  await signIn(page, ADMIN);
  await page.goto("/admin/organization");

  await page.getByLabel(/Por que o apagamento foi pedido/).fill("teste de confirmação");
  await page.getByLabel(/para confirmar/).fill("nao-e-esta-organizacao");
  await page.getByRole("button", { name: /Pedir apagamento/ }).click();

  await expect(
    page.getByText(/O identificador digitado não é o desta organização/),
  ).toBeVisible();
  // E o registro continua sem o pedido: a recusa acontece antes da gravação.
  await expect(page.getByText("Nenhum apagamento pedido até hoje.")).toBeVisible();
});
