import { expect, test } from "@playwright/test";

import { ADMIN as STAFF, CLIENTE as CLIENT, PROJETO_DO_SEED, projetoDoSeed, signIn } from "./atores";

/**
 * O caminho que nenhum outro teste alcança: navegador → Keycloak → callback do
 * BFF → dashboard com dados reais. Os usuários vêm do realm versionado e do
 * seed (`apps/api/src/portal_api/seed.py`), que compartilham o mesmo `sub`.
 */

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
  // Aqui a afirmação sobre o projeto **padrão** continua valendo, e é a única
  // que continua: Marina tem vínculo direto, então `default_project` a resolve
  // pela membership dela e não por recência. É o caso determinístico.
  await expect(page.getByText(PROJETO_DO_SEED).first()).toBeVisible();
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
  // O que a membership organizacional concede é **alcance**, não um projeto
  // específico: ela vale para todo projeto da organização, inclusive os que
  // ainda não existem. Este teste afirmava que Automação Financeira era o
  // projeto *padrão* de Helena — o que é verdade num banco com uma organização
  // só e deixa de ser em qualquer outro, porque `default_project` desempata por
  // `created_at DESC`. Reprovava por acúmulo de dado local, nunca por defeito.
  //
  // A pergunta que o nome do teste faz é se ela chega ao projeto sem ninguém a
  // ter posto nele; é isso que se afirma agora, e é o que a Marina do teste
  // acima não consegue fazer.
  await signIn(page, STAFF);
  await expect(page.getByText(`Bom dia, ${STAFF.firstName}.`)).toBeVisible();

  const projeto = await projetoDoSeed(page);
  await page.goto(`/?project=${projeto}`);

  await expect(page.getByText(PROJETO_DO_SEED).first()).toBeVisible();
});
