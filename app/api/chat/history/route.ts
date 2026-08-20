// BFF proxy do histórico da conversa (Fase 4, ADR 0015). Mesma forma do proxy do
// chat ao lado: o navegador não vê a URL da API e a identidade viaja no access
// token lido do cookie de sessão (ADR 0010).
//
// Degradar aqui é de propósito. Sem API — ou com ela fora do ar — o chat continua
// abrindo com a saudação e o fallback offline; devolver erro faria o painel
// inteiro deixar de abrir por causa de um histórico que talvez nem exista.

import { authorizationHeader } from "@/app/lib/session";

/**
 * O projeto que a tela está mostrando, quando ela sabe qual é (ADR 0059).
 *
 * Repassado como veio: quem valida o vínculo é a API (`access.chosen_project`),
 * e o frontend não decide autorização. **Omitido quando não há projeto**, nunca
 * mandado vazio — `?project=` sem valor é 422, não é "sem parâmetro".
 */
function projectQuery(request: Request): string {
  const project = new URL(request.url).searchParams.get("project")?.trim();
  return project ? `?project=${encodeURIComponent(project)}` : "";
}

export async function GET(request: Request): Promise<Response> {
  const base = process.env.API_BASE_URL;
  if (!base) {
    return Response.json({ error: "history unavailable" }, { status: 503 });
  }

  const authorization = await authorizationHeader();
  if (!authorization) {
    return Response.json({ error: "not authenticated" }, { status: 401 });
  }

  // `?conversation=<uuid>` abre uma thread nomeada em vez da corrente (ADR 0031):
  // a pendência aberta pela IA aponta um turno que quase nunca está na conversa
  // mais recente. Sem id, o comportamento é o de sempre.
  const requested = new URL(request.url).searchParams.get("conversation");
  const path =
    requested && /^[0-9a-f-]{36}$/i.test(requested)
      ? `/api/v1/me/conversations/${requested}`
      : "/api/v1/me/conversations/latest";

  try {
    const response = await fetch(`${base}${path}` + projectQuery(request), {
      headers: { ...authorization },
      cache: "no-store",
    });
    if (!response.ok) {
      return Response.json({ error: "history failed" }, { status: response.status });
    }
    return Response.json(await response.json());
  } catch {
    return Response.json({ error: "history unavailable" }, { status: 503 });
  }
}
