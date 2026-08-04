import { execFileSync } from "node:child_process";

import { expect, test, type Page } from "@playwright/test";

/**
 * A conversa que sobrevive ao navegador (Fase 4, ADR 0015).
 *
 * O que só este nível prova: a resposta não vive no estado do React. O cliente
 * pergunta, **recarrega a página** — e o histórico volta do Postgres, pela mesma
 * credencial que o gravou, com as citações que a resposta mostrou na hora.
 *
 * O F5 é o teste. Sem ele, um `useState` que nunca foi limpo passaria igual.
 */

const CLIENT = { username: "marina.farias", password: "portal_local_only" };
// Membro interno do mesmo projeto — quem *mais* teria motivo para ver a conversa
// do cliente, e justamente por isso o caso que vale testar.
const INTERNAL = { username: "rafael.costa", password: "portal_local_only" };

function dockerAvailable(): boolean {
  try {
    execFileSync("docker", ["compose", "ps", "-q", "api"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

async function signIn(page: Page, user: { username: string; password: string }) {
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

async function ask(page: Page, question: string) {
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();
  await page.getByLabel("Pergunta para IA").fill(question);
  await page.getByRole("button", { name: "Enviar pergunta" }).click();
}

test.beforeEach(async ({ context }) => {
  test.skip(!dockerAvailable(), "Precisa da stack local no ar (docker compose up)");
  // O Keycloak mantém sessão SSO no navegador: sem limpar, `signIn` nem chega ao
  // formulário e o teste roda como quem entrou no spec anterior. Aqui isso seria
  // fatal — a conversa tem dono, e o dono errado invalida as duas asserções.
  await context.clearCookies();
});

test("a conversa volta depois do reload, com as citações e o feedback", async ({ page }) => {
  const question = `Qual é o status do projeto? (${Date.now().toString(36)})`;

  await signIn(page, CLIENT);
  await ask(page, question);

  // A resposta é fundamentada e cita o read model — o mesmo contrato da Fase 3.
  const firstSource = page.locator(".message-sources span").first();
  await expect(firstSource).toBeVisible({ timeout: 30_000 });
  const citation = (await firstSource.innerText()).trim();
  expect(citation.length).toBeGreaterThan(0);

  // O F5: nada do que está na tela agora veio do estado do navegador.
  await page.reload();
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();

  const messages = page.locator(".chat-messages");
  await expect(messages).toContainText(question, { timeout: 30_000 });
  // A mesma citação, remontada das partes gravadas — não uma nova consulta.
  await expect(page.locator(".message-sources span").first()).toHaveText(citation);

  // E a avaliação também é registro: marcada aqui, ainda marcada depois de outro F5.
  await page.getByRole("button", { name: "Esta resposta não ajudou" }).first().click();
  const rated = page.locator(".message-feedback button.is-active").first();
  await expect(rated).toBeVisible();

  await page.reload();
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();
  await expect(page.locator(".message-feedback button.is-active")).toHaveCount(1, {
    timeout: 30_000,
  });
});

test("a conversa do cliente não aparece nem para o time interno do projeto", async ({
  page,
  context,
}) => {
  const secret = `pergunta-privada-${Date.now().toString(36)}`;

  await signIn(page, CLIENT);
  await ask(page, `Qual é o status do projeto? ${secret}`);
  await expect(page.locator(".chat-messages")).toContainText(secret, { timeout: 30_000 });

  await context.clearCookies();
  await signIn(page, INTERNAL);
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();

  // A policy soma o dono ao tenant: o mesmo projeto, outra pessoa, nenhuma linha
  // — e alcançar o projeto (que o membro interno alcança) não é alcançar a
  // conversa de quem pergunta.
  await expect(page.locator(".chat-messages")).not.toContainText(secret);
});
