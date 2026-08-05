// BFF proxy da busca do projeto (Fase 6, ADR 0024). Espelho de `app/api/chat/route.ts`:
// o navegador nunca vê a URL da API, não há CORS porque isto roda no servidor, e a
// identidade viaja no access token lido do cookie de sessão (ADR 0010) — sem sessão não
// há o que repassar, então o 401 sai daqui em vez de a API decidir por um anônimo.
//
// O termo **não** é registrado em lugar nenhum, nem aqui nem na API: é conteúdo do
// cliente (`docs/data-classification.md`).

import { authorizationHeader } from "@/app/lib/session";

export async function GET(request: Request): Promise<Response> {
  const base = process.env.API_BASE_URL;
  const q = new URL(request.url).searchParams.get("q")?.trim() ?? "";

  // Sem termo não se chama a API: a resposta é a mesma lista vazia, e uma tecla
  // apagada não precisa de ida ao servidor. Quem decide o mínimo é a API
  // (`search.MIN_QUERY_LENGTH`) — aqui só se evita a chamada obviamente inútil.
  if (!q) {
    return Response.json({ results: [] });
  }
  if (!base) {
    return Response.json({ error: "search unavailable" }, { status: 503 });
  }

  const authorization = await authorizationHeader();
  if (!authorization) {
    return Response.json({ error: "not authenticated" }, { status: 401 });
  }

  try {
    const response = await fetch(
      `${base}/api/v1/me/search?q=${encodeURIComponent(q)}`,
      { headers: authorization, cache: "no-store" },
    );
    if (!response.ok) {
      return Response.json({ error: "search failed" }, { status: response.status });
    }
    return Response.json(await response.json());
  } catch {
    return Response.json({ error: "search unavailable" }, { status: 503 });
  }
}
