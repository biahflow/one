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

import { tokenDeServico } from "@/app/lib/serviceIdentity";
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
 *
 * E, pela mesma razão, é aqui que entra a identidade **do serviço** (ADR 0046): a
 * `portal-api` exige IAM invoker além do ingress interno, e nenhum chamador
 * respondia a essa exigência. Pôr o header em cada `fetch` faria a próxima rota
 * nascer com 403 — e o 403 do Cloud Run acontece antes da aplicação, então não
 * apareceria em log nenhum nosso.
 */
export async function authorizationHeader(): Promise<Record<string, string> | null> {
  const accessToken = await getAccessToken();
  if (!accessToken) return null;

  const headersDaChamada: Record<string, string> = {
    Authorization: `Bearer ${accessToken}`,
    [TRACE_HEADER]: await traceId(),
  };

  const base = process.env.API_BASE_URL;
  if (base) {
    const idToken = await tokenDeServico(base);
    // `X-Serverless-Authorization` e não `Authorization`: o Cloud Run consome este
    // header e **não** o repassa, então o `Authorization` chega intacto na API com
    // o token da pessoa. Trocar um pelo outro faria a API perder o principal.
    if (idToken) headersDaChamada["X-Serverless-Authorization"] = `Bearer ${idToken}`;
  }

  return headersDaChamada;
}
