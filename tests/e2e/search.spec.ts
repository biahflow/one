import { expect, test, type Page } from "@playwright/test";

import { STACK_REASON, serviceIsUp, stackIsMissing } from "./stack";

/**
 * A busca do projeto no navegador (Fase 6, ADR 0024).
 *
 * O que só este nível prova: o campo da lupa — que até esta fatia era um
 * `<input>` sem handler, prometendo "buscar no contexto do projeto" — digita,
 * espera o debounce, chama o BFF com a sessão real e mostra o que a API
 * escopada devolveu. Nenhuma peça é dublada: Keycloak, FastAPI, Postgres,
 * MinIO e o worker são os do compose.
 *
 * São duas provas diferentes de propósito. A primeira usa o read model semeado
 * e é rápida; a segunda sobe um arquivo com um termo inédito, espera a
 * indexação e procura **dentro** do texto — que é a metade da promessa que um
 * casamento por título não alcança.
 */

const ADMIN = { username: "helena.dias", password: "portal_local_only" };
const CLIENT = { username: "marina.farias", password: "portal_local_only" };

async function signIn(page: Page, user: { username: string; password: string }) {
  // Limpa **aqui**, coladinho no `goto` — ver o comentário longo em
  // `login.spec.ts`: limpar no chamador deixa uma janela em que a navegação
  // anterior reescreve o cookie e `/login` já redireciona para `/`.
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

/** Abre a lupa e digita, devolvendo a lista de resultados. */
async function search(page: Page, term: string) {
  await page.getByRole("button", { name: "Pesquisar" }).click();
  await page.getByLabel("Buscar no projeto").fill(term);
  return page.getByRole("list", { name: "Resultados da busca" });
}

test.beforeEach(() => {
  test.skip(stackIsMissing(serviceIsUp("api")), STACK_REASON);
});

test("a busca acha a pendência do projeto e o clique leva à aba dela", async ({ page }) => {
  await signIn(page, CLIENT);

  // Sem acento e em caixa baixa, contra um título que tem os dois: é o par
  // `fold`/`folded` de `textfold.py` funcionando dos dois lados da comparação.
  const results = await search(page, "excecoes");

  const hit = results.getByRole("button", { name: /Aprovar fluxo de exceções/ });
  await expect(hit).toBeVisible();
  await expect(hit).toContainText("Pendência");

  await hit.click();
  // O clique navega por rótulo de aba, e o rótulo veio da API — não há segundo
  // mapa no navegador para envelhecer.
  await expect(page.getByRole("heading", { name: "Pendências do projeto" })).toBeVisible();
});

test("um termo que o projeto não tem não vira resultado inventado", async ({ page }) => {
  await signIn(page, CLIENT);

  const term = `nadaporaqui${Date.now().toString(36)}`;
  await search(page, term);

  await expect(page.getByText(`Nada encontrado para “${term}”`)).toBeVisible();
  await expect(page.getByRole("list", { name: "Resultados da busca" })).toHaveCount(0);
});

test("a busca acha o termo dentro do documento e oferece a página", async ({
  page,
  context,
}) => {
  // Um termo que não existe no read model, no seed nem em outro spec: se ele
  // aparecer, veio do arquivo que este teste acabou de subir.
  const codeword = `vermilhado${Date.now().toString(36)}`;
  const title = `Aditivo ${codeword}`;

  await signIn(page, ADMIN);
  await page.goto("/admin/conhecimento");
  await page.locator('input[name="file"]').setInputFiles({
    name: "aditivo.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      `Aditivo contratual.\n\nO regime ${codeword} substitui o anexo anterior.\n`,
      "utf8",
    ),
  });
  await page.locator('input[name="title"]').fill(title);
  await page.getByRole("button", { name: /Enviar e indexar/ }).click();
  await expect(page.getByText(/Documento recebido/)).toBeVisible();

  // A indexação é assíncrona, e a tela de administração é a forma de acompanhá-la.
  const row = page.locator(".member-row", { hasText: title });
  await expect(async () => {
    await page.reload();
    await expect(row.locator(".state", { hasText: "Indexado" })).toBeVisible({
      timeout: 2_000,
    });
  }).toPass({ timeout: 40_000 });

  await context.clearCookies();
  await signIn(page, CLIENT);
  const results = await search(page, codeword);

  // O mesmo termo casa duas vezes, e é assim que tem de ser: o título do
  // documento e o texto dentro dele são achados diferentes, com destinos
  // diferentes no clique. Daí o filtro pelo rótulo em vez de um `.first()`, que
  // esconderia se um dos dois sumisse.
  await expect(
    results.getByRole("button", { name: new RegExp(`Documento ${title}`) }),
  ).toBeVisible({ timeout: 15_000 });

  // E o trecho vem com a posição — o mesmo `location` que a citação do chat
  // mostra, verdadeiro pela mesma razão: o chunk nunca cruza a virada de
  // página (ADR 0014).
  const excerpt = results.getByRole("button", { name: /Trecho de documento/ });
  await expect(excerpt).toContainText(title);
  await expect(excerpt).toContainText(codeword);
});
