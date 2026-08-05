/**
 * O `trace_id` do lado do BFF (Fase 5, ADR 0018).
 *
 * Um identificador por requisição do navegador, que viaja em `X-Request-ID` até
 * a FastAPI e de lá até a task do Celery. É o que faz a linha do `web`, a do
 * `api` e a do `worker` contarem a mesma história.
 *
 * **Memoizado com o `cache()` do React**, e não com uma variável de módulo: o
 * servidor atende requisições concorrentes no mesmo processo, então um módulo
 * daria o mesmo id a pessoas diferentes. O `cache()` tem o tempo de vida exato
 * de uma requisição — que é o que faz as três `fetch()` paralelas de
 * `app/page.tsx` saírem com um id só, em vez de três.
 *
 * O id **não** nasce no `proxy.ts`. Injetar header no caminho de passagem
 * exigiria devolver um `NextResponse` de dentro do wrapper do Auth.js, que é
 * onde o cookie de sessão renovado é escrito — e o portão de sessão não é o
 * lugar para correr esse risco. O preço está no ADR: a negação do próprio portão
 * só carrega id quando quem chamou mandou um.
 */

import { cache } from "react";
import { headers } from "next/headers";

/** O nome do header, igual dos dois lados (`portal_api/telemetry.py`). */
export const TRACE_HEADER = "X-Request-ID";

/**
 * O id desta requisição. Aceita um vindo de fora para que um balanceador ou um
 * gateway possa ser o dono do identificador no dia em que houver um; sem ele,
 * cunha aqui.
 */
export const traceId = cache(async (): Promise<string> => {
  const inbound = (await headers()).get(TRACE_HEADER);
  return inbound?.trim() || crypto.randomUUID();
});
