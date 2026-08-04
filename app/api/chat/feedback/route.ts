// BFF proxy da avaliação de uma resposta (Fase 4, ADR 0015).
//
// Quem decide se a mensagem é da pessoa que está avaliando é a API — aqui não há
// verificação de dono, e não deve haver: o frontend não decide autorização
// (AGENTS.md #5). O 404 da API atravessa como veio.

import { authorizationHeader } from "@/app/lib/session";

export async function POST(request: Request): Promise<Response> {
  const base = process.env.API_BASE_URL;

  const payload = await request.json().catch(() => ({}));
  const messageId = typeof payload?.message_id === "string" ? payload.message_id : "";
  const helpful = payload?.helpful;
  if (!messageId || typeof helpful !== "boolean") {
    return Response.json({ error: "invalid feedback" }, { status: 400 });
  }
  if (!base) {
    return Response.json({ error: "feedback unavailable" }, { status: 503 });
  }

  const authorization = await authorizationHeader();
  if (!authorization) {
    return Response.json({ error: "not authenticated" }, { status: 401 });
  }

  try {
    const response = await fetch(
      `${base}/api/v1/me/conversations/messages/${encodeURIComponent(messageId)}/feedback`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authorization },
        body: JSON.stringify({
          helpful,
          comment: typeof payload?.comment === "string" ? payload.comment : null,
        }),
        cache: "no-store",
      },
    );
    if (!response.ok) {
      return Response.json({ error: "feedback failed" }, { status: response.status });
    }
    return Response.json(await response.json());
  } catch {
    return Response.json({ error: "feedback unavailable" }, { status: 503 });
  }
}
