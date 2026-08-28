"use server";

import { revalidatePath } from "next/cache";

import { authorizationHeader } from "@/app/lib/session";

/**
 * Convite e revogação, do BFF para a API (ADR 0011).
 *
 * Server Actions e não uma rota de BFF nova: o token sai de
 * `authorizationHeader()` no servidor e o navegador só vê o resultado. A API é
 * quem autoriza — aqui não há nenhuma decisão de permissão, só o encaminhamento.
 */

export type ActionResult = { ok: true } | { ok: false; error: string };
/** Quando a resposta da API importa para a tela — o caso da chave em claro. */
export type DataResult<T> = { ok: true; data: T } | { ok: false; error: string };

const GENERIC_ERROR = "Não foi possível concluir. Tente novamente.";

async function request<T>(
  path: string,
  init: RequestInit,
  messages: Record<number, string> = {},
): Promise<DataResult<T | null>> {
  const base = process.env.API_BASE_URL;
  const authorization = await authorizationHeader();
  if (!base || !authorization) return { ok: false, error: GENERIC_ERROR };

  try {
    const response = await fetch(`${base}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...authorization },
      cache: "no-store",
    });
    if (response.ok) {
      revalidatePath("/admin");
      revalidatePath("/admin/results");
      revalidatePath("/admin/knowledge");
      revalidatePath("/admin/organization");
      const data = response.status === 204 ? null : ((await response.json()) as T);
      return { ok: true, data };
    }
    // 404 é a negação do portal (nunca 403) e chega aqui como "não encontrado";
    // não vale a pena distinguir para o usuário: em ambos os casos ele não
    // deveria estar vendo esta tela.
    const mapped = messages[response.status];
    if (mapped) return { ok: false, error: mapped };
    if (response.status === 502) {
      return { ok: false, error: "O provedor de identidade não respondeu. Tente de novo." };
    }
    return { ok: false, error: GENERIC_ERROR };
  } catch {
    return { ok: false, error: GENERIC_ERROR };
  }
}

async function callApi(
  path: string,
  init: RequestInit,
  messages: Record<number, string> = {},
): Promise<ActionResult> {
  const result = await request<unknown>(path, init, messages);
  return result.ok ? { ok: true } : result;
}

export async function inviteMember(
  projectId: string,
  formData: FormData,
): Promise<ActionResult> {
  const email = String(formData.get("email") ?? "").trim();
  const fullName = String(formData.get("full_name") ?? "").trim();
  const role = String(formData.get("role") ?? "client_member");

  if (!email || !fullName) {
    return { ok: false, error: "Preencha nome e e-mail." };
  }

  return callApi(`/api/v1/admin/projects/${projectId}/members`, {
    method: "POST",
    body: JSON.stringify({ email, full_name: fullName, role }),
  });
}

export async function revokeMembership(
  projectId: string,
  membershipId: string,
): Promise<ActionResult> {
  return callApi(
    `/api/v1/admin/projects/${projectId}/members/${membershipId}`,
    { method: "DELETE" },
    { 409: "Você não pode remover o seu próprio acesso." },
  );
}

/**
 * Chaves dos agentes e premissas financeiras (ADR 0013).
 *
 * A chave em claro atravessa daqui para a tela **uma vez**: a API só a devolve
 * na criação, e não há como recuperá-la depois. Por isso estas são as únicas
 * ações que carregam corpo de volta.
 */

export type CreatedKey = { key: string; key_prefix: string; name: string };

export async function createAgentKey(
  projectId: string,
  formData: FormData,
): Promise<DataResult<CreatedKey | null>> {
  const name = String(formData.get("name") ?? "").trim();
  if (!name) return { ok: false, error: "Dê um nome à chave." };

  return request<CreatedKey>(`/api/v1/admin/projects/${projectId}/keys`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function rotateAgentKey(
  projectId: string,
  keyId: string,
): Promise<DataResult<CreatedKey | null>> {
  return request<CreatedKey>(
    `/api/v1/admin/projects/${projectId}/keys/${keyId}/rotate`,
    { method: "POST" },
  );
}

export async function revokeAgentKey(
  projectId: string,
  keyId: string,
): Promise<ActionResult> {
  return callApi(`/api/v1/admin/projects/${projectId}/keys/${keyId}`, {
    method: "DELETE",
  });
}

/**
 * Conhecimento do projeto (Fase 4, ADR 0014).
 *
 * O upload é a única ação que não fala JSON: o arquivo atravessa como multipart,
 * e por isso ela não passa pelo `request()` acima — quem define o `boundary` do
 * corpo é o próprio fetch, e fixar `Content-Type` aqui o quebraria.
 */

const MAX_UPLOAD_MESSAGES: Record<number, string> = {
  413: "Arquivo grande demais para o portal.",
  415: "Formato não suportado. Envie PDF, DOCX, TXT, Markdown ou CSV.",
  422: "O arquivo está vazio.",
  502: "O storage de documentos não respondeu. Tente de novo.",
  503: "O storage de documentos não está configurado neste ambiente.",
};

export async function uploadDocument(
  projectId: string,
  formData: FormData,
): Promise<ActionResult> {
  const base = process.env.API_BASE_URL;
  const authorization = await authorizationHeader();
  if (!base || !authorization) return { ok: false, error: GENERIC_ERROR };

  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return { ok: false, error: "Escolha um arquivo." };
  }

  const body = new FormData();
  body.append("file", file);
  body.append("title", String(formData.get("title") ?? "").trim());

  try {
    const response = await fetch(`${base}/api/v1/admin/projects/${projectId}/documents`, {
      method: "POST",
      headers: authorization,
      body,
      cache: "no-store",
    });
    if (response.ok) {
      revalidatePath("/admin/knowledge");
      return { ok: true };
    }
    return { ok: false, error: MAX_UPLOAD_MESSAGES[response.status] ?? GENERIC_ERROR };
  } catch {
    return { ok: false, error: GENERIC_ERROR };
  }
}

export async function deleteDocument(
  projectId: string,
  documentId: string,
): Promise<ActionResult> {
  return callApi(`/api/v1/admin/projects/${projectId}/documents/${documentId}`, {
    method: "DELETE",
  });
}

/**
 * Conector do Google Drive (Fase 4, ADR 0016).
 *
 * Nenhuma destas ações vê o refresh token: o code exchange acontece na API, que
 * é onde moram o `client_secret` do Google e a chave de cifra. O que atravessa o
 * BFF é o `code` e o `state`, e só no sentido navegador → API.
 */

const DRIVE_MESSAGES: Record<number, string> = {
  409: "A autorização do Drive não vale mais. Reconecte a pasta.",
  502: "O Google não respondeu. Tente de novo.",
  503: "O conector do Google Drive não está configurado neste ambiente.",
};

export type DriveAuthorization = { authorize_url: string };
export type DriveFolder = { id: string; name: string };

export async function startDriveAuthorization(
  projectId: string,
): Promise<DataResult<DriveAuthorization | null>> {
  return request<DriveAuthorization>(
    `/api/v1/admin/projects/${projectId}/drive/authorize-url`,
    { method: "POST" },
    DRIVE_MESSAGES,
  );
}

export async function listDriveFolders(
  projectId: string,
): Promise<DataResult<DriveFolder[] | null>> {
  return request<DriveFolder[]>(
    `/api/v1/admin/projects/${projectId}/drive/folders`,
    { method: "GET" },
    DRIVE_MESSAGES,
  );
}

export async function setDriveFolder(
  projectId: string,
  folderId: string,
): Promise<ActionResult> {
  if (!folderId) return { ok: false, error: "Escolha uma pasta." };
  return callApi(
    `/api/v1/admin/projects/${projectId}/drive/folder`,
    { method: "PUT", body: JSON.stringify({ folder_id: folderId }) },
    DRIVE_MESSAGES,
  );
}

export async function syncDriveNow(projectId: string): Promise<ActionResult> {
  return callApi(
    `/api/v1/admin/projects/${projectId}/drive/sync`,
    { method: "POST" },
    { ...DRIVE_MESSAGES, 409: "Uma sincronização já está em andamento." },
  );
}

export async function disconnectDrive(projectId: string): Promise<ActionResult> {
  return callApi(
    `/api/v1/admin/projects/${projectId}/drive`,
    { method: "DELETE" },
    DRIVE_MESSAGES,
  );
}

export async function openAssumption(
  projectId: string,
  formData: FormData,
): Promise<ActionResult> {
  const effectiveFrom = String(formData.get("effective_from") ?? "").trim();
  // A tela pede reais; a API fala centavos, porque o cálculo não pode carregar
  // erro de ponto flutuante.
  const hourlyRate = Number(formData.get("hourly_rate") ?? NaN);
  const investment = Number(formData.get("monthly_investment") ?? NaN);
  const note = String(formData.get("note") ?? "").trim();

  if (!effectiveFrom || Number.isNaN(hourlyRate) || Number.isNaN(investment)) {
    return { ok: false, error: "Preencha vigência, valor-hora e investimento." };
  }
  if (hourlyRate < 0 || investment < 0) {
    return { ok: false, error: "Valores não podem ser negativos." };
  }

  return callApi(
    `/api/v1/admin/projects/${projectId}/assumptions`,
    {
      method: "POST",
      body: JSON.stringify({
        effective_from: effectiveFrom,
        hourly_rate_cents: Math.round(hourlyRate * 100),
        monthly_investment_cents: Math.round(investment * 100),
        note: note || null,
      }),
    },
    {
      409: "A vigência precisa começar depois da premissa atual — o histórico não é reescrito.",
    },
  );
}

/* -------------------------------------------------------------------------- */
/* A organização inteira (ADR 0027)                                            */
/*                                                                             */
/* Escopo diferente de tudo o que está acima: estas três não levam projeto.    */
/* "Por quanto tempo os dados ficam", "quanto de IA esta organização pode      */
/* gastar" e "apague tudo" não são perguntas que se façam projeto a projeto —  */
/* é o mesmo argumento com que `admin.py` separou as rotas.                    */
/* -------------------------------------------------------------------------- */

/** Vazio é "usa o padrão", nunca "guarda para sempre" — ver `retention.py`. */
function optionalDays(formData: FormData, field: string): number | null | undefined {
  const raw = String(formData.get(field) ?? "").trim();
  if (!raw) return null;
  const value = Number(raw);
  // `undefined` distingue "não é número" de "deixado em branco", e só o
  // primeiro é erro: em branco é uma escolha, e é a escolha padrão.
  if (!Number.isInteger(value) || value < 1 || value > 3650) return undefined;
  return value;
}

export async function setRetentionPolicy(
  organizationId: string,
  formData: FormData,
): Promise<ActionResult> {
  const notification = optionalDays(formData, "notification_days");
  const agentEvent = optionalDays(formData, "agent_event_days");
  const conversation = optionalDays(formData, "conversation_days");

  if (notification === undefined || agentEvent === undefined || conversation === undefined) {
    return { ok: false, error: "Os prazos são inteiros entre 1 e 3650 dias, ou vazio para o padrão." };
  }

  // PUT e não PATCH pela razão da API: o corpo descreve a linha inteira, e
  // omitir um campo é dizer "volte ao padrão" — uma decisão, não um silêncio.
  return callApi(`/api/v1/admin/organizations/${organizationId}/retention`, {
    method: "PUT",
    body: JSON.stringify({
      notification_days: notification,
      agent_event_days: agentEvent,
      conversation_days: conversation,
    }),
  });
}

export async function setAiQuota(
  organizationId: string,
  formData: FormData,
): Promise<ActionResult> {
  const raw = String(formData.get("monthly_limit") ?? "").trim();
  if (!raw) {
    return callApi(`/api/v1/admin/organizations/${organizationId}/ai-quota`, {
      method: "PUT",
      body: JSON.stringify({ monthly_limit_cents: null }),
    });
  }

  // A tela pede reais e a API fala centavos, como na premissa financeira: o
  // dinheiro não pode carregar erro de ponto flutuante (ADR 0013).
  const value = Number(raw.replace(",", "."));
  if (Number.isNaN(value) || value < 0) {
    return { ok: false, error: "O teto é um valor em reais, ou vazio para o padrão." };
  }

  return callApi(`/api/v1/admin/organizations/${organizationId}/ai-quota`, {
    method: "PUT",
    body: JSON.stringify({ monthly_limit_cents: Math.round(value * 100) }),
  });
}

export async function requestErasure(
  organizationId: string,
  formData: FormData,
): Promise<ActionResult> {
  const reason = String(formData.get("reason") ?? "").trim();
  const confirmSlug = String(formData.get("confirm_slug") ?? "").trim();

  if (reason.length < 3) {
    return { ok: false, error: "Diga por que o apagamento foi pedido — isso fica no registro." };
  }
  if (!confirmSlug) {
    return { ok: false, error: "Digite o identificador da organização para confirmar." };
  }

  // O 422 é a única negação do portal que **não** é 404, e é deliberado: quem
  // chegou aqui já provou que administra a organização, e o que falhou foi a
  // confirmação. Esconder isso faria a pessoa tentar de novo às cegas.
  return callApi(
    `/api/v1/admin/organizations/${organizationId}/erasure`,
    {
      method: "POST",
      body: JSON.stringify({ reason, confirm_slug: confirmSlug }),
    },
    {
      422: "O identificador digitado não é o desta organização. Confira qual está na tela.",
    },
  );
}
