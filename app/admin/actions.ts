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

const GENERIC_ERROR = "Não foi possível concluir. Tente novamente.";

async function callApi(
  path: string,
  init: RequestInit,
): Promise<ActionResult> {
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
      return { ok: true };
    }
    // 404 é a negação do portal (nunca 403) e chega aqui como "não encontrado";
    // não vale a pena distinguir para o usuário: em ambos os casos ele não
    // deveria estar vendo esta tela.
    if (response.status === 409) {
      return { ok: false, error: "Você não pode remover o seu próprio acesso." };
    }
    if (response.status === 502) {
      return { ok: false, error: "O provedor de identidade não respondeu. Tente de novo." };
    }
    return { ok: false, error: GENERIC_ERROR };
  } catch {
    return { ok: false, error: GENERIC_ERROR };
  }
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
  return callApi(`/api/v1/admin/projects/${projectId}/members/${membershipId}`, {
    method: "DELETE",
  });
}
