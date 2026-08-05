"use server";

import { revalidatePath } from "next/cache";

import { signOut } from "@/auth";
import { logWarn } from "@/app/lib/log";
import { authorizationHeader } from "@/app/lib/session";
import { traceId } from "@/app/lib/trace";

/**
 * Sair de verdade: apaga o cookie de sessão e dispara o logout RP-initiated no
 * Keycloak (`events.signOut` em `auth.ts`). Antes disso "Sair" era um booleano
 * de estado, e um F5 devolvia o dashboard.
 */
export async function signOutAction(): Promise<void> {
  await signOut({ redirectTo: "/login" });
}

/**
 * Notificações e preferências, do BFF para a API (ADR 0012).
 *
 * Server Actions pelo mesmo motivo de `app/admin/actions.ts`: o token sai de
 * `authorizationHeader()` no servidor e o navegador só vê o resultado. Nenhuma
 * decisão de permissão acontece aqui — a API é quem autoriza, e ela responde
 * sobre o projeto do próprio chamador.
 */
async function callApi(path: string, init: RequestInit): Promise<boolean> {
  const base = process.env.API_BASE_URL;
  const authorization = await authorizationHeader();
  if (!base || !authorization) return false;

  try {
    const response = await fetch(`${base}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...authorization },
      cache: "no-store",
    });
    if (!response.ok) {
      logWarn("api.rejected", {
        trace_id: await traceId(),
        path,
        status: response.status,
      });
    }
    return response.ok;
  } catch (error) {
    // Este `catch` era mudo: o sino parava de marcar como lido e não sobrava
    // linha nenhuma dizendo por quê (ADR 0018). O `false` continua igual — a
    // ação degrada, não derruba a página —, mas agora deixa rastro.
    logWarn("api.unreachable", {
      trace_id: await traceId(),
      path,
      message: error instanceof Error ? error.message : String(error),
    });
    return false;
  }
}

/** Marca como lidos os avisos do projeto atual. Sem ids, marca todos. */
export async function markNotificationsReadAction(ids?: string[]): Promise<boolean> {
  const ok = await callApi("/api/v1/me/notifications/read", {
    method: "POST",
    body: JSON.stringify({ ids: ids ?? null }),
  });
  // Revalida para o contador do sino vir do servidor no próximo render, em vez
  // de viver como estado de cliente — que era o bug do booleano `notifRead`.
  if (ok) revalidatePath("/");
  return ok;
}

export async function setEmailPreferenceAction(enabled: boolean): Promise<boolean> {
  const ok = await callApi("/api/v1/me/preferences", {
    method: "PATCH",
    body: JSON.stringify({ notify_by_email: enabled }),
  });
  if (ok) revalidatePath("/");
  return ok;
}
