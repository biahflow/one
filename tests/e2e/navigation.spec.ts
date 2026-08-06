import { expect, test, type Page } from "@playwright/test";

import { STACK_REASON, serviceIsUp, stackIsMissing } from "./stack";

/**
 * Os dois atalhos da Visão geral, no navegador (Fase 6, ADR 0026).
 *
 * O que só este nível prova é modesto e é exatamente o ponto: que **acontece
 * alguma coisa** ao clicar. Até esta fatia "Ver cronograma" e "Ver todas as
 * pendências" eram `<button>` sem `onClick`, apontando para abas que existiam
 * desde a Fase 2 — e nenhuma camada de teste os alcançava, porque um botão
 * inerte renderiza HTML idêntico a um que funciona.
 *
 * A guarda de `inertButtons()` em `tests/rendered-html.test.mjs` impede que
 * eles voltem a nascer mortos; ela não sabe **para onde** levam. Este spec sabe,
 * e é a razão de ele existir apesar de a fatia ser sobretudo remoção.
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

test("os atalhos da Visão geral levam às abas que prometem", async ({ page }) => {
  await signIn(page, CLIENT);

  await page.getByRole("button", { name: "Ver cronograma" }).click();
  await expect(page.getByRole("heading", { name: "Cronograma do projeto" })).toBeVisible();

  // Voltar pela navegação lateral, para o segundo clique partir da Visão geral
  // como parte de quem usa a tela.
  await page.getByRole("button", { name: "Visão geral", exact: true }).click();

  await page.getByRole("button", { name: "Ver todas as pendências" }).click();
  await expect(page.getByRole("heading", { name: "Pendências do projeto" })).toBeVisible();
});
