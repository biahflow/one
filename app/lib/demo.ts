/**
 * O único caminho pelo qual dado de demonstração ainda chega à tela.
 *
 * Até a Fase 1 qualquer falha — 401, 404, rede — virava dashboard fabricado.
 * Agora a casca de demonstração exige as duas condições ao mesmo tempo: nenhuma
 * API configurada **e** `DEMO_MODE` ligado explicitamente. É a única exceção do
 * `proxy.ts`, e é por isso que ela mora em uma função só, fácil de encontrar
 * (`grep demoShellEnabled`).
 */
export function demoShellEnabled(): boolean {
  return !process.env.API_BASE_URL && process.env.DEMO_MODE === "true";
}
