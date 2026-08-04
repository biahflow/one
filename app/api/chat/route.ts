// BFF proxy for the contextual chat (Fase 3). Forwards to the FastAPI /api/v1/chat — the
// browser never sees the API URL, and there's no CORS since this runs on the server.
// The caller's identity travels as a Bearer token, which lands with Auth.js (Fase 1,
// etapa 8); until then the API answers 401 and the client falls back to the offline chat.

export async function POST(request: Request): Promise<Response> {
  const base = process.env.API_BASE_URL;

  const payload = await request.json().catch(() => ({}));
  const question = typeof payload?.question === "string" ? payload.question.trim() : "";
  if (!question) {
    return Response.json({ error: "empty question" }, { status: 400 });
  }
  if (!base) {
    return Response.json({ error: "chat unavailable" }, { status: 503 });
  }

  try {
    const response = await fetch(`${base}/api/v1/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
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
