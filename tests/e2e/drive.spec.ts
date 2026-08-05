
import { expect, test, type Page } from "@playwright/test";

import { STACK_REASON, serviceIsUp, stackIsMissing } from "./stack";

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

/** Conecta a pasta autorizada e espera a indexação terminar. */
async function connectAndSync(page: Page) {
  await page.goto("/admin/conhecimento");
  await expect(
    page.getByRole("heading", { name: /O que o assistente pode citar/ }),
  ).toBeVisible();

  // Idempotente de propósito: os dois testes deste arquivo chamam esta função, e
  // o que o primeiro faz **persiste** — desconectar revoga e carimba a linha, não
  // a apaga (ADR 0016). O painel do conector tem três estados, e a função tem de
  // saber chegar do que encontrar até "sincronizado".
  const connect = page.getByRole("button", { name: /Conectar Google Drive/ });
  const choose = page.getByRole("button", { name: /Escolher a pasta|Trocar de pasta/ });
  const sync = page.getByRole("button", { name: "Sincronizar agora" });

  // Espera o painel assentar antes de perguntar em qual estado ele está. Um
  // `isVisible()` seco responderia "não" para um botão que ainda vai renderizar,
  // e o teste seguiria pulando justamente o passo que precisava dar.
  await expect(connect.or(choose).or(sync).first()).toBeVisible({ timeout: 15_000 });

  if (await connect.isVisible()) {
    // O consentimento: o stub devolve o navegador na hora, com `code` e `state`.
    await connect.click();
    await page.waitForURL(/\/admin\/conhecimento\?.*drive=connected/);
    await expect(page.getByText(/Drive conectado/)).toBeVisible();
  }

  // A pasta é escolhida num passo separado — só ela é a fronteira. Conectar não
  // autoriza nada, e é isso que o "Pasta não escolhida" da tela quer dizer.
  if (!(await sync.isVisible())) {
    if (await choose.isVisible()) {
      // O botão nasce `disabled` enquanto a tela ainda tem requisição em voo —
      // logo depois do callback do OAuth isso é o normal, não a exceção. Esperar
      // ficar habilitado é o que evita um clique que o Playwright reenfileira
      // até o timeout, sem nunca acontecer.
      // 40s: a requisição em voo é a listagem de pastas no Drive, e ela sai da
      // frente devagar quando o worker está ocupado com o que os outros specs
      // enfileiraram. Metade do orçamento do teste, pela regra do config.
      await expect(choose).toBeEnabled({ timeout: 40_000 });
      await choose.click();
    }
    const folderRow = page.locator(".member-row", { hasText: AUTHORIZED_FOLDER });
    await expect(folderRow).toBeVisible({ timeout: 15_000 });
    await folderRow.getByRole("button", { name: "Autorizar" }).click();
    await expect(page.getByText(/autorizada/)).toBeVisible();
  }

  await sync.click();
  await expect(page.getByText(/Sincronização na fila/)).toBeVisible();

  const contract = page.locator(".member-row", { hasText: "Contrato de suporte" });
  const badge = contract.locator(".state", { hasText: "Indexado" });
  await expect(async () => {
    await page.reload();
    await expect(badge).toBeVisible({ timeout: 2_000 });
    // Eram 90s **dentro de um teste de 60s**: a espera não tinha como chegar ao
    // fim, e o que a interrompia era o orçamento do teste — de modo que a falha
    // aparecia sempre noutro lugar. 60s é a metade do orçamento de hoje, e
    // ainda são vinte vezes o que esta sincronização leva com a fila vazia.
  }).toPass({ timeout: 60_000 });
}

test.beforeEach(() => {
  test.skip(stackIsMissing(serviceIsUp("drive-stub")), STACK_REASON);
});

test("a pasta conectada vira citação no chat do cliente", async ({ page, context }) => {
  await signIn(page, ADMIN);
  await connectAndSync(page);

  await context.clearCookies();
  await signIn(page, CLIENT);
  await page.getByRole("button", { name: /Abrir chat com IA/ }).click();

  // A **última** resposta, não `.message-sources` solto: a conversa sobrevive ao
  // reload (ADR 0015), então turnos de execuções anteriores continuam na thread.
  // A asserção abaixo é web-first e reespera até a última resposta citar o
  // documento da pasta — não é preciso identificar "a nova" por contagem.
  await page.getByLabel("Pergunta para IA").fill(`Qual é o código interno ${CANARY}?`);
  await page.getByRole("button", { name: "Enviar pergunta" }).click();
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
