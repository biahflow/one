
import { expect, test } from "@playwright/test";

import { ADMIN, CLIENTE as CLIENT, projetoDoSeed, signIn } from "./atores";
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
  // O upload tem de cair **no projeto da Marina**, senão o documento é indexado
  // num tenant e a pergunta roda em outro — e o assistente, corretamente,
  // declara lacuna. Sem o `?project=` a tela usa `me.projects[0]`, que é "o
  // projeto criado por último" e não tem relação com quem vai perguntar.
  const projeto = await projetoDoSeed(page);
  await page.goto(`/admin/knowledge?project=${projeto}`);
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
  // Este teste não depende de qual projeto, mas escrever num explícito importa
  // por outro motivo: sem isso o destino é "o projeto criado por último", e o
  // lixo das execuções passa a se acumular em qualquer organização que alguém
  // tenha criado à mão. Os artefatos ficam onde o seed os espera.
  await page.goto(`/admin/knowledge?project=${await projetoDoSeed(page)}`);

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

  await page.goto("/admin/knowledge");

  // A API nega com 404 (nunca 403) e a tela não existe para ela — mesma
  // observação do `results.spec.ts` sobre o status HTTP ficar 200.
  await expect(page.getByRole("heading", { name: "404" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /pode citar/ })).toHaveCount(0);
});
