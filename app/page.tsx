import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { demoShellEnabled } from "@/app/lib/demo";
import { TracedError, logError, logWarn } from "@/app/lib/log";
import { authorizationHeader } from "@/app/lib/session";
import { traceId } from "@/app/lib/trace";
import DashboardClient, {
  type JourneyPhase,
  type DecisionView,
  type FreshnessView,
  type MeetingView,
  type NotificationCenter,
  type Overview,
  type PendingItemView,
  type PortalUser,
  type ProjectDocument,
  type ProjectSummary,
} from "./DashboardClient";

// Portal status/milestone enums → rótulos PT usados na UI.
const STATUS_LABELS: Record<string, string> = {
  discovery: "Descoberta",
  in_implementation: "Em implementação",
  live: "Em produção",
  paused: "Pausado",
};
const MILESTONE_LABELS: Record<string, string> = {
  planned: "Planejado",
  in_progress: "Em andamento",
  next: "Próxima entrega",
  done: "Concluído",
};
const PENDING_STATE_LABELS: Record<string, string> = {
  open: "Aberta",
  in_progress: "Em andamento",
  resolved: "Resolvida",
};
const MEETING_STATUS_LABELS: Record<string, string> = {
  scheduled: "Agendada",
  held: "Realizada",
};
/** A prioridade vem do Biahflow desde a Fase 1 e não chegava à tela (ADR 0029). */
const PENDING_PRIORITY_LABELS: Record<string, string> = {
  high: "Alta",
  medium: "Média",
  low: "Baixa",
};
// Papel exibido no perfil. Vem da `membership` (a autoridade), não do realm.
const ROLE_LABELS: Record<string, string> = {
  internal_admin: "Administrador Biahflow",
  internal_member: "Time Biahflow",
  client_member: "Cliente",
};
const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const [, month, day] = iso.split("-");
  return month && day ? `${day} ${MONTHS[Number(month) - 1] ?? ""}`.trim() : "";
}

// Idade relativa em PT-BR ("há 2 dias"). Calculada no servidor, junto do resto da página.
function relativeAge(iso: string | null | undefined): string {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (!Number.isFinite(days) || days < 0) return "";
  if (days === 0) return "hoje";
  if (days === 1) return "há 1 dia";
  if (days < 30) return `há ${days} dias`;
  const months = Math.floor(days / 30);
  return months === 1 ? "há 1 mês" : `há ${months} meses`;
}

/**
 * A partir de quantas horas de idade a projeção passa a dizer que pode estar
 * desatualizada (ADR 0076).
 *
 * **Vem de configuração porque é parâmetro de operação, não de desenho** — o DAP r1 desta
 * fatia registra o limiar numérico em "Explicitly not approved", e as *Resoluções do gate*
 * de 27/08/2026 o mandam de volta para quem opera. O default existe para a ausência da
 * variável não significar "nunca fica velho", que seria o `skipped` fingindo `clean` da
 * ADR 0017 nesta superfície; um valor inválido cai nele em vez de desligar o estado.
 */
const DEFAULT_STALE_HOURS = 24;

function staleAfterHours(): number {
  const declared = Number(process.env.PROJECTION_STALE_HOURS);
  return Number.isFinite(declared) && declared > 0 ? declared : DEFAULT_STALE_HOURS;
}

/**
 * "há 2 horas", com a granularidade que um carimbo de frescor exige.
 *
 * `relativeAge` acima serve documento e aviso, e o menor degrau dela é o **dia**: ela
 * responde "hoje" a um sync de dois minutos atrás e a um de vinte horas atrás, que é
 * exatamente a distinção que esta fatia existe para fazer.
 *
 * Idade negativa é relógio da origem à frente do nosso, não dado do futuro: vira "há menos
 * de 1 minuto" em vez de sumir, porque a alternativa seria a tela deixar de carimbar por
 * causa de alguns segundos de desvio.
 */
