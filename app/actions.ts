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

/**
 * A decisão do cliente sobre um entregável (FDD 027, ADR 0077).
 *
 * Server Action pela razão do comentário da pendência: o token sai de
 * `authorizationHeader()` no servidor e o navegador só vê o desfecho. A API é
 * quem autoriza, e ela responde sobre o projeto do próprio chamador.
 *
 * **Não devolve a linha gravada, e isso é escolha.** A resposta do `POST` traz a
 * decisão inteira, mas quem a mostra é o histórico do próximo render — e ele vem
 * do servidor, pelo `revalidatePath` abaixo, exatamente como a contagem do fio da
 * pendência. Espelhar a linha aqui criaria uma segunda fonte para "o que foi
 * decidido", que é a divisão que `deliverable_acceptance.py` existe para não ter.
 */
export type DecisionOutcome =
  | { ok: true }
  | { ok: false; reason: "read_only" | "rate_limited" | "failed" };

/**
 * `callApi` que devolve o **status**, e não só o `ok`.
 *
 * Quarta porta neste arquivo, pela razão que a terceira já escreveu: "o que a tela
 * escreve", "o que ela lê" e "o que o servidor guardou" são perguntas diferentes.
 * Aqui a pergunta é a quarta — *por que* a escrita foi recusada —, e ela existe
 * porque as duas recusas que o cliente consegue entender têm nome: o projeto sem
 * escrita (409, ADR 0036/0037) e o ritmo (429). Qualquer outra vira a mesma frase
 * opaca, que é o que impede a tela de fabricar um motivo que ela não sabe.
 *
 * `null` é "não cheguei a falar com a API": sem base, sem token, ou rede caída.
 */
async function postApiStatus(path: string, body: object): Promise<number | null> {
  const base = process.env.API_BASE_URL;
  const authorization = await authorizationHeader();
  if (!base || !authorization) return null;

  try {
    const response = await fetch(`${base}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authorization },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (!response.ok) {
      logWarn("api.rejected", {
        trace_id: await traceId(),
        path,
        status: response.status,
      });
    }
    return response.status;
  } catch (error) {
    logWarn("api.unreachable", {
      trace_id: await traceId(),
      path,
      message: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}

/**
 * Aprovar a entrega, ou pedir ajuste.
 *
 * O comentário é **opcional em aprovar e esperado em pedir ajuste**, e a espera é
 * da tela: a API aceita os dois sem texto, porque um pedido de ajuste sem
 * comentário continua sendo uma decisão que o time precisa ver. Vazio vira `null`
 * em vez de string vazia — é o mesmo `.strip() or None` do outro lado, e mandar
 * `""` gravaria "comentou nada" em vez de "não comentou".
 */
export async function recordDeliverableDecisionAction(
  externalRef: string,
  action: "accepted" | "changes_requested",
  comment: string,
  projectId?: string | null,
): Promise<DecisionOutcome> {
  const text = comment.trim();
  const status = await postApiStatus(
    `/api/v1/me/deliverables/${encodeURIComponent(externalRef)}/acceptance` +
      projectQuery(projectId),
    { action, comment: text ? text : null },
  );
  if (status === 201) {
    // Revalida para o histórico do próximo render vir do servidor, pela razão do
    // contador do sino e da contagem do fio: a linha é imutável, e a única cópia
    // dela que a tela deve mostrar é a que o banco devolveu.
    revalidatePath("/");
    return { ok: true };
  }
  if (status === 409) return { ok: false, reason: "read_only" };
  if (status === 429) return { ok: false, reason: "rate_limited" };
  return { ok: false, reason: "failed" };
}
