/**
 * `onRequestError` — a única fronteira onde o Next entrega o erro do servidor
 * antes de saneá-lo para o cliente (Fase 5, ADR 0018).
 *
 * É o que faz `app/error.tsx` parar de mentir. A tela dizia "A falha foi
 * registrada" e nada registrava; agora um render que estoura vira uma linha com
 * o `digest` — o mesmo código que a pessoa lê na tela e pode repetir ao
 * suporte — e com o `trace_id` que atravessou a API, quando o erro veio de uma
 * chamada nossa (`TracedError`).
 */

import { logError, traceIdOf } from "@/app/lib/log";

type ErrorRequest = {
  path?: string;
  method?: string;
  headers?: Record<string, string | undefined>;
};

type ErrorContext = {
  routerKind?: string;
  routePath?: string;
  renderSource?: string;
};

export function onRequestError(
  error: unknown,
  request: ErrorRequest,
  context: ErrorContext,
): void {
  const digest =
    typeof error === "object" && error !== null && "digest" in error
      ? String((error as { digest?: unknown }).digest ?? "")
      : "";

  logError("web.request_error", {
    // O `digest` é o que o cliente vê como "Código" na fronteira de erro. Sem
    // ele a pessoa só consegue dizer "deu erro", e o log só consegue responder
    // "vários deram".
    digest,
    trace_id: traceIdOf(error) || request.headers?.["x-request-id"] || "",
    // A rota, não a URL: o path traz id de projeto e de documento, e a mesma
    // regra do `_route_of` da API vale aqui.
    route: context.routePath ?? request.path ?? "",
    method: request.method ?? "",
    render_source: context.renderSource ?? "",
    message: error instanceof Error ? error.message : String(error),
  });
}
