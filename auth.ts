/**
 * Auth.js v5 — the BFF as the OIDC client (ADR 0010).
 *
 * The portal has one confidential client (`portal-web`): the authorization code
 * is exchanged here, on the server, and the access token never reaches the
 * browser. `app/lib/session.ts` reads it back out of the encrypted cookie when
 * the BFF calls the API; `callbacks.session` deliberately exposes only the name
 * and e-mail.
 *
 * **Two URLs for one Keycloak, on purpose.** The browser reaches it at
 * `localhost:8080` — that address is the `iss` of every token, and the API
 * validates against it — while this container only reaches `keycloak:8080`. So
 * the authorization endpoint (where we *send the browser*) is built from the
 * public issuer and the token/userinfo endpoints (which we call ourselves) from
 * the internal one. Passing both explicitly also skips OIDC discovery, which
 * would otherwise refuse the mismatch. Running `npm run dev` on the host, the
 * two are the same and none of this shows.
 *
 * Roles are absent from the session by design: a realm role cannot say *which
 * project*, so the UI takes them from `GET /api/v1/me`, which answers from the
 * membership — the authority (ADR 0002/0010).
 */

import NextAuth, { type NextAuthConfig } from "next-auth";
import Keycloak from "next-auth/providers/keycloak";
import type { JWT } from "next-auth/jwt";

const DEFAULT_ISSUER = "http://localhost:8080/realms/portal-local";
/** Renew this many seconds before expiry, so a request never races the clock. */
const REFRESH_SKEW_SECONDS = 30;

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    refreshToken?: string;
    idToken?: string;
    /** Unix seconds, from the token endpoint. */
    expiresAt?: number;
    /** Set when the refresh failed — `proxy.ts` turns it into a redirect. */
    error?: "RefreshAccessTokenError";
  }
}

declare module "next-auth" {
  interface Session {
    error?: "RefreshAccessTokenError";
  }
}

/** Realm URLs. Read per call so `next build` never needs the environment. */
function realm() {
  const issuer = process.env.KEYCLOAK_ISSUER || DEFAULT_ISSUER;
  return {
    issuer,
    // The compose sets this to the service address; on the host it is the issuer.
    internal: process.env.KEYCLOAK_INTERNAL_URL || issuer,
    clientId: process.env.AUTH_KEYCLOAK_ID || "portal-web",
    clientSecret: process.env.AUTH_KEYCLOAK_SECRET || "",
  };
}

async function refreshAccessToken(token: JWT): Promise<JWT> {
  const { internal, clientId, clientSecret } = realm();
  if (!token.refreshToken) return { ...token, error: "RefreshAccessTokenError" };

  try {
    const response = await fetch(`${internal}/protocol/openid-connect/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: clientId,
        client_secret: clientSecret,
        refresh_token: token.refreshToken,
      }),
      cache: "no-store",
    });
    const refreshed = await response.json();
    if (!response.ok) throw new Error(refreshed?.error ?? "refresh_failed");

    return {
      ...token,
      accessToken: refreshed.access_token,
      // Keycloak rotates the refresh token; keeping the old one would fail next time.
      refreshToken: refreshed.refresh_token ?? token.refreshToken,
      idToken: refreshed.id_token ?? token.idToken,
      expiresAt: Math.floor(Date.now() / 1000) + Number(refreshed.expires_in ?? 0),
      error: undefined,
    };
  } catch {
    // No detail in the token: the reason belongs in the server log, and the user
    // only needs to land back on /login.
    return { ...token, error: "RefreshAccessTokenError" };
  }
}

function config(): NextAuthConfig {
  const { issuer, internal, clientId, clientSecret } = realm();

  return {
    // The BFF runs behind the compose network under its service name; without
    // this Auth.js refuses to trust the forwarded host.
    trustHost: true,
    session: { strategy: "jwt" },
    pages: { signIn: "/login" },
    providers: [
      Keycloak({
        clientId,
        clientSecret,
        issuer,
        authorization: {
          url: `${issuer}/protocol/openid-connect/auth`,
          params: { scope: "openid email profile" },
        },
        token: `${internal}/protocol/openid-connect/token`,
        userinfo: `${internal}/protocol/openid-connect/userinfo`,
      }),
    ],
    callbacks: {
      async jwt({ token, account }) {
        if (account) {
          return {
            ...token,
            accessToken: account.access_token,
            refreshToken: account.refresh_token,
            idToken: account.id_token,
            expiresAt: account.expires_at,
            error: undefined,
          };
        }
        const expiresAt = token.expiresAt ?? 0;
        if (Date.now() < (expiresAt - REFRESH_SKEW_SECONDS) * 1000) return token;
        return refreshAccessToken(token);
      },
      session({ session, token }) {
        // Name and e-mail only. The access token stays in the encrypted cookie,
        // reachable exclusively through `getAccessToken()` on the server.
        session.error = token.error;
        return session;
      },
    },
    events: {
      async signOut(message) {
        // RP-initiated logout: without it the Keycloak SSO session survives and
        // the next sign-in silently skips the login screen.
        const idToken = "token" in message ? message.token?.idToken : undefined;
        if (!idToken) return;
        const url = new URL(`${internal}/protocol/openid-connect/logout`);
        url.searchParams.set("id_token_hint", idToken);
        await fetch(url, { cache: "no-store" }).catch(() => undefined);
      },
    },
  };
}

// `config()` and not `config`: with the lazy form Auth.js returns a *promise* of
// the middleware, which `proxy.ts` cannot call. Nothing here throws when the
// environment is missing, so `next build` still runs without secrets.
export const { handlers, auth, signIn, signOut } = NextAuth(config());
