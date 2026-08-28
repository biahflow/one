import { expect, test } from "@playwright/test";

import { CLIENTE as CLIENT, signIn } from "./atores";
import { STACK_REASON, serviceIsUp, stackIsMissing } from "./stack";

/**
 * A aba Decisões no navegador (ADR 0049).
 *
 * O que só este nível prova é o caminho inteiro: a decisão nasce no Biahflow, atravessa
 * o snapshot, é reescrita pelo `sync_snapshot` do seed, e chega à tela do cliente com o
 * **porquê** e com a reunião de onde saiu. Nenhuma peça é dublada.
 *
 * O ator é a Marina, que tem vínculo direto no projeto — então `default_project` é
 * determinístico para ela e o spec não precisa de `?project=` (ver `atores.ts`).
 */

test.beforeEach(() => {
  test.skip(stackIsMissing(serviceIsUp("api")), STACK_REASON);
});

test("a decisão chega à tela do cliente com o porquê e a reunião de origem", async ({ page }) => {
  await signIn(page, CLIENT);
  await page.getByRole("button", { name: "Decisões" }).click();

  const painel = page.getByRole("article").filter({ hasText: "Decisões registradas" });
  await expect(painel).toBeVisible();

  // O título, o racional e a proveniência — as três coisas que a pendência não carrega.
  await expect(painel).toContainText("Adotar fila gerenciada em vez de instância própria");
  await expect(painel).toContainText("escala a zero fora do horário comercial");
  await expect(painel).toContainText("Revisão de integrações");
  await expect(painel).toContainText("Marina Farias");
});

test("o filtro separa a decisão que veio de uma reunião da que não veio", async ({ page }) => {
  await signIn(page, CLIENT);
  await page.getByRole("button", { name: "Decisões" }).click();

  const painel = page.getByRole("article").filter({ hasText: "Decisões registradas" });
  await expect(painel).toContainText("Adiar o PROVE de cobrança");

  await painel.getByRole("button", { name: /De uma reunião/ }).click();
  await expect(painel).toContainText("Adotar fila gerenciada em vez de instância própria");
});
