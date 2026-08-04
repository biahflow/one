/**
 * Respostas da API usadas pelo teste de SSR autenticado.
 *
 * Espelham o que `GET /api/v1/me` e `GET /api/v1/me/dashboard` devolvem para o
 * cliente semeado (mesmo conteúdo de `seed_data/biahflow-snapshot.json`), de
 * modo que o teste exercite a projeção real de `page.tsx` sem subir Postgres,
 * Keycloak ou FastAPI.
 */

export const ME = {
  email: "marina.farias@acme.com.br",
  full_name: "Marina Farias",
  is_internal: false,
  notify_by_email: true,
  organization: "Acme Brasil",
  projects: [
    {
      id: "11111111-2222-4333-8444-555555555555",
      name: "Automação Financeira",
      slug: "biahflow-7",
      status: "in_implementation",
    },
  ],
  roles: ["client_member"],
};

export const DASHBOARD = {
  project: "Automação Financeira",
  organization: "Acme Brasil",
  status: "in_implementation",
  completion: 68,
  milestones: [
    { title: "Validação de integrações", state: "in_progress", due_date: "2026-09-09", owner_label: "Acme Brasil" },
    { title: "Treinamento da operação", state: "planned", due_date: "2026-09-18", owner_label: "Portal Labs" },
    { title: "Entrada em produção", state: "planned", due_date: "2026-09-30", owner_label: "Acme Brasil" },
  ],
  journey: {
    current_phase: "Prove",
    phases: [
      { name: "Welcome", description: "Boas-vindas e acessos.", state: "done", target_date: null, deliverables: [{ name: "Acesso ao portal", state: "delivered", link: null }] },
      { name: "Prove", description: "Piloto do funcionário digital.", state: "active", target_date: "2026-09-20", deliverables: [{ name: "Funcionário Digital", state: "pending", link: null }] },
      { name: "Scale", description: "Expansão para mais áreas.", state: "locked", target_date: null, deliverables: [] },
    ],
  },
  roi: { net: 214000, ratio: 1.42 },
  next_meeting: { title: "Comitê de projeto", date: "2026-08-28" },
  health: { label: "No prazo", level: "green" },
  digital_employees: [
    {
      name: "Agente Financeiro",
      area: "Financeiro",
      description: "Concilia contas a pagar e sinaliza divergências.",
      status: "active",
      kpi_label: "Conciliação",
      kpi_value: "80%",
      hours_saved_month: 120,
      roi_month: 14000,
    },
  ],
  documents: [
    { title: "Plano de implantação v3.pdf", type: "PDF", author: "Portal Labs", link: null, updated_at: "2026-08-03T12:00:00+00:00" },
  ],
  meetings: [
    { title: "Comitê de projeto", date: "2026-08-28", recording_url: null, has_transcript: false, status: "scheduled" },
  ],
  pendings: [
    { title: "Aprovar fluxo de exceções", description: null, owner_label: "Acme Brasil", state: "open", priority: "normal", origin: "biahflow", created_at: "2026-08-02T10:00:00+00:00", resolved_at: null },
  ],
  results: { milestones_total: 3, milestones_done: 0, overdue: 0, on_time_percent: 100 },
};

/** `GET /api/v1/me/notifications` — a caixa do projeto atual (Fase 2, ADR 0012). */
export const NOTIFICATIONS = {
  unread_count: 2,
  items: [
    {
      id: "aaaaaaaa-1111-4222-8333-444444444444",
      kind: "milestone_done",
      title: "Marco concluído",
      detail: "Validação de integrações",
      link: null,
      occurred_at: "2026-08-03T12:00:00+00:00",
      read: false,
    },
    {
      id: "bbbbbbbb-1111-4222-8333-444444444444",
      kind: "document_added",
      title: "Novo documento no projeto",
      detail: "Plano de implantação v3.pdf",
      link: null,
      occurred_at: "2026-08-02T09:00:00+00:00",
      read: false,
    },
  ],
};
