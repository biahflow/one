// BFF proxy for the contextual chat (Fase 3). Forwards to the FastAPI /api/v1/chat — the
// browser never sees the API URL, and there's no CORS since this runs on the server.
// The caller's identity travels as the OIDC access token read from the session cookie
// (ADR 0010): without one there is nothing to forward, so we answer 401 here rather than
// letting the API decide for an anonymous request.

import { authorizationHeader } from "@/app/lib/session";

export async function POST(request: Request): Promise<Response> {
  const base = process.env.API_BASE_URL;

  const payload = await request.json().catch(() => ({}));
  const question = typeof payload?.question === "string" ? payload.question.trim() : "";
  // A thread a continuar (ADR 0015). Ausente abre uma nova — quem decide isso é a
  // API, então aqui só repassamos: um id inválido não é erro do BFF.
  const conversationId =
    typeof payload?.conversation_id === "string" ? payload.conversation_id : undefined;
  if (!question) {
    return Response.json({ error: "empty question" }, { status: 400 });
  }
  if (!base) {
    return Response.json({ error: "chat unavailable" }, { status: 503 });
  }

  const authorization = await authorizationHeader();
  if (!authorization) {
    return Response.json({ error: "not authenticated" }, { status: 401 });
  }

  try {
    const response = await fetch(`${base}/api/v1/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authorization },
      body: JSON.stringify({ question, conversation_id: conversationId }),
      cache: "no-store",
    });
    if (!response.ok) {
      return Response.json({ error: "chat failed" }, { status: response.status });
    }
    return Response.json(await response.json());
  } catch {
    return Response.json({ error: "chat unavailable" }, { status: 503 });
  }
}