function freshnessAge(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (!Number.isFinite(minutes)) return "";
  if (minutes < 1) return "há menos de 1 minuto";
  if (minutes < 60) return minutes === 1 ? "há 1 minuto" : `há ${minutes} minutos`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? "há 1 hora" : `há ${hours} horas`;
  const days = Math.floor(hours / 24);
  if (days < 30) return days === 1 ? "há 1 dia" : `há ${days} dias`;
  const months = Math.floor(days / 30);
  return months === 1 ? "há 1 mês" : `há ${months} meses`;
}

/**
 * O frescor da projeção, e **qual das duas colunas veio é o rótulo** (ADR 0076).
 *
 * A API mantém `observed_at` e `synced_at` mutuamente exclusivos de propósito — não há um
 * terceiro campo dizendo qual é o caso, e não pode haver: seria a mesma regra em dois
 * lugares, livre para divergir do par. Ler qual chegou é ler o contrato, não adivinhar.
 *
 * As duas nulas são a **terceira** resposta: projeto que nunca passou por um sync não ganha
 * carimbo. A ADR 0026 removeu desta mesma tela um "Atualizado há 2 dias" que ninguém tinha
 * como sustentar, e a regra desde então é não carimbar sem hora de verdade.
 *
 * A idade é derivada **aqui**, no instante em que a página é renderizada, e não na API: um
 * "há X" calculado no servidor de dados envelheceria dentro da própria resposta. É o que
 * `build_dashboard` escreveu ao projetar os instantes e recusar-se a projetar a idade.
 */
function freshnessOf(observedAt: string | null, syncedAt: string | null): FreshnessView | null {
  const kind = observedAt ? "observed" : syncedAt ? "synced" : null;
  const at = observedAt ?? syncedAt;
  if (!kind || !at) return null;
  const age = freshnessAge(at);
  // Data ilegível não vira carimbo — mesma regra do par nulo.
  if (!age) return null;
  const hours = (Date.now() - new Date(at).getTime()) / 3_600_000;
  return { kind, age, stale: hours >= staleAfterHours() };
}

function initialsOf(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] ?? "" : "";
  return `${first}${last}`.toLocaleUpperCase("pt-BR");
}

type ApiMilestone = { title: string; state: string; due_date: string | null; owner_label: string | null };
type ApiDocument = { title: string; type: string | null; author: string | null; link: string | null; updated_at: string | null };
type ApiDecision = { title: string; rationale: string | null; decided_on: string | null; owner_label: string | null; meeting_title: string | null };
type ApiMeeting = { title: string; date: string | null; recording_url: string | null; has_transcript: boolean; status: string | null };
type ApiPending = { id: string; title: string; description: string | null; owner_label: string | null; state: string; priority: string; origin: string; opened_by_message_id: string | null; opened_by_conversation_id: string | null; comment_count: number; created_at: string; resolved_at: string | null };
type ApiResults = { milestones_total: number; milestones_done: number; overdue: number; on_time_percent: number };
type ApiAssumption = {
  effective_from: string;
  effective_to: string | null;
  hourly_rate_cents: number;
  monthly_investment_cents: number;
  currency: string;
  note: string | null;
  days_in_period: number;
};
/** Apuração dos eventos dos agentes (Fase 3, ADR 0013) — distinta de `results`,
 *  que projeta o andamento dos marcos. */
type ApiMeasured = {
  period: { from: string; to: string; days: number };
  events_total: number;
  hours_saved: number;
  benefit_cents: number;
  labor_savings_cents: number;
  avoided_cost_cents: number;
  investment_cents: number;
  net_cents: number;
  roi_ratio: number | null;
  accuracy: number | null;
  exceptions_handled: number;
  unattended_share: number | null;
  failed: number;
  events_without_assumption: number;
  assumptions: ApiAssumption[];
  assumption_basis: { days_per_month: number; formula: string };
  gaps: string[];
};
type ApiDeliverable = { name: string; state: string; link: string | null };
type ApiPhase = { name: string; description: string | null; state: string; target_date: string | null; deliverables: ApiDeliverable[] };
type ApiEmployee = { name: string; area: string | null; description: string | null; status: string; kpi_label: string | null; kpi_value: string | null; hours_saved_month: number | null; roi_month: number | null };
type ApiMe = {
  email: string;
  full_name: string;
  is_internal: boolean;
  notify_by_email: boolean;
  notify_by_whatsapp: boolean;
  phone_hint: string;
  organization: string | null;
  projects: { id: string; name: string; slug: string; status: string }[];
  roles: string[];
};
type ApiNotification = {
  id: string;
  kind: string;
  title: string;
  detail: string | null;
  link: string | null;
  occurred_at: string;
  read: boolean;
};
type ApiNotifications = { unread_count: number; items: ApiNotification[] };

