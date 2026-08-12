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
  // O canal nasce desligado e sem número (FDD 021, ADR 0043) — é o estado de toda
  // conta no dia do deploy, e é o que a tela de Configurações tem de saber mostrar.
  notify_by_whatsapp: false,
  phone_hint: "",
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
  // `null` é projeto ativo (ADR 0036). O caso preenchido é exercitado por
  // `archivedDashboard()` em `rendered-html.test.mjs`, sobre esta mesma base.
  archived_at: null,
  // Idem para a exclusão na origem (ADR 0037), que só chega por webhook.
  source_deleted_at: null,
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
  // Uma com proveniência e outra sem: é o corte que o filtro da aba oferece, e o
  // `meeting_title` nulo é o caso real de uma reunião arquivada no Biahflow.
  decisions: [
    { title: "Adotar fila gerenciada", rationale: "O volume previsto não paga o Memorystore.", decided_on: "2026-08-06", owner_label: "Marina Farias", meeting_title: "Comitê de projeto" },
    { title: "Adiar o piloto de cobrança", rationale: null, decided_on: null, owner_label: null, meeting_title: null },
  ],
  // Três abertas com prioridades diferentes, e a alta é a **mais antiga** de
  // propósito: é o que torna a ordenação da ADR 0029 observável no HTML do SSR.
  // Ordenada por data, "Aprovar fluxo de exceções" viria por último.
  //
  // A `priority` dizia `"normal"` até esta fatia — valor que `PendingPriority`
  // não tem. Passava porque o contrato declarava `str`; hoje declara os três.
  pendings: [
    { id: "eeeeeeee-1111-4222-8333-000000000001", title: "Renovar o certificado do integrador", description: null, owner_label: "Acme Brasil", state: "open", priority: "low", origin: "biahflow", opened_by_message_id: null, opened_by_conversation_id: null, comment_count: 0, created_at: "2026-08-04T10:00:00+00:00", resolved_at: null },
    { id: "eeeeeeee-1111-4222-8333-000000000002", title: "Enviar lista de usuários piloto", description: null, owner_label: "Acme Brasil", state: "open", priority: "medium", origin: "biahflow", opened_by_message_id: null, opened_by_conversation_id: null, comment_count: 0, created_at: "2026-08-03T10:00:00+00:00", resolved_at: null },
    { id: "eeeeeeee-1111-4222-8333-000000000003", title: "Aprovar fluxo de exceções", description: null, owner_label: "Acme Brasil", state: "open", priority: "high", origin: "biahflow", opened_by_message_id: null, opened_by_conversation_id: null, comment_count: 0, created_at: "2026-08-02T10:00:00+00:00", resolved_at: null },
  ],
  results: { milestones_total: 3, milestones_done: 0, overdue: 0, on_time_percent: 100 },
  // Apuração dos eventos dos agentes (Fase 3, ADR 0013). Os números batem com a
  // premissa abaixo de propósito: 40h a R$ 150 = R$ 6.000, mais R$ 1.200 de
  // custo evitado, contra R$ 3.000 de investimento no período → ROI de 140%.
  measured: {
    period: { from: "2026-07-05", to: "2026-08-05", days: 30 },
    events_total: 1240,
    hours_saved: 40,
    labor_savings_cents: 600_000,
    avoided_cost_cents: 120_000,
    benefit_cents: 720_000,
    investment_cents: 300_000,
    net_cents: 420_000,
    roi_ratio: 1.4,
    accuracy: 0.986,
    exceptions_handled: 120,
    unattended_share: 0.87,
    failed: 17,
    events_without_assumption: 0,
    assumptions: [
      {
        effective_from: "2026-06-01",
        effective_to: null,
        hourly_rate_cents: 15_000,
        monthly_investment_cents: 300_000,
        currency: "BRL",
        note: "Contrato de implantação",
        days_in_period: 30,
      },
    ],
    assumption_basis: { days_per_month: 30, formula: "(beneficio - investimento) / investimento" },
    gaps: [],
  },
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

/** `GET /api/v1/me/search` — a busca do projeto (Fase 6, ADR 0024).
 *
 *  Duas espécies de propósito: a linha que leva a uma aba e o trecho que abre a
 *  fonte. Elas percorrem caminhos diferentes no clique, e uma fixture com só uma
 *  delas deixaria metade do componente sem exercício. */
export const SEARCH = {
  results: [
    {
      kind: "document",
      title: "Contrato de manutenção",
      detail: "Jurídico",
      location: "",
      tab: "Documentos",
      document_id: "cccccccc-1111-4222-8333-444444444444",
    },
    {
      kind: "chunk",
      title: "Contrato de manutenção",
      detail: "…a cláusula de rescisão antecipada exige aviso de trinta dias…",
      location: "página 2",
      tab: "Documentos",
      document_id: "cccccccc-1111-4222-8333-444444444444",
    },
  ],
};
