import { execFileSync } from "node:child_process";

import { expect, test, type Page } from "@playwright/test";

import { STACK_REASON, stackIsMissing } from "./stack";

/**
 * A central de notificações ponta a ponta (Fase 2, ADR 0012).
 *
 * O que só este nível prova: uma mudança no Biahflow vira aviso no sino do
 * cliente **e** e-mail na caixa, atravessando banco, RLS, BFF, navegador e SMTP.
 *
 * O sync é disparado por dentro do container da API, com o mesmo
 * `sync_snapshot` que o webhook chama, porque a stack do Biahflow vive em outro
 * repositório — e a alternativa seria abrir um endpoint de teste na API, que é
 * exatamente o tipo de superfície que não deve existir em produção para um teste
 * existir. O snapshot é o versionado do seed, alterado em memória.
 */

const MAILPIT = process.env.MAILPIT_URL ?? "http://localhost:8025";
const CLIENT = { username: "marina.farias", password: "portal_local_only" };
const CLIENT_EMAIL = "marina.farias@acme.com.br";

/**
 * Sincroniza duas vezes — a primeira estabelece a linha de base (o primeiro sync
 * de um projeto não notifica, por desenho) e a segunda muda alguma coisa. O
 * `marker` vira o id de um documento novo, o que garante uma notificação inédita
 * a cada chamada: o `dedupe_key` existe justamente para o mesmo fato não emitir
 * duas vezes, então um teste que precise de "não lida" precisa de um fato novo.
 */
const SYNC_SCRIPT = `
import json, sys
from portal_api.db.session import DbRole, get_session
from portal_api.integrations import biahflow
from portal_api.seed import SNAPSHOT_PATH
from portal_api.worker import send_project_digests

marker = sys.argv[1]
snapshot = json.loads(SNAPSHOT_PATH.read_text())
with get_session(role=DbRole.system) as session:
    biahflow.sync_snapshot(session, snapshot)

snapshot["milestones"][0]["status"] = "done"
snapshot["documents"].append({
    "id": marker, "name": "Ata do comite " + marker, "type": "PDF",
    "author": "Portal Labs", "link": "", "created_at": "2026-08-04T12:00:00+00:00",
})
with get_session(role=DbRole.system) as session:
    project = biahflow.sync_snapshot(session, snapshot)
    project_id = str(project.id)

send_project_digests(project_id)
print(project_id)
`;

/** Devolve o título do documento recém-sincronizado, ou `null` sem stack no ar. */
function syncSomethingNew(): string | null {
  const marker = `e2e-${Date.now().toString(36)}`;
  try {
    execFileSync(
      "docker",
      ["compose", "exec", "-T", "api", "python", "-c", SYNC_SCRIPT, marker],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
    );
    return `Ata do comite ${marker}`;
  } catch {
    return null; // sem docker à mão: os testes se pulam em vez de mentir
  }
}

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
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

/** Cada teste cria o próprio fato novo: assim nenhum depende da ordem do outro. */
let lastChange: string | null = null;

test.beforeEach(() => {
  lastChange = syncSomethingNew();
  test.skip(stackIsMissing(lastChange !== null), STACK_REASON);
});

