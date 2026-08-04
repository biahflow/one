import { execFileSync } from "node:child_process";

import { expect, test, type Page } from "@playwright/test";

/**
 * Resultados ponta a ponta (Fase 3, ADR 0013).
 *
 * O que só este nível prova: uma pessoa interna configura a premissa e emite a
 * chave no navegador, um agente publica eventos com essa chave por HTTP, e o
 * cliente vê o número apurado — atravessando Keycloak, BFF, API, RLS e as duas
 * telas. Nenhuma camada é dublada.
 *
 * O agente é um `curl` de dentro do container da API, e não um fixture: o que
 * está sob teste é justamente que a chave criada pela tela autentica uma
 * requisição HTTP de verdade, vinda de fora da sessão do navegador.
 */

const ADMIN = { username: "helena.dias", password: "portal_local_only" };
const CLIENT = { username: "marina.farias", password: "portal_local_only" };

/** Publica um evento pelo container da API. `null` quando não há stack no ar. */
function publishEvent(key: string, projectId: string, eventId: string): string | null {
  const body = JSON.stringify({
    event_id: eventId,
    project_id: projectId,
    occurred_at: new Date().toISOString(),
    agent_key: "finance-agent",
    time_saved_seconds: 3_600,
    avoided_cost_cents: 5_000,
    run_reference: `e2e-${eventId.slice(0, 8)}`,
    outcome: "exception_handled",
    human_intervention: false,
  });
  try {
    return execFileSync(
      "docker",
      [
        "compose", "exec", "-T", "api",
        "python", "-c",
        `import json,sys,urllib.request
request = urllib.request.Request(
    "http://localhost:8000/api/v1/agent-events",
    data=sys.argv[1].encode(),
    headers={"Content-Type": "application/json", "X-Agent-Key": sys.argv[2]},
)
with urllib.request.urlopen(request) as response:
    print(json.load(response)["status"])`,
        body,
        key,
      ],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
    ).trim();
  } catch {
    return null;
  }
}

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
  // Espera voltar **ao portal**, e não apenas "sair de /login": o Keycloak
  // serve `/realms/...`, que também não começa com `/login`, então um login
  // recusado passaria por essa condição e o teste quebraria alguns passos
  // adiante, apontando para o lugar errado.
  await page.waitForURL(
    (url) => !url.pathname.startsWith("/login") && !url.pathname.startsWith("/realms"),
  );
}

test.beforeEach(() => {
  test.skip(!dockerAvailable(), "Precisa da stack local no ar (docker compose up)");
});

test("a premissa e a chave criadas na tela sustentam o número do cliente", async ({
  page,
  context,
}) => {
  await signIn(page, ADMIN);
  await page.goto("/admin/resultados");
  await expect(page.getByRole("heading", { name: /Como .* apura valor/ })).toBeVisible();

  // Com um projeto só não há seletor nem `?project=` na URL; a tela marca qual
  // projeto está administrando.
  const projectId = await page.locator(".admin-shell").getAttribute("data-project-id");
  expect(projectId).toBeTruthy();

  // 1. Premissa: uma data bem no passado, para cobrir os eventos de agora.
  await page.locator('input[name="effective_from"]').fill("2026-01-01");
  await page.locator('input[name="hourly_rate"]').fill("150");
  await page.locator('input[name="monthly_investment"]').fill("3000");
  await page.locator('input[name="note"]').fill("Contrato de implantação");
  await page.getByRole("button", { name: /Abrir vigência/ }).click();
  await expect(page.getByText(/Nova vigência aberta|vigência precisa começar/)).toBeVisible();

  // 2. Chave: aparece em claro exatamente uma vez.
  await page.locator('input[name="name"]').fill("Agente e2e");
  await page.getByRole("button", { name: /Emitir chave/ }).click();
  const revealed = page.locator("code", { hasText: /^plk_/ });
  await expect(revealed).toBeVisible();
  const key = (await revealed.textContent())!.trim();

  // 3. O agente publica — e o reenvio do mesmo evento não duplica resultado,
  // que é o aceite declarado da fase.
  const eventId = crypto.randomUUID();
  expect(publishEvent(key, projectId!, eventId)).toBe("accepted");
  expect(publishEvent(key, projectId!, eventId)).toBe("duplicate");

  // 4. O cliente vê o número e a premissa que o produziu.
  await context.clearCookies();
  await signIn(page, CLIENT);
  await page.getByRole("button", { name: "Resultados" }).click();

  await expect(page.getByRole("heading", { name: "Resultados do projeto" })).toBeVisible();

  // A premissa aparece ao lado do número — a metade visível do aceite da fase.
  const basis = page.locator(".panel", { hasText: "COMO CALCULAMOS" });
  await expect(basis.getByText("Valor-hora vigente", { exact: true })).toBeVisible();
  // Sem o "R$": `Intl` separa o símbolo com espaço não separável, que não casa
  // com um espaço comum no seletor.
  await expect(basis.locator(".field-row", { hasText: "Valor-hora vigente" })).toContainText(
    "150,00",
  );
  await expect(basis.getByText("Contrato de implantação")).toBeVisible();

  // O painel conta eventos de verdade. A contagem exata não serve de asserção
  // aqui — o banco local acumula entre execuções — e a idempotência já está
  // provada acima pelo par accepted/duplicate, com a contagem de linhas coberta
  // em `test_agent_events.py`, que é onde ela pode ser isolada.
  await expect(basis.getByText("Eventos considerados", { exact: true })).toBeVisible();
  await expect(
    basis.locator(".field-row", { hasText: "Eventos considerados" }),
  ).toContainText(/[1-9]\d*/);

  // E nenhum dos números de demonstração sobreviveu na tela.
  await expect(page.getByText("12,4k")).toHaveCount(0);
  await expect(page.getByText("98,6%")).toHaveCount(0);
  await expect(page.getByText("1.203")).toHaveCount(0);
});

test("o cliente não alcança a administração de resultados", async ({ page }) => {
  await signIn(page, CLIENT);

  await page.goto("/admin/resultados");

  // A API nega com 404 (nunca 403) e a tela não existe para ela. A asserção é
  // sobre o que a pessoa vê: o status HTTP fica 200 porque o Next já começou a
  // transmitir a resposta antes de saber que era negada — mesma observação do
  // `invite.spec.ts`.
  await expect(page.getByRole("heading", { name: "404" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /apura valor/ })).toHaveCount(0);
});