function toOverview(data: Record<string, unknown>, organization: string): Overview {
  const apiMilestones: ApiMilestone[] = (data.milestones as ApiMilestone[]) ?? [];
  const next = apiMilestones.find((milestone) => milestone.state !== "done");
  const journey = data.journey as { current_phase?: string; phases?: ApiPhase[] } | undefined;
  const apiPhases: ApiPhase[] = journey?.phases ?? [];
  const nextMeeting = data.next_meeting as { title: string; date: string | null } | null;
  const roi = data.roi as { net: number | null; ratio: number | null } | null;
  const health = data.health as { label: string; level: string } | null;
  const results = data.results as ApiResults | null;
  const measured = data.measured as ApiMeasured | null;
  // A premissa que o cliente vê ao lado do número é a que está aberta hoje; o
  // histórico inteiro fica na tela de administração.
  const currentAssumption =
    measured?.assumptions?.find((item) => item.effective_to === null) ??
    measured?.assumptions?.at(-1) ??
    null;

  return {
    project: (data.project as string) ?? "",
    organization: (data.organization as string) ?? organization,
    status: STATUS_LABELS[data.status as string] ?? (data.status as string) ?? "",
    completion: (data.completion as number) ?? 0,
    source: "live",
    archivedAt: (data.archived_at as string | null) ?? null,
    sourceDeletedAt: (data.source_deleted_at as string | null) ?? null,
    // `projection_version` fica de fora de propósito, e não por esquecimento: ele existe
    // para "o Biahflow parou de avançar" ser respondível sem abrir o Postgres, e não tem o
    // que dizer a um cliente. Trazê-lo até aqui só para calar a guarda de consumo seria o
    // código morto que a ADR 0033 existe para pegar — a linha continua em `NOT_CONSUMED`,
    // agora com o motivo verdadeiro.
    freshness: freshnessOf(
      (data.observed_at as string | null) ?? null,
      (data.synced_at as string | null) ?? null,
    ),
    nextDelivery: next ? { title: next.title, detail: shortDate(next.due_date) } : null,
    milestones: apiMilestones.map((milestone) => ({
      title: milestone.title,
      owner: milestone.owner_label ?? "",
      state: MILESTONE_LABELS[milestone.state] ?? milestone.state,
      date: shortDate(milestone.due_date),
    })),
    journey: {
      currentPhase: journey?.current_phase ?? null,
      phases: apiPhases.map((phase) => ({
        name: phase.name,
        description: phase.description ?? "",
        state: (["locked", "active", "done"].includes(phase.state) ? phase.state : "locked") as JourneyPhase["state"],
        targetDate: shortDate(phase.target_date),
        deliverables: (phase.deliverables ?? []).map((deliverable) => ({
          name: deliverable.name,
          state: deliverable.state === "delivered" ? "delivered" : "pending",
          link: deliverable.link,
        })),
      })),
    },
    roi: roi ? { net: roi.net ?? null, ratio: roi.ratio ?? null } : null,
    nextMeeting: nextMeeting ? { title: nextMeeting.title, detail: shortDate(nextMeeting.date) } : null,
    health: health ? { label: health.label, level: health.level } : null,
    digitalEmployees: ((data.digital_employees as ApiEmployee[]) ?? []).map((employee) => ({
      name: employee.name,
      area: employee.area,
      description: employee.description,
      status: employee.status,
      kpiLabel: employee.kpi_label,
      kpiValue: employee.kpi_value,
      hoursSavedMonth: employee.hours_saved_month,
      roiMonth: employee.roi_month,
    })),
    documents: ((data.documents as ApiDocument[]) ?? []).map<ProjectDocument>((document) => ({
      title: document.title,
      type: document.type,
      author: document.author,
      link: document.link,
      updated: relativeAge(document.updated_at),
    })),
    meetings: ((data.meetings as ApiMeeting[]) ?? []).map<MeetingView>((meeting) => ({
      title: meeting.title,
      date: shortDate(meeting.date),
      status: meeting.status ? MEETING_STATUS_LABELS[meeting.status] ?? meeting.status : "",
      hasTranscript: meeting.has_transcript,
      recordingUrl: meeting.recording_url,
    })),
    // Cada campo é desreferenciado aqui de propósito: a guarda de consumo da ADR 0033
    // gera um caso por esquema e reprova campo que a tela não lê — e ela enxerga este
    // arquivo porque ninguém o importa nem o chama por URL, então o corpus dele é ele
    // mesmo.
    decisions: ((data.decisions as ApiDecision[]) ?? []).map<DecisionView>((decision) => ({
      title: decision.title,
      rationale: decision.rationale,
      decidedOn: shortDate(decision.decided_on),
      ownerLabel: decision.owner_label,
      meetingTitle: decision.meeting_title,
    })),
    pendings: ((data.pendings as ApiPending[]) ?? []).map<PendingItemView>((pending) => ({
      id: pending.id,
      title: pending.title,
      description: pending.description,
      owner: pending.owner_label,
      state: pending.state,
      stateLabel: PENDING_STATE_LABELS[pending.state] ?? pending.state,
      priority: pending.priority,
      priorityLabel: PENDING_PRIORITY_LABELS[pending.priority] ?? pending.priority,
      origin: pending.origin,
      openedByMessageId: pending.opened_by_message_id,
      openedByConversationId: pending.opened_by_conversation_id,
      commentCount: pending.comment_count,
      age: relativeAge(pending.state === "resolved" ? pending.resolved_at : pending.created_at),
    })),
    results: results
      ? {
          milestonesTotal: results.milestones_total,
          milestonesDone: results.milestones_done,
          overdue: results.overdue,
          onTimePercent: results.on_time_percent,
        }
      : null,
    measured: measured
      ? {
          periodDays: measured.period.days,
          // O período é dito por extremos, e não só por duração: "Últimos 30
          // dias" não diz *quais* 30, e a apuração muda de valor conforme a
          // janela (ADR 0033).
          periodFrom: shortDate(measured.period.from),
          periodTo: shortDate(measured.period.to),
          eventsTotal: measured.events_total,
          hoursSaved: measured.hours_saved,
          benefit: measured.benefit_cents / 100,
          laborSavings: measured.labor_savings_cents / 100,
          avoidedCost: measured.avoided_cost_cents / 100,
          investment: measured.investment_cents / 100,
          net: measured.net_cents / 100,
          roiRatio: measured.roi_ratio,
          accuracy: measured.accuracy,
          exceptionsHandled: measured.exceptions_handled,
          unattendedShare: measured.unattended_share,
          failed: measured.failed,
          eventsWithoutAssumption: measured.events_without_assumption,
          assumption: currentAssumption
            ? {
                hourlyRate: currentAssumption.hourly_rate_cents / 100,
                monthlyInvestment: currentAssumption.monthly_investment_cents / 100,
                effectiveFrom: shortDate(currentAssumption.effective_from),
                note: currentAssumption.note,
                currency: currentAssumption.currency,
                daysInPeriod: currentAssumption.days_in_period,
              }
            : null,
          // A conta em si, vinda de quem a fez. Até a ADR 0033 a tela imprimia
          // uma fórmula literal que nem casava com a que a API devolve.
          basis: {
            daysPerMonth: measured.assumption_basis.days_per_month,
            formula: measured.assumption_basis.formula,
          },
          gaps: measured.gaps ?? [],
        }
      : null,
  };
}

