// Auth.js endpoints (sign-in, callback, sign-out, session). The realm accepts a
// single redirect URI, /api/auth/callback/keycloak, which lands here.
import { handlers } from "@/auth";

export const { GET, POST } = handlers;
