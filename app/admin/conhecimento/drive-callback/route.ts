import { NextResponse, type NextRequest } from "next/server";

import { authorizationHeader } from "@/app/lib/session";

/**
 * Volta do consentimento do Google (ADR 0016).
 *
 * **Por que no BFF e não na API.** O `redirect_uri` registrado no Google é um
 * endereço que o *navegador* visita, e em produção a API não é publicamente
 * roteável (`API_BASE_URL: http://api:8000`, rede interna do compose). Não existe
 * endereço da API que o Google possa mandar o navegador visitar. Além disso, a
 * API continuaria precisando de uma rota sem `principal` — e a de
 * `POST /api/v1/agent-events` deve seguir sendo a única exceção.
 *
 * **Por que fora de `/api/`.** O `proxy.ts` responde 401 **JSON** a tudo sob
 * `/api/` e só redireciona para `/login` fora dele. Isto aqui é uma navegação de
 * topo vinda de outro site: se a sessão expirar enquanto a pessoa está na tela de
 * consentimento do Google, `/api/drive/callback` entregaria um JSON de erro no
 * lugar da tela de login. Aqui ela cai no login e recomeça.
 *
 * O cookie de sessão do Auth.js é `SameSite=Lax`, que **é** enviado em navegação
 * de topo cross-site por GET — que é exatamente esta. Trocar para `Strict`
 * quebraria este fluxo com um erro que parece CSRF legítimo.
 *
 * O que este arquivo **não** faz é trocar o código por tokens. Isso acontece na
 * API, que é onde moram o `client_secret` do Google e a chave de cifra: fazer o
 * exchange aqui traria o refresh token em claro para o BFF sem necessidade
 * nenhuma.
 *
 * O destino é sempre um caminho relativo fixo. Um `next` vindo da query
 * transformaria o callback em open redirect.
 */
export async function GET(request: NextRequest) {
  const home = new URL("/admin/conhecimento", request.nextUrl.origin);
  const params = request.nextUrl.searchParams;

  // A pessoa recusou na tela do Google, ou o Google recusou o pedido.
  const error = params.get("error");
  if (error) {
    home.searchParams.set("drive", error === "access_denied" ? "denied" : "error");
    return NextResponse.redirect(home);
  }

  const code = params.get("code");
  const state = params.get("state");
  if (!code || !state) {
    home.searchParams.set("drive", "error");
    return NextResponse.redirect(home);
  }

  const base = process.env.API_BASE_URL;
  const authorization = await authorizationHeader();
  if (!base || !authorization) {
    home.searchParams.set("drive", "error");
    return NextResponse.redirect(home);
  }

  try {
    const response = await fetch(`${base}/api/v1/admin/drive/callback`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authorization },
      body: JSON.stringify({ code, state }),
      cache: "no-store",
    });
    if (!response.ok) {
      home.searchParams.set("drive", response.status === 400 ? "scope" : "error");
      return NextResponse.redirect(home);
    }
    const connection = (await response.json()) as { project_id: string | null };
    if (connection.project_id) home.searchParams.set("project", connection.project_id);
    home.searchParams.set("drive", "connected");
  } catch {
    home.searchParams.set("drive", "error");
  }
  return NextResponse.redirect(home);
}
