import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { demoShellEnabled } from "@/app/lib/demo";
import { authorizationHeader } from "@/app/lib/session";
import DashboardClient, {
  type JourneyPhase,
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
// Papel exibido no perfil. Vem da `membership` (a autoridade), não do realm.
const ROLE_LABELS: Record<string, string> = {
  internal_admin: "Administrador Portal Labs",
  internal_member: "Time Portal Labs",
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

function initialsOf(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] ?? "" : "";
  return `${first}${last}`.toLocaleUpperCase("pt-BR");
}

type ApiMilestone = { title: string; state: string; due_date: string | null; owner_label: string | null };
type ApiDocument = { title: string; type: string | null; author: string | null; link: string | null; updated_at: string | null };
type ApiMeeting = { title: string; date: string | null; recording_url: string | null; has_transcript: boolean; status: string | null };
type ApiPending = { title: string; description: string | null; owner_label: string | null; state: string; priority: string; origin: string; created_at: string; resolved_at: string | null };
type ApiResults = { milestones_total: number; milestones_done: number; overdue: number; on_time_percent: number };
type ApiDeliverable = { name: string; state: string; link: string | null };
type ApiPhase = { name: string; description: string | null; state: string; target_date: string | null; deliverables: ApiDeliverable[] };
type ApiEmployee = { name: string; area: string | null; description: string | null; status: string; kpi_label: string | null; kpi_value: string | null; hours_saved_month: number | null; roi_month: number | null };
type ApiMe = {
  email: string;
  full_name: string;
  is_internal: boolean;
  notify_by_email: boolean;
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

  return {
    project: (data.project as string) ?? "",
    organization: (data.organization as string) ?? organization,
    status: STATUS_LABELS[data.status as string] ?? (data.status as string) ?? "",
    completion: (data.completion as number) ?? 0,
    source: "live",
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
    pendings: ((data.pendings as ApiPending[]) ?? []).map<PendingItemView>((pending) => ({
      title: pending.title,
      description: pending.description,
      owner: pending.owner_label,
      state: pending.state,
      stateLabel: PENDING_STATE_LABELS[pending.state] ?? pending.state,
      origin: pending.origin,
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
  };
}

function toUser(me: ApiMe): PortalUser {
  const role = me.roles[0];
  return {
    name: me.full_name,
    initials: initialsOf(me.full_name),
    email: me.email,
    role: ROLE_LABELS[role] ?? (me.is_internal ? "Time Portal Labs" : "Cliente"),
    org: me.organization ?? "",
    isInternal: me.is_internal,
    notifyByEmail: me.notify_by_email,
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
          da Portal Labs precisa fazer esse vínculo — assim que ele existir, o painel aparece aqui.
        </p>
      </div>
    </main>
  );
}

// O dashboard é por usuário e por requisição: nada aqui pode ser pré-renderizado
// no build, que roda sem sessão e sem API.
export const dynamic = "force-dynamic";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ project?: string }>;
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

  const { project: projectId } = await searchParams;
  const dashboardUrl = projectId
    ? `${base}/api/v1/projects/${projectId}/dashboard`
    : `${base}/api/v1/me/dashboard`;

  // Uma falha de rede aqui sobe para `app/error.tsx`: indisponibilidade tem que
  // parecer indisponibilidade, não um projeto inventado.
  const [meResponse, dashboardResponse, notificationsResponse] = await Promise.all([
    fetch(`${base}/api/v1/me`, { headers: authorization, cache: "no-store" }),
    fetch(dashboardUrl, { headers: authorization, cache: "no-store" }),
    fetch(`${base}/api/v1/me/notifications`, { headers: authorization, cache: "no-store" }),
  ]);

  // O token venceu entre o SSR e a chamada: volta para o login, não para o demo.
  if (meResponse.status === 401 || dashboardResponse.status === 401) redirect("/login");
  if (!meResponse.ok) throw new Error(`GET /api/v1/me respondeu ${meResponse.status}`);

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
    throw new Error(`${dashboardUrl} respondeu ${dashboardResponse.status}`);
  }

  const overview = toOverview(await dashboardResponse.json(), user.org);
  // Sem `?project=`, o atual é o que a API escolheu — marcado pelo nome.
  const marked = projects.some((project) => project.current)
    ? projects
    : projects.map((project) => ({ ...project, current: project.name === overview.project }));

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
    />
  );
}
