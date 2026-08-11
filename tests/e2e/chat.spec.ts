
import { expect, test, type Page } from "@playwright/test";

import {
  ADMIN,
  CLIENTE as CLIENT,
  MEMBRO_INTERNO as INTERNAL,
  projetoDoSeed,
  signIn,
} from "./atores";
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

/**
 * Dois atores internos, e a distinção entre eles é o assunto de um dos testes
 * abaixo. `INTERNAL` (`rafael.costa`) é `internal_member`: alcança o projeto e
 * **não** alcança `/admin/*`, porque `admin.py:_authorized` exige
 * `internal_admin` e responde 404. `ADMIN` (`helena.dias`) é quem alcança.
 *
 * O terceiro teste deste arquivo usava o Rafael para abrir `/admin/assistente` e
 * por isso **nunca passou** — recebia o 404 do contrato e o media como se fosse
 * ausência do comentário. Trocar a constante compartilhada teria consertado ele
 * e estragado o segundo teste, onde o Rafael é o ator certo e insubstituível:
 * ali o que se prova é que **nem quem tem acesso ao projeto** lê a conversa do
 * cliente, e usar a administradora enfraqueceria a afirmação.
 */
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

test("o comentário do cliente chega à tela do time interno", async ({ page, context }) => {
  // A prova de ponta a ponta da ADR 0033. `feedback_comment` existia na coluna,
  // na API e na rota do BFF desde a ADR 0015, e **não tinha escritor** — de modo
  // que o painel "O que os clientes disseram", criado pela ADR 0030, só podia
  // mostrar carimbo de data. Este teste é o que impede a volta desse estado: ele
  // falha tanto se o campo sumir do chat quanto se a tela do time parar de lê-lo.
  const remark = `faltou-o-cronograma-${Date.now().toString(36)}`;

  await signIn(page, CLIENT);

  // Índice fixo, e não `.last()` — pela razão que o primeiro teste deste arquivo
  // já explica e que aqui morde mais fundo. A conversa sobrevive entre execuções
  // (ADR 0015), então a thread já tem turnos, e `.last()` é **reavaliada a cada
  // chamada**: entre preencher o campo e clicar em "Enviar" ela pode passar a
  // apontar para outra mensagem, e o clique procura um botão que naquele turno
  // está desabilitado, porque o comentário foi digitado no turno de antes.
  // Contar e fixar o índice amarra as quatro interações ao turno que este teste
  // criou.
  const answers = page.locator(".message--assistant");
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();
  await page.waitForLoadState("networkidle");
  const before = await answers.count();

  await page.getByLabel("Pergunta para IA").fill("Qual é o status do projeto?");
  await page.getByRole("button", { name: "Enviar pergunta" }).click();
  await expect(answers).toHaveCount(before + 1, { timeout: 30_000 });
  const answer = answers.nth(before);

  // O campo só aparece depois do polegar: pedir texto antes torna o polegar
  // caro, e o polegar barato é o que faz existir algum sinal.
  await answer.getByRole("button", { name: "Esta resposta não ajudou" }).click();
  const comment = answer.getByRole("textbox", { name: "Comentário sobre esta resposta" });
  await expect(comment).toBeVisible();
  await comment.fill(remark);
  await answer.getByRole("button", { name: "Enviar" }).click();

  await context.clearCookies();
  // `ADMIN`, e não o membro interno: a tela é `internal_admin`-only por
  // contrato. E com `?project=`, porque sem ele a página administra
  // `me.projects[0]` — o projeto mais recente — enquanto o comentário foi
  // escrito na conversa da Marina, e o painel viria vazio pelo motivo errado.
  await signIn(page, ADMIN);
  await page.goto(`/admin/assistente?project=${await projetoDoSeed(page)}`);

  // O comentário aparece; a pergunta do cliente, não — o GRANT de coluna da
  // ADR 0030 é quem garante a segunda metade, e ela é afirmada aqui de novo
  // porque é o que torna a primeira aceitável.
  //
  // Escopado ao painel: `.field-list` é a lista de rótulo e valor do design
  // system e a tela tem duas — a do agregado ("Avaliadas 14 (9%)") e esta. Um
  // `.field-list` solto casa as duas e reprova por ambiguidade, o que este
  // teste nunca chegou a mostrar porque antes ele parava no 404.
  const avaliacoes = page
    .locator("article.panel")
    .filter({ has: page.getByRole("heading", { name: /O que os clientes disseram/ }) });
  await expect(avaliacoes.locator(".field-list")).toContainText(remark, { timeout: 30_000 });
  await expect(page.locator("body")).not.toContainText("Qual é o status do projeto?");
});
