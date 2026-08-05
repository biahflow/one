import { expect, test, type Page } from "@playwright/test";

/**
 * O caminho que nenhum outro teste alcança: navegador → Keycloak → callback do
 * BFF → dashboard com dados reais. Os usuários vêm do realm versionado e do
 * seed (`apps/api/src/portal_api/seed.py`), que compartilham o mesmo `sub`.
 */

const CLIENT = { username: "marina.farias", password: "portal_local_only", firstName: "Marina" };
const STAFF = { username: "helena.dias", password: "portal_local_only", firstName: "Helena" };

async function signIn(page: Page, user: { username: string; password: string }) {
  // Limpa **aqui**, coladinho no `goto`. Limpar no chamador deixa uma janela: a
  // navegação anterior pode ter uma requisição em voo que reescreve o cookie de
  // sessão logo depois, e aí `/login` redireciona para `/` (ele faz isso quando
  // há sessão) e o botão nunca aparece. O sintoma é um timeout esperando um
  // botão numa página que é o dashboard.
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByRole("button", { name: /Entrar com SSO/ }).click();

  // Tela do Keycloak, no endereço público — se o `iss` estivesse errado, o
  // navegador nem chegaria aqui.
  await page.waitForURL(/\/realms\/portal-local\/protocol\/openid-connect\/auth/);
  await page.locator("#username").fill(user.username);
  await page.locator("#password").fill(user.password);
  await page.locator("#kc-login").click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

test("mantém o portal fechado para quem não entrou", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: /Entrar com SSO/ })).toBeVisible();
});

test("cliente entra e vê o próprio projeto, com o nome vindo do token", async ({ page }) => {
  await signIn(page, CLIENT);

  await expect(page).toHaveURL(/localhost:3000\/$/);
  await expect(page.getByText(`Bom dia, ${CLIENT.firstName}.`)).toBeVisible();
  // Dados do seed, não do fallback de demonstração — que já nem existe.
  await expect(page.getByText("Automação Financeira").first()).toBeVisible();
  await expect(page.getByText("Aprovar fluxo de exceções").first()).toBeVisible();
});

test("sair encerra a sessão e o F5 não devolve o dashboard", async ({ page }) => {
  await signIn(page, CLIENT);

  await page.getByRole("button", { name: "Abrir menu do usuário" }).first().click();
  await page.getByRole("button", { name: /Sair/ }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});

test("interno enxerga o projeto pela membership org-wide", async ({ page }) => {
  await signIn(page, STAFF);

  await expect(page.getByText(`Bom dia, ${STAFF.firstName}.`)).toBeVisible();
  await expect(page.getByText("Automação Financeira").first()).toBeVisible();
});