test("uma mudança no Biahflow vira aviso no sino e e-mail na caixa", async ({ page }) => {
  await signIn(page, CLIENT);

  const bell = page.getByRole("button", { name: /^Notificações/ });
  await expect(bell).toHaveAttribute("aria-label", /\d+ não lidas/);

  await bell.click();
  // Dentro do popover, e o aviso desta rodada: o mesmo documento também aparece
  // em "Atualizações recentes", e a caixa acumula entre execuções.
  const popover = page.locator(".popover--notifications");
  await expect(popover.getByText("Novo documento no projeto").first()).toBeVisible();
  await expect(popover.getByText(lastChange!, { exact: false })).toBeVisible();

  // Um resumo por lote de sync, não um e-mail por aviso.
  const inbox = await page.request.get(
    `${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${CLIENT_EMAIL}`)}`,
  );
  const messages = (await inbox.json()).messages ?? [];
  expect(messages.length).toBeGreaterThan(0);
  expect(messages[0].Subject).toMatch(/Automação Financeira/);
});

test("abrir o sino zera o contador, e o F5 não o traz de volta", async ({ page }) => {
  await signIn(page, CLIENT);

  const bell = page.getByRole("button", { name: /^Notificações/ });
  await expect(bell).toHaveAttribute("aria-label", /\d+ não lidas/);

  await bell.click();
  await expect(bell).toHaveAttribute("aria-label", "Notificações");

  // A prova de que a leitura foi para o banco: antes da Fase 2 isto era um
  // booleano de estado, e o recarregamento devolvia o ponto vermelho.
  await page.reload();
  await expect(page.getByRole("button", { name: /^Notificações/ })).toHaveAttribute(
    "aria-label",
    "Notificações",
  );
});

test("a central lista o histórico do projeto", async ({ page }) => {
  await signIn(page, CLIENT);

  await page.getByRole("button", { name: "Abrir menu do usuário" }).first().click();
  // Dentro do menu: o sino da barra também se chama "Notificações".
  await page.locator(".popover-menu").getByRole("button", { name: "Notificações" }).click();

  await expect(page.getByRole("heading", { name: "Central de notificações" })).toBeVisible();
  await expect(page.getByText("Avisos do projeto")).toBeVisible();
});

test("o aviso leva à linha do documento, e não só à aba", async ({ page }) => {
  // O critério de aceite (4) da FDD 021 provado ponta a ponta pela primeira vez
  // (ADR 0056): até aqui o e2e provava que o aviso **existe**, não que ele leva a
  // algum lugar. O documento sincronizado no `beforeEach` dá o rótulo exato para
  // ancorar, e o percurso é o do cliente — sino, "Ver todas", clique no aviso.
  await signIn(page, CLIENT);

  await page.getByRole("button", { name: /^Notificações/ }).click();
  await page.locator(".popover--notifications").getByRole("button", { name: /Ver todas/ }).click();

  const aviso = page
    .locator("a.notification-row")
    .filter({ hasText: lastChange! })
    .first();
  await expect(aviso).toBeVisible();
  // O `href` continua sendo o caminho compartilhável, e é o que a recusa da
  // interceptação usa quando o aviso é de outro projeto (ADR 0057).
  await expect(aviso).toHaveAttribute(
    "href",
    new RegExp(`item=document%3A${encodeURIComponent(lastChange!)}`),
  );

  // Navega **na mesma aba** desde a ADR 0057: a Central perdeu o `target="_blank"`,
  // e chegar a uma lista que já está aberta não pede janela nova. O `waitForEvent`
  // que este caso tinha era a prova de que ela abria — e é o que muda aqui.
  await aviso.click();

  // E a linha daquele documento chega destacada, não só a aba.
  const linha = page.locator(`[data-item="document:${lastChange!}"]`);
  await expect(linha).toBeVisible();
  await expect(linha).toHaveClass(/is-anchored/);
});

test("o popover do sino também leva à linha, sem passar por 'Ver todas'", async ({ page }) => {
  // O caminho de menor atrito para quem **já está no portal**, e a ponta que a ADR
  // 0043 nomeou, a ADR 0056 renomeou e nenhuma das duas fechou: a linha do popover
  // era um `<div>`. Duas superfícies mostravam o mesmo aviso e só uma o levava a
  // algum lugar (ADR 0057).
  await signIn(page, CLIENT);

  await page.getByRole("button", { name: /^Notificações/ }).click();
  const popover = page.locator(".popover--notifications");
  const linhaDoAviso = popover.locator("a.popover-row").filter({ hasText: lastChange! }).first();
  await expect(linhaDoAviso).toBeVisible();

  // Nenhuma aba nova: o clique é interceptado e vira troca de aba, porque o
  // `?project=` do link é o projeto que já está na tela.
  const abasAntes = page.context().pages().length;
  await linhaDoAviso.click();
  expect(page.context().pages().length).toBe(abasAntes);

  // A aba do assunto abriu, o popover fechou, e a linha veio destacada.
  await expect(popover).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Documentos do projeto" })).toBeVisible();
  const linha = page.locator(`[data-item="document:${lastChange!}"]`);
  await expect(linha).toBeVisible();
  await expect(linha).toHaveClass(/is-anchored/);
});
