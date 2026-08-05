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
      revalidatePath("/admin/resultados");
      revalidatePath("/admin/conhecimento");
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
      revalidatePath("/admin/conhecimento");
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
