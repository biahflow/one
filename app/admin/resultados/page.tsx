import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { authorizationHeader } from "@/app/lib/session";

import ResultsAdminClient, {
  type AgentKey,
  type Assumption,
} from "./ResultsAdminClient";

// Como o resto da administração: por usuário e por requisição.
export const dynamic = "force-dynamic";

type ApiMe = {
  is_internal: boolean;
  organization: string | null;
  projects: { id: string; name: string; slug: string; status: string }[];
};

type ApiKey = {
  key_id: string;
  name: string;
  key_prefix: string;
  expires_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  usable: boolean;
};

type ApiAssumption = {
  assumption_id: string;
  effective_from: string;
  effective_to: string | null;
  hourly_rate_cents: number;
  monthly_investment_cents: number;
  currency: string;
  note: string | null;
};

/**
 * As duas coisas de que o número da aba Resultados depende (ADR 0013).
 *
 * Ficam juntas porque só fazem sentido juntas: a chave é por onde o resultado
 * entra, a premissa é o que o converte em dinheiro. Configurar uma sem a outra
 * produz ou eventos que não viram valor, ou um valor sem evento.
 *
 * O `notFound()` para quem não é interno é ergonomia, não segurança — a API
 * responde 404 a quem não tem `internal_admin` no projeto, e é ela a autoridade.
 */
export default async function ResultsAdminPage({
  searchParams,
}: {
  searchParams: Promise<{ project?: string }>;
}) {
  const base = process.env.API_BASE_URL;
  const session = await auth();
  const authorization = await authorizationHeader();
  if (!base || !session || session.error || !authorization) redirect("/login");

  const meResponse = await fetch(`${base}/api/v1/me`, {
    headers: authorization,
    cache: "no-store",
  });
  if (meResponse.status === 401) redirect("/login");
  if (!meResponse.ok) throw new Error(`GET /api/v1/me respondeu ${meResponse.status}`);

  const me: ApiMe = await meResponse.json();
  if (!me.is_internal || me.projects.length === 0) notFound();

  const { project: requested } = await searchParams;
  const project =
    me.projects.find((candidate) => candidate.id === requested) ?? me.projects[0];

  const [keysResponse, assumptionsResponse] = await Promise.all([
    fetch(`${base}/api/v1/admin/projects/${project.id}/keys`, {
      headers: authorization,
      cache: "no-store",
    }),
    fetch(`${base}/api/v1/admin/projects/${project.id}/assumptions`, {
      headers: authorization,
      cache: "no-store",
    }),
  ]);
  // 404 aqui é "você não é internal_admin neste projeto" — a mesma resposta que
  // um projeto inexistente daria, de propósito.
  if (keysResponse.status === 404 || assumptionsResponse.status === 404) notFound();
  if (!keysResponse.ok) throw new Error(`GET keys respondeu ${keysResponse.status}`);
  if (!assumptionsResponse.ok) {
    throw new Error(`GET assumptions respondeu ${assumptionsResponse.status}`);
  }

  const keys: AgentKey[] = ((await keysResponse.json()) as ApiKey[]).map((key) => ({
    keyId: key.key_id,
    name: key.name,
    keyPrefix: key.key_prefix,
    expiresAt: key.expires_at,
    revoked: key.revoked_at !== null,
    // "Expirada" é derivado, não observado: a API já decidiu se a chave ainda
    // autentica, e é o relógio dela que vale.
    expired: !key.usable && key.revoked_at === null,
    lastUsedAt: key.last_used_at,
  }));

  const assumptions: Assumption[] = (
    (await assumptionsResponse.json()) as ApiAssumption[]
  ).map((item) => ({
    assumptionId: item.assumption_id,
    effectiveFrom: item.effective_from,
    effectiveTo: item.effective_to,
    hourlyRate: item.hourly_rate_cents / 100,
    monthlyInvestment: item.monthly_investment_cents / 100,
    currency: item.currency,
    note: item.note,
  }));

  return (
    <ResultsAdminClient
      organization={me.organization ?? ""}
      projects={me.projects.map((candidate) => ({
        id: candidate.id,
        name: candidate.name,
        current: candidate.id === project.id,
      }))}
      projectName={project.name}
      projectId={project.id}
      keys={keys}
      assumptions={assumptions}
    />
  );
}