function toUser(me: ApiMe): PortalUser {
  const role = me.roles[0];
  return {
    name: me.full_name,
    initials: initialsOf(me.full_name),
    email: me.email,
    role: ROLE_LABELS[role] ?? (me.is_internal ? "Time Biahflow" : "Cliente"),
    org: me.organization ?? "",
    isInternal: me.is_internal,
    notifyByEmail: me.notify_by_email,
    notifyByWhatsapp: me.notify_by_whatsapp,
    phoneHint: me.phone_hint,
  };
}

function toNotifications(data: ApiNotifications | null): NotificationCenter {
  if (!data) return { unreadCount: 0, items: [] };
  return {
    unreadCount: data.unread_count,
    items: data.items.map((item) => ({
      id: item.id,
      kind: item.kind,
      title: item.title,
      detail: item.detail,
      link: item.link,
      age: relativeAge(item.occurred_at),
      read: item.read,
    })),
  };
}

/** Autenticado, mas ainda sem projeto: é o estado correto de quem não tem membership. */
function NoProject({ user }: { user: PortalUser }) {
  return (
    <main className="state-shell">
      <div className="state-card">
        <p className="eyebrow">SEM PROJETO</p>
        <h1>Você ainda não tem um projeto atribuído.</h1>
        <p>
          Sua conta ({user.email}) está ativa, mas ainda não foi vinculada a um projeto. O time
          da Biahflow precisa fazer esse vínculo — assim que ele existir, o painel aparece aqui.
        </p>
      </div>
    </main>
  );
}

