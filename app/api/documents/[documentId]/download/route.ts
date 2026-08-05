// BFF proxy da URL temporária do documento (Fase 5, ADR 0017). Mesma forma dos
// proxies do chat e do histórico: o navegador não vê a URL da API e a identidade
// viaja no access token lido do cookie de sessão (ADR 0010).
//
// O que atravessa é o *endereço assinado*, não o arquivo. O download em si vai do
// storage direto para o navegador, sem passar por aqui — um PDF de 25 MiB não tem
// por que atravessar dois processos Node só para chegar à aba do cliente.
//
// Aqui não se degrada, ao contrário do histórico ao lado: um link de documento que
// falha em silêncio faria a citação parecer clicável e não abrir nada. O erro sobe,
// e a tela decide o que dizer.

import { authorizationHeader } from "@/app/lib/session";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ documentId: string }> },
): Promise<Response> {
  const base = process.env.API_BASE_URL;
  if (!base) {
    return Response.json({ error: "download unavailable" }, { status: 503 });
  }

  const authorization = await authorizationHeader();
  if (!authorization) {
    return Response.json({ error: "not authenticated" }, { status: 401 });
  }

  const { documentId } = await params;

  try {
    const response = await fetch(
      `${base}/api/v1/me/documents/${encodeURIComponent(documentId)}/download`,
      { headers: { ...authorization }, cache: "no-store" },
    );
    if (!response.ok) {
      // 404 é a negação do portal e chega aqui como 404 — a tela não distingue
      // "não existe" de "não é seu", porque a API também não.
      return Response.json({ error: "download failed" }, { status: response.status });
    }
    return Response.json(await response.json());
  } catch {
    return Response.json({ error: "download unavailable" }, { status: 503 });
  }
}
