import { expect, test, type Page } from "@playwright/test";

import { STACK_REASON, serviceIsUp, stackIsMissing } from "./stack";

/**
 * A lista de clientes travados no funil de onboarding (Fase 7, RFC 001 passo 3, ADR 0040).
 *
 * O que só este nível prova: que a leitura do funil tem **caller**, e que o fan-out sobre as
 * organizações administradas chega à tela. A cadeia inteira — `GET /admin/organizations`,
 * depois uma leitura por organização, depois a ordenação por gravidade — só existe aqui;
 * abaixo dela, `test_onboarding.py` prova a regra e `api-contract.test.mjs` prova que todo
 * campo entregue é lido, mas nenhum dos dois percorre o caminho do navegador. Se a
 * ordenação descartasse linhas, os dois continuariam verdes.
 *
 * **A asserção que carrega o spec é a separação**, não a contagem: a FDD 020 exige que
 * "travou no cliente" e "travou em nós" nunca sejam somados, e é isso que se confere —
 * dois painéis distintos, dois números distintos, e nenhum total em lugar nenhum.
 */

const ADMIN = { username: "helena.dias", password: "portal_local_only" };
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

test("a lista do funil é alcançada a partir do /admin", async ({ page }) => {
  await signIn(page, ADMIN);

  await page.goto("/admin");
  await page.getByRole("link", { name: /Contas travadas no funil/ }).click();

  await expect(page).toHaveURL(/\/admin\/funnel/);
  await expect(page.getByRole("heading", { name: "Contas travadas" })).toBeVisible();
});

test("os dois lados são painéis separados, e nunca uma soma", async ({ page }) => {
  await signIn(page, ADMIN);
  await page.goto("/admin/funnel");

  // Os dois painéis existem por si, com títulos que dizem de quem é a vez.
  await expect(page.getByRole("heading", { name: /Ele tem tudo e não veio/ })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /Falta alguma coisa nossa/ }),
  ).toBeVisible();

  // E as três contagens são independentes. O que se afirma aqui não é o valor de nenhuma
  // delas — que depende do que o seed produziu — e sim que são **três**, separadas: um
  // total apareceria como um quarto número, e a FDD 020 o proíbe.
  const contadores = page.locator(".admin-head .field-row");
  await expect(contadores).toHaveCount(3);
  await expect(contadores.filter({ hasText: "Travados no cliente" })).toHaveCount(1);
  await expect(contadores.filter({ hasText: "Travados em nós" })).toHaveCount(1);
  await expect(contadores.filter({ hasText: "Sem base para medir" })).toHaveCount(1);
});

test("o cliente não alcança a lista do funil", async ({ page }) => {
  // O contraponto da regra 6 no navegador: a API responde 404 a quem não é
  // `internal_admin`, e a tela não tem como mostrar o que não recebeu. Aqui isso importa
  // mais que de costume — a resposta descreve o comportamento de uma pessoa nomeada, que
  // é a classe mais sensível da `data-classification.md`.
  await signIn(page, CLIENT);

  await page.goto("/admin/funnel");

  await expect(page.getByRole("heading", { name: "Contas travadas" })).toHaveCount(0);
});