// O dashboard é por usuário e por requisição: nada aqui pode ser pré-renderizado
// no build, que roda sem sessão e sem API.
export const dynamic = "force-dynamic";

/**
 * Registra a falha e devolve o erro a lançar (ADR 0018).
 *
 * A linha sai daqui, de dentro da requisição, porque é aqui que o `trace_id`
 * ainda existe — `instrumentation.ts` só vê o objeto lançado, e é por isso que
 * ele viaja num `TracedError`. Antes desta fase o `throw` subia mudo e a
 * fronteira de erro afirmava ao cliente que alguém tinha registrado.
 */
async function apiFailure(url: string, status: number): Promise<Error> {
  const trace = await traceId();
  logError("api.failed", { trace_id: trace, url, status });
  return new TracedError(`${url} respondeu ${status}`, trace);
}

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ project?: string; tab?: string; item?: string }>;
}) {
  const base = process.env.API_BASE_URL;

  if (!base) {
    // Sem API: ou é a casca de demonstração declarada, ou é configuração errada —
    // e configuração errada não pode virar dashboard (ADR 0010).
    if (demoShellEnabled()) {
      const { DEMO_OVERVIEW, DEMO_PROJECTS, DEMO_USER } = await import("./demo-overview");
      return <DashboardClient overview={DEMO_OVERVIEW} user={DEMO_USER} projects={DEMO_PROJECTS} />;
    }
    throw new Error("API_BASE_URL não está configurada e DEMO_MODE não está ligado");
  }

  const session = await auth();
  const authorization = await authorizationHeader();
  if (!session || session.error || !authorization) redirect("/login");

  // `item` é passagem, como `tab` já era (ADR 0056): o BFF não decide nada aqui, e
  // não há validação de servidor possível nem desejável — o rótulo só faz sentido
  // contra a lista que a tela desenhou, e é lá que ele é comparado.
  const { project: projectId, tab, item } = await searchParams;
  const dashboardUrl = projectId
    ? `${base}/api/v1/projects/${projectId}/dashboard`
    : `${base}/api/v1/me/dashboard`;

  // Uma falha de rede aqui sobe para `app/error.tsx`: indisponibilidade tem que
  // parecer indisponibilidade, não um projeto inventado.
  const [meResponse, dashboardResponse, notificationsResponse] = await Promise.all([
    fetch(`${base}/api/v1/me`, { headers: authorization, cache: "no-store" }),
    fetch(dashboardUrl, { headers: authorization, cache: "no-store" }),
    // O `?project=` da URL também escopa a caixa de avisos (ADR 0059): até aqui
    // ela vinha de `access.default_project` — a membership mais recente — enquanto
    // o dashboard ao lado já vinha do projeto que a URL nomeia. Um cliente com dois
    // projetos, vendo B, recebia o sino de A. Omitido quando a URL não nomeia
    // projeto, que é o caso em que o padrão continua sendo a resposta certa.
    fetch(
      `${base}/api/v1/me/notifications` +
        (projectId ? `?project=${encodeURIComponent(projectId)}` : ""),
      { headers: authorization, cache: "no-store" },
    ),
  ]);

  // O token venceu entre o SSR e a chamada: volta para o login, não para o demo.
  if (meResponse.status === 401 || dashboardResponse.status === 401) redirect("/login");
  if (!meResponse.ok) {
    throw await apiFailure("/api/v1/me", meResponse.status);
  }

  const me: ApiMe = await meResponse.json();
  const user = toUser(me);
  const projects: ProjectSummary[] = me.projects.map((project) => ({
    id: project.id,
    name: project.name,
    status: STATUS_LABELS[project.status] ?? project.status,
    current: projectId ? project.id === projectId : false,
  }));

  // 404 é a resposta de negação do portal (nunca 403): sem projeto visível, a
  // tela diz isso com todas as letras.
  if (dashboardResponse.status === 404) return <NoProject user={user} />;
  if (!dashboardResponse.ok) {
    throw await apiFailure(dashboardUrl, dashboardResponse.status);
  }

  const dashboard: Record<string, unknown> = await dashboardResponse.json();
  const overview = toOverview(dashboard, user.org);
  // Sem `?project=`, o atual é o que a API **disse** que serviu (ADR 0061).
  //
  // Até aqui isto era um casamento por **nome**, porque `MyDashboardOut` não publicava
  // o id. E o nome era a única coisa ligando duas rotas que ordenam por critérios
  // diferentes: `GET /me` lista por `Project.created_at`, `GET /me/dashboard` resolve
  // por `Membership.created_at` com prioridade ao vínculo direto. Dois projetos
  // homônimos no mesmo tenant faziam a tela marcar o errado — e o `?project=` que a ADR
  // 0059 passou a mandar em nove rotas herdava a escolha errada, com a pendência do
  // projeto certo respondendo 404, indistinguível da negação de um estranho.
  //
  // O id só vem de `/me/dashboard`: quem chega por `?project=` já foi marcado acima,
  // pelo id que ele mesmo nomeou.
  const servedProjectId = (dashboard.project_id as string | undefined) ?? null;
  const marked = projects.some((project) => project.current)
    ? projects
    : projects.map((project) => ({ ...project, current: project.id === servedProjectId }));

  // Nenhum item casou: o projeto que está na tela não aparece em `me.projects`.
  //
  // A ADR 0061 desenhou isso como **degradação e não erro** — `activeProject` fica
  // `null`, o `?project=` é omitido e as nove rotas caem em `default_project`, que é
  // o mesmo projeto que o dashboard serviu, então o cliente vê uma tela coerente. O
  // que faltava era alguém **saber**: duas rotas divergirem é fato sobre o servidor,
  // e ele não tem por onde aparecer olhando a tela do cliente. Desde a ADR 0062 a
  // lista abre pelo projeto servido, de modo que uma ocorrência aqui deixou de ser
  // ordem divergente e passou a ser o caso mais estranho — `/me` e `/me/dashboard`
  // discordando sobre a própria membership.
  //
  // A linha sai **daqui** e não do `DashboardClient`, que é `"use client"`: um
  // `logWarn` lá roda no browser e nunca chega ao stdout do BFF.
  if (!marked.some((project) => project.current)) {
    logWarn("web.project_unmatched", {
      trace_id: await traceId(),
      // Nulo quando a URL não nomeou projeto — e é a distinção que importa: com
      // `?project=`, quem respondeu foi `/projects/{id}/dashboard`, que por desenho
      // não publica `project_id` (ADR 0061), então o id pedido é o que se tem.
      requested_project_id: projectId ?? null,
      served_project_id: servedProjectId,
      listed: marked.length,
    });
  }

  // A caixa de avisos não derruba o dashboard: um 404 aqui só quer dizer que a
  // API não resolveu projeto para esta chamada, e o resto da tela já sabe disso.
  const notifications = toNotifications(
    notificationsResponse.ok ? await notificationsResponse.json() : null,
  );

  return (
    <DashboardClient
      overview={overview}
      user={user}
      projects={marked}
      notifications={notifications}
      initialTab={tab}
      initialItem={item}
    />
  );
}
