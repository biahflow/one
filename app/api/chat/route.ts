// BFF proxy for the contextual chat (Fase 3). Injects the client identity server-side
// (X-Portal-User) and forwards to the FastAPI /api/v1/chat — the browser never sees the API
// URL or the identity header, and there's no CORS since this runs on the server.

export async function POST(request: Request): Promise<Response> {
  const base = process.env.API_BASE_URL;
  const email = process.env.PORTAL_CLIENT_EMAIL ?? "marina.farias@acme.com.br";

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
      headers: { "Content-Type": "application/json", "X-Portal-User": email },
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
