/**
 * Session gate (Next 16 calls this file `proxy`; it was `middleware` before).
 *
 * Anything that is not `/login` or an Auth.js route needs a session, and a token
 * whose refresh failed counts as no session — otherwise the user would sit on a
 * dashboard whose every request comes back 401.
 *
 * Pages get a redirect; routes under `/api/` get a 401, because a `fetch()` that
 * follows a redirect would receive the login page as if it were data.
 *
 * This is the outer barrier, not the only one: `app/page.tsx` calls `auth()` on
 * its own, the chat route checks the token before forwarding, and the FastAPI
 * validates it independently (ADR 0010). The portal does not depend on the edge
 * to be closed.
 */

import type { NextAuthRequest } from "next-auth";
import { NextResponse, type NextFetchEvent, type NextRequest } from "next/server";

import { auth } from "@/auth";

/** Declaring the second parameter is what picks the *middleware* overload of
 *  `auth()`; without it TypeScript resolves the route-handler one and the
 *  wrapper below stops type-checking. */
type Gate = (request: NextAuthRequest, event: NextFetchEvent) => Response | undefined;

const gate = auth(((request) => {
  const { pathname } = request.nextUrl;
  if (pathname === "/login") return;
  if (request.auth && !request.auth.error) return;

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "not authenticated" }, { status: 401 });
  }
  return NextResponse.redirect(new URL("/login", request.nextUrl.origin));
}) as Gate);

// Next resolves this file statically and requires a declared function — the
// value returned by `auth()` is only callable at runtime, so it is wrapped.
export default function proxy(request: NextRequest, event: NextFetchEvent) {
  return gate(request, event);
}

export const config = {
  matcher: [
    // Everything except the Auth.js routes (which must stay reachable to sign
    // in) and static assets.
    "/((?!api/auth|_next/static|_next/image|favicon.ico|og.png|.*\\.svg).*)",
  ],
};
