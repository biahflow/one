import { defineConfig, devices } from "@playwright/test";

/**
 * E2E contra a stack local (`docker compose up`). É o único nível de teste que
 * sobe o Keycloak de verdade: o resto da suíte valida JWT com JWKS falso e SSR
 * com cookie forjado, o que é mais rápido e determinístico. Aqui provamos o que
 * só o navegador prova — o redirect, o code exchange e o fim da sessão.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
