import { expect, test, type Page } from "@playwright/test";

/**
 * O convite ponta a ponta — o único teste que prova o produto inteiro.
 *
 * Entra como administrador, convida um e-mail novo, **lê a mensagem na caixa do
 * Mailpit**, segue o link, define a senha e entra com a conta recém-criada. É o
 * que nenhum outro nível alcança: os testes de API dublam o Keycloak justamente
 * porque o que ele faz é mandar e-mail, e é aqui que isso é verificado.
 */

const MAILPIT = process.env.MAILPIT_URL ?? "http://localhost:8025";
const ADMIN = { username: "helena.dias", password: "portal_local_only" };
const NEW_PASSWORD = "Convidado#2026";

/** E-mail novo a cada execução: o realm guarda contas entre rodadas. */
function freshEmail(): string {
  return `convidado.${Date.now().toString(36)}@cliente.com.br`;
}

async function signIn(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByRole("button", { name: /Entrar com SSO/ }).click();
  await page.waitForURL(/\/realms\/portal-local\/protocol\/openid-connect\/auth/);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.locator("#kc-login").click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

/** O link de ação que o Keycloak mandou para este endereço.
 *
 * Laço explícito em vez de `expect.poll`: aqui o valor importa, e `poll`
 * devolve uma asserção encadeável, não o que foi lido.
 */
async function invitationLink(page: Page, email: string): Promise<string> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const inbox = await page.request.get(
      `${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${email}`)}`,
    );
    const { messages = [] } = await inbox.json();
    if (messages.length > 0) {
      const message = await page.request.get(`${MAILPIT}/api/v1/message/${messages[0].ID}`);
      const body = await message.json();
      const match = String(body.Text ?? body.HTML ?? "").match(
        /https?:\/\/[^\s"<>]*login-actions\/action-token[^\s"<>]*/,
      );
      if (match) return match[0].replace(/&amp;/g, "&");
    }
    await page.waitForTimeout(500);
  }
  throw new Error(`nenhum convite chegou para ${email}`);
}

test.beforeEach(async ({ request }) => {
  // Caixa limpa: a busca por destinatário já isola, mas rodadas antigas poluem
  // o diagnóstico quando algo falha.
  await request.delete(`${MAILPIT}/api/v1/messages`);
});

test("administrador convida, a pessoa recebe o e-mail e entra vendo só o projeto dela", async ({
  page,
}) => {
  const email = freshEmail();

  await signIn(page, ADMIN.username, ADMIN.password);

  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: /Quem enxerga/ })).toBeVisible();

  await page.getByLabel("Nome").fill("Convidado de Teste");
  await page.getByLabel("E-mail").fill(email);
  await page.getByRole("button", { name: /Enviar convite/ }).click();

  // A tela confirma, e o convite aparece como pendente até a pessoa entrar.
  await expect(page.getByText(`Convite enviado para ${email}.`)).toBeVisible();
  await expect(page.getByText("Convite pendente").first()).toBeVisible();

  const link = await invitationLink(page, email);

  // A partir daqui é a pessoa convidada, em contexto limpo.
  const invitee = await page.context().browser()!.newContext();
  const inviteePage = await invitee.newPage();
  await inviteePage.goto(link);

  // O link de e-mail cai numa página de confirmação antes do formulário: o
  // Keycloak não age sobre a conta só porque alguém abriu a mensagem.
  const proceed = inviteePage.locator("#kc-info-message a, #kc-content a").first();
  if (await proceed.isVisible().catch(() => false)) {
    await proceed.click();
  }

  await inviteePage.locator("#password-new").fill(NEW_PASSWORD);
  await inviteePage.locator("#password-confirm").fill(NEW_PASSWORD);
  await inviteePage.getByRole("button", { name: /Enviar|Submit/ }).click();

  await inviteePage.goto("/");
  if (inviteePage.url().includes("/login")) {
    await signIn(inviteePage, email, NEW_PASSWORD);
  }

  await expect(inviteePage.getByText("Automação Financeira").first()).toBeVisible();
  await expect(inviteePage.getByText("Bom dia, Convidado.")).toBeVisible();
  await invitee.close();
});

test("cliente não alcança a administração", async ({ page }) => {
  await signIn(page, "marina.farias", "portal_local_only");

  await page.goto("/admin");

  // A API nega com 404 (nunca 403) e a tela não existe para ela. A asserção é
  // sobre o que a pessoa vê: o status HTTP fica 200 porque o Next já começou a
  // transmitir a resposta antes de saber que era negada.
  await expect(page.getByRole("heading", { name: "404" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Quem enxerga/ })).toHaveCount(0);
});
