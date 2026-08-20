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

/**
 * O projeto que a tela está mostrando, no formato de query (ADR 0059).
 *
 * As três ações abaixo resolviam `access.default_project` do outro lado — a
 * membership **mais recente** —, então um cliente com dois projetos marcava como
 * lido o sino do projeto errado e abria os comentários de uma pendência do
 * projeto certo recebendo 404, porque o item era procurado sob o tenant do outro.
 *
 * **Vazio é omitido, nunca mandado**: `?project=` sem valor é 422 do outro lado, e
 * ausente é o padrão de sempre. Escrito aqui e não num módulo compartilhado de
 * propósito — quem chama a rota é quem tem de mostrar que manda o parâmetro.
 */
function projectQuery(projectId?: string | null): string {
  return projectId ? `?project=${encodeURIComponent(projectId)}` : "";
}

/** Marca como lidos os avisos do projeto na tela. Sem ids, marca todos. */
export async function markNotificationsReadAction(
  projectId?: string | null,
  ids?: string[],
): Promise<boolean> {
  const ok = await callApi("/api/v1/me/notifications/read" + projectQuery(projectId), {
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

/**
 * O estado das preferências como o **servidor** o guardou (FDD 021, ADR 0043).
 *
 * As ações do canal devolvem isto em vez de um booleano, e a diferença não é
 * cosmética: o telefone é normalizado do outro lado (só dígitos) e o `phone_hint`
 * é derivado de lá. Uma tela que calculasse o próprio "••••1234" a partir do que
 * foi digitado estaria reimplementando `_phone_hint`, e as duas divergiriam no
 * primeiro formato que alguém colar — foi a guarda de consumo do contrato que
 * cobrou, e ela estava certa.
 */
/**
 * `callApi` que devolve o corpo, não só o `ok`.
 *
 * Existe porque `readApi` (abaixo) é `GET` sem `init` e `callApi` descarta a
 * resposta — e aqui a resposta **é** o resultado: o servidor devolve o que
 * guardou. Uma terceira porta em vez de alargar uma das duas, pela razão de sempre
 * neste arquivo: "o que a tela escreve" e "o que a tela lê" são perguntas
 * diferentes, e um helper que faz as duas responde mal às duas.
 */
async function callApiJson<T>(path: string, init: RequestInit): Promise<T | null> {
  const base = process.env.API_BASE_URL;
  const authorization = await authorizationHeader();
  if (!base || !authorization) return null;

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
      return null;
    }
    return (await response.json()) as T;
  } catch (error) {
    logWarn("api.unreachable", {
      trace_id: await traceId(),
      path,
      message: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}

export type ChannelPreferences = {
  notifyByEmail: boolean;
  notifyByWhatsapp: boolean;
  phoneHint: string;
};

async function patchPreferences(body: object): Promise<ChannelPreferences | null> {
  const data = await callApiJson<{
    notify_by_email: boolean;
    notify_by_whatsapp: boolean;
    phone_hint: string;
  }>("/api/v1/me/preferences", { method: "PATCH", body: JSON.stringify(body) });
  if (!data) return null;
  revalidatePath("/");
  return {
    notifyByEmail: data.notify_by_email,
    notifyByWhatsapp: data.notify_by_whatsapp,
    phoneHint: data.phone_hint,
  };
}

/**
 * O consentimento do canal de WhatsApp.
 *
 * Ação separada da do e-mail e **não** um parâmetro a mais dela: são dois
 * interruptores independentes na tela, e um PATCH que mandasse os dois faria o
 * clique num deles reescrever o outro com o que a tela achava que ele era.
 *
 * `null` inclui o 422 de ligar o canal sem número cadastrado, que é recusa
 * deliberada — a tela volta o interruptor e diz o motivo.
 */
export async function setWhatsappPreferenceAction(
  enabled: boolean,
): Promise<ChannelPreferences | null> {
  return patchPreferences({ notify_by_whatsapp: enabled });
}

/**
 * O telefone do canal. String vazia apaga o número.
 *
 * A API valida (dez a quinze dígitos) e responde 422 ao que não passa, então um
 * `null` aqui é "não guardei" e a tela mantém o que estava — nunca um número
 * meio gravado.
 */
export async function setPhoneAction(phone: string): Promise<ChannelPreferences | null> {
  return patchPreferences({ phone });
}

/**
 * Comentários na pendência (ADR 0032).
 *
 * A leitura é uma Server Action e não um proxy de rota como o do chat: o fio abre
 * por clique numa tela que já é um componente cliente, e não há streaming nem
 * debounce a justificar a rota — a busca (ADR 0024) precisou de uma porque digita
 * a cada tecla.
 */
export type PendingComment = {
  id: string;
  author_label: string;
  author_is_internal: boolean;
  body: string;
  created_at: string;
};

async function readApi<T>(path: string): Promise<T | null> {
  const base = process.env.API_BASE_URL;
  const authorization = await authorizationHeader();
  if (!base || !authorization) return null;

  try {
    const response = await fetch(`${base}${path}`, {
      headers: { ...authorization },
      cache: "no-store",
    });
    if (!response.ok) {
      logWarn("api.rejected", { trace_id: await traceId(), path, status: response.status });
      return null;
    }
    return (await response.json()) as T;
  } catch (error) {
    logWarn("api.unreachable", {
      trace_id: await traceId(),
      path,
      message: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}

export async function listPendingCommentsAction(
  pendingItemId: string,
  projectId?: string | null,
): Promise<PendingComment[] | null> {
  const body = await readApi<{ items: PendingComment[] }>(
    `/api/v1/me/pendings/${encodeURIComponent(pendingItemId)}/comments` +
      projectQuery(projectId),
  );
  return body ? body.items : null;
}

export async function addPendingCommentAction(
  pendingItemId: string,
  body: string,
  projectId?: string | null,
): Promise<boolean> {
  const text = body.trim();
  if (!text) return false;
  const ok = await callApi(
    `/api/v1/me/pendings/${encodeURIComponent(pendingItemId)}/comments` +
      projectQuery(projectId),
    { method: "POST", body: JSON.stringify({ body: text }) },
  );
  // Revalida para a contagem do fio vir do servidor no próximo render, pela
  // mesma razão do contador do sino.
  if (ok) revalidatePath("/");
  return ok;
}
