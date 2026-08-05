
import { expect, test, type Page } from "@playwright/test";

import { STACK_REASON, serviceIsUp, stackIsMissing } from "./stack";

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

async function signIn(page: Page, user: { username: string; password: string }) {
  // Limpa **aqui**, coladinho no `goto`. Limpar no chamador deixa uma janela: a
  // navegação anterior pode ter uma requisição em voo que reescreve o cookie de
  // sessão logo depois, e aí `/login` redireciona para `/` (ele faz isso quando
  // há sessão) e o botão nunca aparece. O sintoma é um timeout esperando um
  // botão numa página que é o dashboard.
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

async function ask(page: Page, question: string) {
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();
  await page.getByLabel("Pergunta para IA").fill(question);
  await page.getByRole("button", { name: "Enviar pergunta" }).click();
}

test.beforeEach(async ({ context }) => {
  test.skip(stackIsMissing(serviceIsUp("api")), STACK_REASON);
  // O Keycloak mantém sessão SSO no navegador: sem limpar, `signIn` nem chega ao
  // formulário e o teste roda como quem entrou no spec anterior. Aqui isso seria
  // fatal — a conversa tem dono, e o dono errado invalida as duas asserções.
  await context.clearCookies();
});

test("a conversa volta depois do reload, com as citações e o feedback", async ({ page }) => {
  const question = `Qual é o status do projeto? (${Date.now().toString(36)})`;

  await signIn(page, CLIENT);

  // Sempre a **última** resposta. A conversa sobrevive ao reload — que é o que
  // este teste prova —, então ela também sobrevive entre execuções: turnos
  // antigos continuam na thread, e um seletor solto acabaria falando deles.
  //
  // Mas "a última" só vale depois que a nova chegou: numa thread que já tem
  // turnos, `.last()` resolve para a resposta **anterior** enquanto esta ainda
  // está em voo, e as asserções passariam a falar do turno errado. Contar antes
  // e esperar o incremento é o que amarra o teste ao turno que ele criou.
  // A contagem precisa ser tirada **depois** de o histórico assentar: o painel
  // abre com a saudação e só então troca tudo pelo que veio do Postgres. Contar
  // antes disso mede um número que muda por outro motivo — foi o que fez esta
  // asserção esperar `2` enquanto a tela chegava a `7`.
  const answers = page.locator(".message--assistant");
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();
  await page.waitForLoadState("networkidle");
  const before = await answers.count();

  await page.getByLabel("Pergunta para IA").fill(question);
  await page.getByRole("button", { name: "Enviar pergunta" }).click();
  await expect(answers).toHaveCount(before + 1, { timeout: 30_000 });

  // `.message-sources > *` e não `span`: desde a ADR 0017 a citação que aponta
  // para um arquivo é um `button` clicável, e a que vem do read model segue
  // `span`. O teste é sobre a citação voltar igual, não sobre a tag dela.
  const answer = () => answers.last();
  const firstSource = answer().locator(".message-sources > *").first();
  await expect(firstSource).toBeVisible({ timeout: 30_000 });
  const citation = (await firstSource.innerText()).trim();
  expect(citation.length).toBeGreaterThan(0);

  // O F5: nada do que está na tela agora veio do estado do navegador.
  await page.reload();
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();

  await expect(page.locator(".chat-messages")).toContainText(question, { timeout: 30_000 });
  // A mesma citação, remontada das partes gravadas — não uma nova consulta.
  await expect(answer().locator(".message-sources > *").first()).toHaveText(citation);

  // E a avaliação também é registro: marcada aqui, ainda marcada depois de outro F5.
  await answer().getByRole("button", { name: "Esta resposta não ajudou" }).click();
  await expect(answer().locator(".message-feedback button.is-active")).toHaveCount(1);

  await page.reload();
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();
  await expect(answer().locator(".message-feedback button.is-active")).toHaveCount(1, {
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
