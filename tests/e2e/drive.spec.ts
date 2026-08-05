import { execFileSync } from "node:child_process";

import { expect, test, type Page } from "@playwright/test";

/**
 * Conector do Google Drive ponta a ponta (Fase 4, ADR 0016).
 *
 * O que só este nível prova: uma pessoa interna conecta uma pasta pelo navegador,
 * atravessa o consentimento OAuth de verdade (contra o `drive-stub` do compose,
 * que fala o mesmo REST do Google), e o conteúdo daquela pasta — e **somente**
 * dela — chega ao índice a ponto de o cliente receber a citação.
 *
 * O segundo teste é o que o `docs/threat-model.md` cobra nominalmente: o stub tem
 * um arquivo numa pasta que não foi autorizada e um atalho apontando para fora.
 * Nenhum dos dois pode virar documento — e aqui isso é verificado no navegador,
 * não só no unitário.
 *
 * O termo procurado na citação vem do próprio stub (`CANARY`), e não existe em
 * `seed.py`: encontrá-lo na resposta só é possível se o arquivo tiver mesmo sido
 * baixado do "Drive", indexado e recuperado.
 */

const ADMIN = { username: "helena.dias", password: "portal_local_only" };
const CLIENT = { username: "marina.farias", password: "portal_local_only" };

/** O mesmo de `portal_api/devtools/drive_stub.py`. */
const CANARY = "girassol-cravado-42";
const AUTHORIZED_FOLDER = "Contratos do Projeto";

function dockerAvailable(): boolean {
  try {
    execFileSync("docker", ["compose", "ps", "-q", "drive-stub"], { stdio: "ignore" });
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

/** Conecta a pasta autorizada e espera a indexação terminar. */
async function connectAndSync(page: Page) {
  await page.goto("/admin/conhecimento");
  await expect(
    page.getByRole("heading", { name: /O que o assistente pode citar/ }),
  ).toBeVisible();

  // Idempotente de propósito: dois testes deste arquivo chamam esta função, e o
  // consentimento do primeiro **persiste** — desconectar revoga e carimba a
  // linha, não a apaga (ADR 0016). Insistir em clicar "Conectar" faria o segundo
  // teste falhar procurando um botão que a tela deixou de mostrar por já estar
  // conectada, que é exatamente o estado que ele quer exercitar.
  const connect = page.getByRole("button", { name: /Conectar Google Drive/ });
  if (await connect.isVisible()) {
    // O consentimento: o stub devolve o navegador na hora, com `code` e `state`.
    await connect.click();
    await page.waitForURL(/\/admin\/conhecimento\?.*drive=connected/);
    await expect(page.getByText(/Drive conectado/)).toBeVisible();
  }

  // A pasta é escolhida num passo separado — só ela é a fronteira.
  const folderRow = page.locator(".member-row", { hasText: AUTHORIZED_FOLDER });
  const authorize = folderRow.getByRole("button", { name: "Autorizar" });
  if (await authorize.isVisible().catch(() => false)) {
    await authorize.click();
    await expect(page.getByText(/autorizada/)).toBeVisible();
  }

  await page.getByRole("button", { name: "Sincronizar agora" }).click();
  await expect(page.getByText(/Sincronização na fila/)).toBeVisible();

  const contract = page.locator(".member-row", { hasText: "Contrato de suporte" });
  const badge = contract.locator(".state", { hasText: "Indexado" });
  await expect(async () => {
    await page.reload();
    await expect(badge).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 90_000 });
}

test.beforeEach(() => {
  test.skip(!dockerAvailable(), "Precisa da stack local no ar (docker compose up)");
});

test("a pasta conectada vira citação no chat do cliente", async ({ page, context }) => {
  await signIn(page, ADMIN);
  await connectAndSync(page);

  await context.clearCookies();
  await signIn(page, CLIENT);
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();
  await page.getByLabel("Pergunta para IA").fill(`Qual é o código interno ${CANARY}?`);
  await page.getByRole("button", { name: "Enviar pergunta" }).click();

  // A **última** resposta, não `.message-sources` solto: a conversa sobrevive ao
  // reload (ADR 0015), então turnos de execuções anteriores continuam na thread.
  const answer = page.locator(".message--assistant").last();
  await expect(answer.locator(".message-sources")).toContainText(/Contrato de suporte/, {
    timeout: 30_000,
  });
  await expect(answer).toContainText(CANARY);
});

test("arquivo fora da pasta autorizada nunca entra no índice", async ({ page }) => {
  await signIn(page, ADMIN);
  await connectAndSync(page);

  // O stub serve `Confidencial.txt` numa pasta que ninguém autorizou e um atalho
  // dentro da pasta autorizada apontando para ela. Nenhum dos dois pode aparecer.
  await expect(page.locator(".member-row", { hasText: "Confidencial" })).toHaveCount(0);
  await expect(page.locator(".member-row", { hasText: "Atalho" })).toHaveCount(0);
  // E o que estava dentro entrou, senão o teste passaria por não ter sincronizado.
  await expect(page.locator(".member-row", { hasText: "Contrato de suporte" })).toHaveCount(1);
});

test("o cliente não alcança o conector do Drive", async ({ page }) => {
  await signIn(page, CLIENT);

  await page.goto("/admin/conhecimento");

  await expect(page.getByRole("heading", { name: "404" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Conectar Google Drive/ })).toHaveCount(0);
});
