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

/** `Authorization` header for a call to the API, or `null` without a session. */
export async function authorizationHeader(): Promise<Record<string, string> | null> {
  const accessToken = await getAccessToken();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : null;
}
