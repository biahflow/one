import { execFileSync } from "node:child_process";

import { expect, test, type Page } from "@playwright/test";

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

test.beforeEach(() => {
  test.skip(!dockerAvailable(), "Precisa da stack local no ar (docker compose up)");
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
  await expect(async () => {
    await page.reload();
    await expect(badge).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 60_000 });
  await expect(row).toContainText(/trecho/);

  // O cliente pergunta e recebe a citação daquele documento.
  await context.clearCookies();
  await signIn(page, CLIENT);
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();
  await page.getByLabel("Pergunta para IA").fill(`O que diz o procedimento ${codeword}?`);
  await page.getByRole("button", { name: "Enviar pergunta" }).click();

  // A citação nomeia o documento — e o termo só existe no arquivo enviado acima.
  await expect(page.locator(".message-sources")).toContainText(title, { timeout: 30_000 });
  await expect(page.locator(".chat-messages")).toContainText(codeword);
});

test("o cliente não alcança a administração de conhecimento", async ({ page }) => {
  await signIn(page, CLIENT);

  await page.goto("/admin/conhecimento");

  // A API nega com 404 (nunca 403) e a tela não existe para ela — mesma
  // observação do `results.spec.ts` sobre o status HTTP ficar 200.
  await expect(page.getByRole("heading", { name: "404" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /pode citar/ })).toHaveCount(0);
});
