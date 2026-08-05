/**
 * Server-side access to the OIDC access token (ADR 0010).
 *
 * The token lives in the encrypted Auth.js cookie and is never part of the
 * `session` object, so it cannot leak into a client bundle or an RSC payload.
 * `getToken()` is the only thing that opens that cookie, and it needs
 * `AUTH_SECRET` — which exists on the server alone.
 */

import { headers } from "next/headers";
import { getToken } from "next-auth/jwt";

import { TRACE_HEADER, traceId } from "@/app/lib/trace";

/** True when the cookie carries the `__Secure-` prefix, i.e. we are on https. */
function secureCookie(): boolean {
  return (process.env.AUTH_URL ?? "").startsWith("https://");
}

export async function getAccessToken(): Promise<string | null> {
  const token = await getToken({
    req: { headers: await headers() },
    secret: process.env.AUTH_SECRET,
    secureCookie: secureCookie(),
  });
  if (!token || token.error) return null;
  return token.accessToken ?? null;
}

/**
 * Os headers de uma chamada à API, ou `null` sem sessão.
 *
 * Além do `Authorization`, carrega o `X-Request-ID` da requisição em curso
 * (ADR 0018). É deliberadamente **este** o ponto de costura da telemetria: o
 * `CLAUDE.md` já manda toda chamada nova ao servidor sair daqui, então uma rota
 * futura ganha o id sem ninguém lembrar de pedi-lo — do mesmo jeito que ganha o
 * token.
 */
export async function authorizationHeader(): Promise<Record<string, string> | null> {
  const accessToken = await getAccessToken();
  if (!accessToken) return null;
  return {
    Authorization: `Bearer ${accessToken}`,
    [TRACE_HEADER]: await traceId(),
  };
}
