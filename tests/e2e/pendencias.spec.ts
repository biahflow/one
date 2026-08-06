import { expect, test, type Page } from "@playwright/test";

import { STACK_REASON, serviceIsUp, stackIsMissing } from "./stack";

/**
 * Prioridade e filtro na aba onde o cliente decide o que fazer (ADR 0029).
 *
 * O que só este nível prova: que o dado atravessa a corrente inteira até um
 * navegador de verdade. A prioridade é coluna no Postgres desde a Fase 1, o
 * sync a projeta, o contrato a declara — e o mapeamento do BFF a descartava,
 * de modo que toda pendência aparecia igual. `api-contract.test.mjs` pega o
 * descarte no código-fonte; aqui se vê o selo e o filtro funcionando com a
 * sessão real e o read model semeado.
 */

const CLIENT = { username: "marina.farias", password: "portal_local_only" };

async function signIn(page: Page, user: { username: string; password: string }) {
  // Limpa coladinho no `goto`, pelo motivo longo em `login.spec.ts`.
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

test("o filtro de prioridade encolhe a lista e o caminho de volta existe", async ({ page }) => {
  await signIn(page, CLIENT);
  // Sem `exact`: o item da navegação carrega a contagem de abertas num `<em>`,
  // então o nome acessível é "Pendências 3", não "Pendências".
  await page.getByRole("button", { name: /^Pendências/ }).click();
  await expect(page.getByRole("heading", { name: "Pendências do projeto" })).toBeVisible();

  // Escopado ao painel de abertas: a aba tem dois, e o de resolvidas também usa
  // `.pending-row` — sem o escopo, a contagem inclui o que o filtro não toca.
  const rows = page.locator(".pending-panel .pending-row");
  const total = await rows.count();
  expect(total).toBeGreaterThan(0);

  // O chip diz quantas são antes de clicar — sem o número, escolher é adivinhar.
  const alta = page.getByRole("button", { name: /^Alta/ });
  const declared = Number((await alta.textContent())?.match(/\d+/)?.[0] ?? "-1");
  await alta.click();

  await expect(rows).toHaveCount(declared);
  expect(declared).toBeLessThan(total);

  // "Todas" é sempre a primeira opção: um filtro sem volta esconde dado e
  // parece lista vazia.
  await page.getByRole("button", { name: /^Todas/ }).click();
  await expect(rows).toHaveCount(total);
});

test("a pendência aberta pela IA leva de volta à pergunta que a gerou", async ({ page }) => {
  await signIn(page, CLIENT);
  await page.getByRole("button", { name: /^Pendências/ }).click();

  // As do Biahflow não vieram de conversa nenhuma; a da IA veio, e o FK que diz
  // qual turno era lido só como booleano até a ADR 0031.
  const row = page.locator(".pending-row", { hasText: "aberta pela IA" }).first();
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Ver a pergunta" }).click();

  // O chat abre e o turno apontado é o que fica em destaque — não o último.
  await expect(page.locator(".chat-panel")).toBeVisible();
  await expect(page.locator(".message--focused")).toHaveCount(1);
});

/**
 * O "outro lado" é o `internal_member`, e não a administradora, e a razão é do
 * ambiente: `helena.dias` tem vínculo org-wide em **duas** organizações nesta
 * máquina (o bootstrap da ADR 0025 rodou aqui), então o `default_project` dela é
 * o outro projeto e a caixa dela é a de outro tenant. `rafael.costa` pertence só
 * à organização semeada — e é ele quem, no produto, acompanha o projeto.
 */
const STAFF = { username: "rafael.costa", password: "portal_local_only" };

test("o comentário do cliente chega ao time, com aviso no sino", async ({ page }) => {
  const mark = `combinado-${Date.now().toString(36)}`;

  await signIn(page, CLIENT);

  /** A contagem do sino, ou 0 quando não há badge. */
  async function unread(): Promise<number> {
    const bell = page.getByRole("button", { name: /^Notificações/ });
    const label = (await bell.getAttribute("aria-label")) ?? "";
    return Number(label.match(/\((\d+)/)?.[1] ?? "0");
  }

  // Medido antes, e não comparado com zero: este banco acumula avisos de sync
  // anteriores, e exigir zero confundiria "não recebeu pelo próprio comentário"
  // com "não tem aviso nenhum".
  const before = await unread();

  await page.getByRole("button", { name: /^Pendências/ }).click();
  const row = page.locator(".pending-entry", { hasText: "Aprovar fluxo de exceções" }).first();
  // O fio abre por clique: oito pendências com todos abertos viram mural.
  await row.getByRole("button", { name: /Comentar|comentário/ }).click();
  await row.getByLabel("Novo comentário").fill(`Já enviei, ${mark}`);
  await row.getByRole("button", { name: "Enviar" }).click();
  await expect(row.getByText(new RegExp(mark))).toBeVisible();

  // Quem escreveu não é avisado do próprio comentário — é o que
  // `exclude_user_id` garante (ADR 0032).
  await page.reload();
  expect(await unread()).toBe(before);

  // E o outro lado vê o comentário e recebe o aviso.
  await signIn(page, STAFF);
  await expect(
    page.getByRole("button", { name: /Notificações \(\d+ não lidas\)/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^Pendências/ }).click();
  const sameRow = page
    .locator(".pending-entry", { hasText: "Aprovar fluxo de exceções" })
    .first();
  await sameRow.getByRole("button", { name: /comentário/ }).click();
  await expect(sameRow.getByText(new RegExp(mark))).toBeVisible();
});
