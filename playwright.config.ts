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
  // Um worker, e não é conservadorismo: a suíte inteira dirige **uma** stack —
  // um Postgres, um MinIO, um Keycloak — com os mesmos usuários do seed. Dois
  // arquivos em paralelo autenticam `helena.dias` no mesmo instante, e a
  // proteção de força bruta do realm trata login simultâneo do mesmo usuário
  // como ataque: `user_temporarily_disabled` sem uma única senha errada, por 60
  // segundos. `fullyParallel: false` não bastava — ele serializa dentro de um
  // arquivo, e o paralelismo que quebra é o de arquivos entre si.
  //
  // O mesmo vale para o estado: specs concorrentes disputam as linhas do banco
  // que uns e outros criam. Serializar é o que torna a suíte legível quando ela
  // falha.
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
