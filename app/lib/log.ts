/**
 * Log estruturado do BFF (Fase 5, ADR 0018).
 *
 * Mesma forma do `portal_api/telemetry.py`: uma linha JSON por evento, com
 * `event` e `trace_id`, para que `docker compose logs web` e
 * `docker compose logs api` sejam filtráveis pelo mesmo campo. Não há
 * biblioteca aqui pelo mesmo motivo que não há do lado do Python — o formato é
 * um `JSON.stringify`, e uma dependência a mais no bundle do servidor não
 * compraria nada.
 *
 * Antes disto não havia um `console.error` sequer em `app/`: uma falha de rede
 * entre o BFF e a API sumia no `catch {}` de `app/actions.ts`, e `app/error.tsx`
 * dizia ao cliente "A falha foi registrada" sem que nada registrasse.
 *
 * Só é chamado de código de servidor — server components, server actions,
 * route handlers e `instrumentation.ts`. Não há marcador `server-only` aqui
 * pelo mesmo motivo que não há em `app/lib/session.ts`, que guarda coisa bem
 * mais sensível: o repositório não usa o pacote, e importar isto de um
 * componente `"use client"` quebraria no build de qualquer forma.
 */

type Fields = Record<string, unknown>;

function emit(level: "info" | "warn" | "error", event: string, fields: Fields): void {
  const line = JSON.stringify({
    ts: new Date().toISOString(),
    level: level.toUpperCase(),
    logger: "web",
    event,
    ...fields,
  });
  if (level === "error") console.error(line);
  else if (level === "warn") console.warn(line);
  else console.log(line);
}

export function logInfo(event: string, fields: Fields = {}): void {
  emit("info", event, fields);
}

export function logWarn(event: string, fields: Fields = {}): void {
  emit("warn", event, fields);
}

export function logError(event: string, fields: Fields = {}): void {
  emit("error", event, fields);
}

/**
 * Um `Error` que carrega o `trace_id` até a fronteira de erro.
 *
 * `instrumentation.ts` recebe o objeto lançado **antes** de o Next o sanear
 * para o cliente, então a propriedade sobrevive até lá — e é isso que faz o
 * `digest` que a pessoa lê na tela e o `trace_id` que atravessou a API caírem
 * na mesma linha de log. Sem isso os dois só se juntariam por horário.
 */
export class TracedError extends Error {
  readonly traceId: string;

  constructor(message: string, traceId: string) {
    super(message);
    this.name = "TracedError";
    this.traceId = traceId;
  }
}

export function traceIdOf(error: unknown): string {
  return error instanceof TracedError ? error.traceId : "";
}
