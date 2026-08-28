import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { authorizationHeader } from "@/app/lib/session";

import OrganizationAdminClient, {
  type ErasureRequest,
  type Organization,
  type Quota,
  type RetentionPolicy,
} from "./OrganizationAdminClient";

// Como o resto da administração: por usuário e por requisição.
export const dynamic = "force-dynamic";

type ApiOrganization = { organization_id: string; name: string; slug: string };

type ApiRetention = {
  organization_id: string;
  notification_days: number | null;
  agent_event_days: number | null;
  conversation_days: number | null;
  onboarding_days: number | null;
  effective: Record<string, number>;
};

type ApiQuota = {
  organization_id: string;
  monthly_limit_cents: number | null;
  effective_limit_cents: number;
  spent_cents: number;
  input_tokens: number;
  output_tokens: number;
  calls: number;
  gaps: string[];
};

type ApiErasure = {
  request_id: string;
  organization_id: string;
  state: string;
  requested_reason: string | null;
  created_at: string;
  completed_at: string | null;
  removed: Record<string, number> | null;
  error: string | null;
};

/**
 * A tela das rotas cujo escopo é a organização (ADR 0027).
 *
 * As seis rotas existiam desde as ADRs 0017 e 0022, completas e testadas, e
 * **nenhuma tinha caller possível**: elas são chaveadas por um
 * `organization_id` que nenhuma resposta da API devolvia — `GET /api/v1/me`
 * traz o *nome* da organização, uma string. `GET /api/v1/admin/organizations`
 * é a peça que faltava, e esta página é a primeira coisa a consumi-la.
 *
 * Três painéis por um motivo só: prazo de retenção, teto de gasto de IA e
 * apagamento são as três perguntas que não se fazem projeto a projeto — é o
 * mesmo argumento com que `admin.py` separou estas rotas das demais.
 *
 * O `notFound()` para quem não é interno é ergonomia, não segurança: a API
 * responde 404 a quem não tem `internal_admin` na organização, e é ela a
 * autoridade (ADR 0011).
 */
export default async function OrganizationAdminPage({
  searchParams,
}: {
  searchParams: Promise<{ org?: string }>;
}) {
  const base = process.env.API_BASE_URL;
  const session = await auth();
  const authorization = await authorizationHeader();
  if (!base || !session || session.error || !authorization) redirect("/login");

  const organizationsResponse = await fetch(`${base}/api/v1/admin/organizations`, {
    headers: authorization,
    cache: "no-store",
  });
  if (organizationsResponse.status === 401) redirect("/login");
  if (!organizationsResponse.ok) {
    throw new Error(`GET /api/v1/admin/organizations respondeu ${organizationsResponse.status}`);
  }

  const listed: ApiOrganization[] = await organizationsResponse.json();
  // Lista vazia é 200 nesta rota, e aqui vira 404 na tela: quem não administra
  // organização nenhuma não tem o que ver, e a API já diria 404 no passo abaixo.
  if (listed.length === 0) notFound();

  const { org: requested } = await searchParams;
  const current =
    listed.find((candidate) => candidate.organization_id === requested) ?? listed[0];

  const [retentionResponse, quotaResponse, erasureResponse] = await Promise.all([
    fetch(`${base}/api/v1/admin/organizations/${current.organization_id}/retention`, {
      headers: authorization,
      cache: "no-store",
    }),
    fetch(`${base}/api/v1/admin/organizations/${current.organization_id}/ai-quota`, {
      headers: authorization,
      cache: "no-store",
    }),
    fetch(`${base}/api/v1/admin/organizations/${current.organization_id}/erasure`, {
      headers: authorization,
      cache: "no-store",
    }),
  ]);
  // 404 aqui é "você não é `internal_admin` nesta organização" — a mesma
  // resposta que uma organização inexistente daria, de propósito.
  if ([retentionResponse, quotaResponse, erasureResponse].some((r) => r.status === 404)) {
    notFound();
  }
  for (const [name, response] of [
    ["retention", retentionResponse],
    ["ai-quota", quotaResponse],
    ["erasure", erasureResponse],
  ] as const) {
    if (!response.ok) throw new Error(`GET ${name} respondeu ${response.status}`);
  }

  const apiRetention: ApiRetention = await retentionResponse.json();
  const apiQuota: ApiQuota = await quotaResponse.json();
  const apiErasures: ApiErasure[] = await erasureResponse.json();

  const retention: RetentionPolicy = {
    notificationDays: apiRetention.notification_days,
    agentEventDays: apiRetention.agent_event_days,
    conversationDays: apiRetention.conversation_days,
    onboardingDays: apiRetention.onboarding_days,
    effective: apiRetention.effective,
  };

  const quota: Quota = {
    monthlyLimit:
      apiQuota.monthly_limit_cents === null ? null : apiQuota.monthly_limit_cents / 100,
    effectiveLimit: apiQuota.effective_limit_cents / 100,
    spent: apiQuota.spent_cents / 100,
    inputTokens: apiQuota.input_tokens,
    outputTokens: apiQuota.output_tokens,
    calls: apiQuota.calls,
    gaps: apiQuota.gaps,
  };

  const erasures: ErasureRequest[] = apiErasures.map((item) => ({
    requestId: item.request_id,
    state: item.state,
    reason: item.requested_reason,
    createdAt: item.created_at,
    completedAt: item.completed_at,
    removed: item.removed,
    error: item.error,
  }));

  const organizations: Organization[] = listed.map((item) => ({
    id: item.organization_id,
    name: item.name,
    slug: item.slug,
    current: item.organization_id === current.organization_id,
  }));

  return (
    <OrganizationAdminClient
      organizations={organizations}
      organizationId={current.organization_id}
      organizationName={current.name}
      organizationSlug={current.slug}
      retention={retention}
      quota={quota}
      erasures={erasures}
    />
  );
}
