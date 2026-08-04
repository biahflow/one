import DashboardClient, {
  type JourneyPhase,
  type MeetingView,
  type Overview,
  type PendingItemView,
  type ProjectDocument,
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

// Fallback demo — mantém a Visão geral (e os testes de SSR) quando a API não responde.
const DEMO_OVERVIEW: Overview = {
  project: "Automação Financeira",
  organization: "Acme Brasil",
  status: "Em implementação",
  completion: 68,
  source: "demo",
  nextDelivery: { title: "Treinamento da operação", detail: "18 de setembro • Em 12 dias" },
  milestones: [
    { title: "Validação de integrações", owner: "Time Acme", state: "Em andamento", date: "09 set" },
    { title: "Treinamento da operação", owner: "Portal Labs", state: "Próxima entrega", date: "18 set" },
    { title: "Entrada em produção", owner: "Time Acme", state: "Planejado", date: "30 set" },
  ],
  journey: {
    currentPhase: "Prove",
    phases: [
      { name: "Welcome", description: "Boas-vindas e acessos.", state: "done", targetDate: "", deliverables: [{ name: "Acesso ao portal", state: "delivered", link: null }] },
      { name: "Discover", description: "Mapeamento dos processos.", state: "done", targetDate: "", deliverables: [{ name: "Mapa dos processos", state: "delivered", link: null }, { name: "AI Score", state: "delivered", link: null }] },
      { name: "Prove", description: "Piloto do funcionário digital.", state: "active", targetDate: "20 set", deliverables: [{ name: "Funcionário Digital", state: "pending", link: null }, { name: "Dashboard de KPIs", state: "pending", link: null }] },
      { name: "Scale", description: "Expansão para mais áreas.", state: "locked", targetDate: "", deliverables: [] },
      { name: "Optimize", description: "Evolução contínua.", state: "locked", targetDate: "", deliverables: [] },
    ],
  },
  roi: { net: 214000, ratio: 1.42 },
  nextMeeting: { title: "Comitê de projeto", detail: "28 ago" },
  health: { label: "No prazo", level: "green" },
  digitalEmployees: [
    { name: "Agente Financeiro", area: "Financeiro", description: "Concilia contas a pagar e sinaliza divergências.", status: "active", kpiLabel: "Conciliação", kpiValue: "80%", hoursSavedMonth: 120, roiMonth: 14000 },
    { name: "Agente de Atendimento", area: "Atendimento", description: "Responde dúvidas frequentes no WhatsApp.", status: "building", kpiLabel: "Cobertura", kpiValue: "—", hoursSavedMonth: null, roiMonth: null },
  ],
  documents: [
    { title: "Plano de implantação v3.pdf", type: "PDF", author: "Portal Labs", link: null, updated: "há 1 dia" },
    { title: "Mapa de integrações", type: null, author: "Time Acme", link: null, updated: "há 3 dias" },
    { title: "Política de exceções financeiras.docx", type: "DOCX", author: "Mariana Farias", link: null, updated: "há 5 dias" },
  ],
  meetings: [
    { title: "Comitê de projeto", date: "28 ago", status: "Agendada", hasTranscript: false, recordingUrl: null },
    { title: "Revisão de integrações", date: "21 ago", status: "Realizada", hasTranscript: true, recordingUrl: null },
    { title: "Kickoff do projeto", date: "07 ago", status: "Realizada", hasTranscript: true, recordingUrl: null },
  ],
  pendings: [
    { title: "Aprovar fluxo de exceções", description: null, owner: "Acme Brasil", state: "open", stateLabel: "Aberta", origin: "biahflow", age: "há 2 dias" },
    { title: "Enviar lista de usuários piloto", description: null, owner: "Acme Brasil", state: "open", stateLabel: "Aberta", origin: "biahflow", age: "há 4 dias" },
    { title: "Validar cálculo de economia", description: null, owner: "Portal Labs", state: "open", stateLabel: "Aberta", origin: "biahflow", age: "há 5 dias" },
    { title: "Definir alçada de aprovação", description: null, owner: "Portal Labs", state: "resolved", stateLabel: "Resolvida", origin: "biahflow", age: "há 9 dias" },
  ],
  results: { milestonesTotal: 5, milestonesDone: 2, overdue: 0, onTimePercent: 100 },
};

type ApiMilestone = { title: string; state: string; due_date: string | null; owner_label: string | null };
type ApiDocument = { title: string; type: string | null; author: string | null; link: string | null; updated_at: string | null };
type ApiMeeting = { title: string; date: string | null; recording_url: string | null; has_transcript: boolean; status: string | null };
type ApiPending = { title: string; description: string | null; owner_label: string | null; state: string; priority: string; origin: string; created_at: string; resolved_at: string | null };
type ApiResults = { milestones_total: number; milestones_done: number; overdue: number; on_time_percent: number };
type ApiDeliverable = { name: string; state: string; link: string | null };
type ApiPhase = { name: string; description: string | null; state: string; target_date: string | null; deliverables: ApiDeliverable[] };
type ApiEmployee = { name: string; area: string | null; description: string | null; status: string; kpi_label: string | null; kpi_value: string | null; hours_saved_month: number | null; roi_month: number | null };

async function loadOverview(): Promise<Overview> {
  const base = process.env.API_BASE_URL;
  const email = process.env.PORTAL_CLIENT_EMAIL ?? "marina.farias@acme.com.br";
  if (!base) return DEMO_OVERVIEW;
  try {
    const response = await fetch(`${base}/api/v1/me/dashboard`, {
      headers: { "X-Portal-User": email },
      cache: "no-store",
    });
    if (!response.ok) return DEMO_OVERVIEW;
    const data = await response.json();
    const apiMilestones: ApiMilestone[] = data.milestones ?? [];
    const next = apiMilestones.find((milestone) => milestone.state !== "done");
    const apiPhases: ApiPhase[] = data.journey?.phases ?? [];
    const nextMeeting = data.next_meeting;
    return {
      project: data.project ?? DEMO_OVERVIEW.project,
      organization: data.organization ?? "",
      status: STATUS_LABELS[data.status] ?? data.status ?? DEMO_OVERVIEW.status,
      completion: data.completion ?? 0,
      source: "live",
      nextDelivery: next
        ? { title: next.title, detail: shortDate(next.due_date) }
        : null,
      milestones: apiMilestones.map((milestone) => ({
        title: milestone.title,
        owner: milestone.owner_label ?? "",
        state: MILESTONE_LABELS[milestone.state] ?? milestone.state,
        date: shortDate(milestone.due_date),
      })),
      journey: {
        currentPhase: data.journey?.current_phase ?? null,
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
      roi: data.roi ? { net: data.roi.net ?? null, ratio: data.roi.ratio ?? null } : null,
      nextMeeting: nextMeeting
        ? { title: nextMeeting.title, detail: shortDate(nextMeeting.date) }
        : null,
      health: data.health ? { label: data.health.label, level: data.health.level } : null,
      digitalEmployees: ((data.digital_employees ?? []) as ApiEmployee[]).map((employee) => ({
        name: employee.name,
        area: employee.area,
        description: employee.description,
        status: employee.status,
        kpiLabel: employee.kpi_label,
        kpiValue: employee.kpi_value,
        hoursSavedMonth: employee.hours_saved_month,
        roiMonth: employee.roi_month,
      })),
      documents: ((data.documents ?? []) as ApiDocument[]).map<ProjectDocument>((document) => ({
        title: document.title,
        type: document.type,
        author: document.author,
        link: document.link,
        updated: relativeAge(document.updated_at),
      })),
      meetings: ((data.meetings ?? []) as ApiMeeting[]).map<MeetingView>((meeting) => ({
        title: meeting.title,
        date: shortDate(meeting.date),
        status: meeting.status ? MEETING_STATUS_LABELS[meeting.status] ?? meeting.status : "",
        hasTranscript: meeting.has_transcript,
        recordingUrl: meeting.recording_url,
      })),
      pendings: ((data.pendings ?? []) as ApiPending[]).map<PendingItemView>((pending) => ({
        title: pending.title,
        description: pending.description,
        owner: pending.owner_label,
        state: pending.state,
        stateLabel: PENDING_STATE_LABELS[pending.state] ?? pending.state,
        origin: pending.origin,
        age: relativeAge(pending.state === "resolved" ? pending.resolved_at : pending.created_at),
      })),
      results: data.results
        ? {
            milestonesTotal: (data.results as ApiResults).milestones_total,
            milestonesDone: (data.results as ApiResults).milestones_done,
            overdue: (data.results as ApiResults).overdue,
            onTimePercent: (data.results as ApiResults).on_time_percent,
          }
        : null,
    };
  } catch {
    return DEMO_OVERVIEW;
  }
}

export default async function Page() {
  const overview = await loadOverview();
  return <DashboardClient overview={overview} />;
}
