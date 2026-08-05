
import { expect, test, type Page } from "@playwright/test";

import { STACK_REASON, serviceIsUp, stackIsMissing } from "./stack";

/**
 * Conhecimento do projeto ponta a ponta (Fase 4, ADR 0014).
 *
 * O que só este nível prova: uma pessoa interna envia um arquivo pelo navegador,
 * o objeto chega ao MinIO de verdade, o worker o transforma em trechos com
 * embedding no pgvector, e o cliente — outra pessoa, outra sessão, outro papel
 * do Postgres — recebe a resposta citando aquele documento. Nada é dublado:
 * storage, fila e índice são os do compose.
 *
 * O texto enviado é único por execução, e é isso que faz a asserção valer: a
 * citação só pode ter vindo do arquivo que este teste acabou de subir.
 */

const ADMIN = { username: "helena.dias", password: "portal_local_only" };
const CLIENT = { username: "marina.farias", password: "portal_local_only" };

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

test.beforeEach(() => {
  test.skip(stackIsMissing(serviceIsUp("api")), STACK_REASON);
});

test("o documento enviado na administração vira citação no chat do cliente", async ({
  page,
  context,
}) => {
  // Um termo que não existe em lugar nenhum do read model nem do seed: se ele
  // aparecer na resposta, veio do arquivo.
  const codeword = `zafrenil${Date.now().toString(36)}`;
  const title = `Contrato ${codeword}`;

  await signIn(page, ADMIN);
  await page.goto("/admin/conhecimento");
  await expect(
    page.getByRole("heading", { name: /O que o assistente pode citar/ }),
  ).toBeVisible();

  await page.locator('input[name="file"]').setInputFiles({
    name: "contrato.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      `Cláusula de suporte do projeto.\n\n` +
        `O procedimento ${codeword} descreve o suporte contratado por 12 meses.\n`,
      "utf8",
    ),
  });
  await page.locator('input[name="title"]').fill(title);
  await page.getByRole("button", { name: /Enviar e indexar/ }).click();
  await expect(page.getByText(/Documento recebido/)).toBeVisible();

  // A indexação é assíncrona: o worker precisa buscar o objeto no MinIO,
  // extrair, dividir e vetorizar. A tela é a própria forma de acompanhar.
  const row = page.locator(".member-row", { hasText: title });
  // O selo de estado, e não a frase "indexado em …" da linha de baixo.
  const badge = row.locator(".state", { hasText: "Indexado" });
  // 40s, e não os 60s de antes: com a suíte inteira rodando, o worker está
  // ocupado com o que os outros specs enfileiraram, e esta espera passava a
  // consumir o orçamento inteiro do teste (ver `playwright.config.ts`).
  await expect(async () => {
    await page.reload();
    await expect(badge).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 40_000 });
  await expect(row).toContainText(/trecho/);

  // O cliente pergunta e recebe a citação daquele documento.
  await context.clearCookies();
  await signIn(page, CLIENT);
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();

  // Sempre a **última** resposta, nunca ".message-sources" solto: a conversa
  // sobrevive ao reload (ADR 0015), então uma execução anterior deste mesmo
  // teste deixa turnos antigos na thread — com citações de outro `codeword`.
  //
  // Não é preciso identificar "a nova" por contagem: a asserção abaixo é
  // web-first e reespera sozinha até a última resposta ser a que cita este
  // `codeword` — que só existe no arquivo enviado nesta execução.
  await page.getByLabel("Pergunta para IA").fill(`O que diz o procedimento ${codeword}?`);
  await page.getByRole("button", { name: "Enviar pergunta" }).click();
  const answer = page.locator(".message--assistant").last();
  await expect(answer.locator(".message-sources")).toContainText(title, {
    timeout: 30_000,
  });
  await expect(answer).toContainText(codeword);

  // E agora ela **abre** o documento (Fase 5, ADR 0017). O que só este nível
  // prova: a URL assinada é emitida pela API contra o endereço público do
  // storage, aceita pelo MinIO de verdade e devolve os bytes do arquivo que a
  // administração enviou lá em cima.
  const citation = answer.locator(".message-source-link", { hasText: title });
  await expect(citation).toBeVisible();
  const documentId = await citation.getAttribute("data-document-id");
  expect(documentId).toBeTruthy();

  const downloaded = await page.evaluate(async (id) => {
    const response = await fetch(`/api/documents/${id}/download`);
    if (!response.ok) return { status: response.status, body: "" };
    const { url } = await response.json();
    const file = await fetch(url);
    return { status: file.status, body: await file.text() };
  }, documentId);

  expect(downloaded.status).toBe(200);
  expect(downloaded.body).toContain(codeword);
});

test("o arquivo com assinatura de malware é recusado e não vira índice", async ({ page }) => {
  /**
   * A fronteira da ADR 0017 no navegador. O EICAR é a cadeia de teste padrão da
   * indústria — inofensiva por construção —, e é o que permite provar a rejeição
   * sem antivírus configurado, como o `drive-stub` prova o Drive sem o Google.
   *
   * Montada em pedaços aqui pelo mesmo motivo do `scanner.py`: escrita inteira,
   * faria um antivírus de verdade acusar o próprio arquivo de teste.
   */
  const eicar =
    "X5O!P%@AP[4\\PZX54(P^)7CC)7}$" +
    "EICAR-STANDARD-ANTIVIRUS-TEST-FILE" +
    "!$H+H*";
  const title = `Anexo suspeito ${Date.now().toString(36)}`;

  await signIn(page, ADMIN);
  await page.goto("/admin/conhecimento");

  await page.locator('input[name="file"]').setInputFiles({
    name: "anexo.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(eicar, "utf8"),
  });
  await page.locator('input[name="title"]').fill(title);
  await page.getByRole("button", { name: /Enviar e indexar/ }).click();
  await expect(page.getByText(/Documento recebido/)).toBeVisible();

  // O upload é aceito — a varredura é assíncrona, como a indexação. O que a tela
  // precisa mostrar é o desfecho, e ele não é "indexado".
  const row = page.locator(".member-row", { hasText: title });
  await expect(async () => {
    await page.reload();
    await expect(row.locator(".state", { hasText: "Recusado" })).toBeVisible({
      timeout: 2_000,
    });
  }).toPass({ timeout: 60_000 });

  await expect(row).toContainText(/Barrado pela varredura/);
  await expect(row).toContainText(/Eicar-Test-Signature/);
  // E nunca vira trecho: a linha não mostra contagem de trechos porque não há.
  await expect(row).not.toContainText(/trecho/);
});

test("o cliente não alcança a administração de conhecimento", async ({ page }) => {
  await signIn(page, CLIENT);

  await page.goto("/admin/conhecimento");

  // A API nega com 404 (nunca 403) e a tela não existe para ela — mesma
  // observação do `results.spec.ts` sobre o status HTTP ficar 200.
  await expect(page.getByRole("heading", { name: "404" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /pode citar/ })).toHaveCount(0);
});
