/**
 * A casca de demonstração — `npm run dev` sem stack nenhuma.
 *
 * Vive isolada aqui, e não dentro de `page.tsx`, para que dê para **provar por
 * grep** que ela só é alcançável atrás de `demoShellEnabled()`: um único import,
 * num único ponto. Nenhuma falha da API cai mais neste objeto (ADR 0010).
 */

import type { Overview } from "./DashboardClient";
import type { PortalUser, ProjectSummary } from "./DashboardClient";

export const DEMO_USER: PortalUser = {
  name: "Marina Farias",
  initials: "MF",
  email: "marina.farias@acme.com.br",
  role: "Cliente",
  org: "Acme Brasil",
  isInternal: false,
  notifyByEmail: true,
  notifyByWhatsapp: false,
  phoneHint: "",
};

export const DEMO_PROJECTS: ProjectSummary[] = [
  // Sem Engagement, e é a resposta certa (ADR 0079): a casca não espelha Biahflow
  // nenhum, então não há programa que alguém tenha afirmado. O projeto cai no grupo
  // sem cabeçalho do seletor, que é exatamente o caminho que a ausência tem de ter.
  {
    id: "demo-1",
    name: "Automação Financeira",
    status: "Em implementação",
    current: true,
    engagementId: null,
    engagementName: null,
  },
];

export const DEMO_OVERVIEW: Overview = {
  project: "Automação Financeira",
  organization: "Acme Brasil",
  status: "Em implementação",
  completion: 68,
  source: "demo",
  // Pelo mesmo motivo do `DEMO_PROJECTS` acima e do `freshness` abaixo.
  engagement: null,
  archivedAt: null,
  sourceDeletedAt: null,
  // A casca de demonstração **não** carimba frescor, e é o caso mais literal da regra
  // (ADR 0026/0076): não há origem que tenha observado coisa nenhuma aqui, então qualquer
  // hora escrita nesta linha seria inventada. Foi daqui que saiu o "Atualizado há 2 dias".
  freshness: null,
  nextDelivery: { title: "Treinamento da operação", detail: "18 de setembro • Em 12 dias" },
  milestones: [
    { title: "Validação de integrações", owner: "Time Acme", state: "Em andamento", date: "09 set" },
    { title: "Treinamento da operação", owner: "Biahflow", state: "Próxima entrega", date: "18 set" },
    { title: "Entrada em produção", owner: "Time Acme", state: "Planejado", date: "30 set" },
  ],
  // A jornada da casca é a **escada canônica da FDE** (Language Map v1.1 §4, ADR 0081):
  // os seis degraus, na ordem, cada um com o `canonicalStage` que lhe corresponde. Ela
  // é a documentação viva do formato, então documenta **os dois ramos** do gate —
  // Feasibility com decisão tomada, Prove exigindo gate e ainda sem decisão. Sem o
  // segundo, o caso que só existe por causa de `requiresGate` não teria exemplo em
  // lugar nenhum do repositório.
  //
  // `Welcome` **saiu**: aqui ela nunca foi degrau da metodologia — era o passo de
  // acessos, que é onboarding. Isso vale só para esta casca, que é nossa; o One não
  // reclassifica fase vinda do Biahflow (Language Map §3, regra 2), e lá `Welcome`
  // continua sendo uma fase com `canonical_stage=discover`.
  journey: {
    currentPhase: "Prove",
    phases: [
      { name: "Discover", description: "Mapeamento dos processos.", state: "done", targetDate: "", canonicalStage: "discover", gateDecision: null, requiresGate: false, deliverables: [{ name: "Mapa dos processos", state: "delivered", link: null, externalRef: null, decisions: [] }, { name: "Diagnóstico de maturidade de IA", state: "delivered", link: null, externalRef: null, decisions: [] }] },
      { name: "Prioritize", description: "Priorização das oportunidades de melhoria.", state: "done", targetDate: "", canonicalStage: "prioritize", gateDecision: null, requiresGate: false, deliverables: [{ name: "Improvement Opportunity Backlog", state: "delivered", link: null, externalRef: null, decisions: [] }] },
      { name: "Feasibility", description: "Viabilidade técnica da hipótese de solução.", state: "done", targetDate: "", canonicalStage: "feasibility", gateDecision: "conditional_go", requiresGate: true, deliverables: [{ name: "Technical Feasibility Brief", state: "delivered", link: null, externalRef: null, decisions: [] }] },
      { name: "Prove", description: "A menor implementação real em produção controlada, com critério de sucesso definido antes de construir.", state: "active", targetDate: "20 set", canonicalStage: "prove", gateDecision: null, requiresGate: true, deliverables: [{ name: "Funcionário Digital", state: "pending", link: null, externalRef: null, decisions: [] }, { name: "Dashboard de KPIs", state: "pending", link: null, externalRef: null, decisions: [] }] },
      { name: "Scale", description: "Expansão para mais áreas.", state: "locked", targetDate: "", canonicalStage: "scale", gateDecision: null, requiresGate: false, deliverables: [] },
      { name: "Optimize", description: "Evolução contínua.", state: "locked", targetDate: "", canonicalStage: "optimize", gateDecision: null, requiresGate: false, deliverables: [] },
    ],
  },
  roi: { net: 214000, ratio: 1.42 },
  nextMeeting: { title: "Comitê de projeto", detail: "28 ago" },
  health: { label: "No prazo", level: "green" },
  digitalEmployees: [
    { name: "Agente Financeiro", area: "Financeiro", description: "Concilia contas a pagar e sinaliza divergências.", status: "active", kpiLabel: "Conciliação", kpiValue: "80%", hoursSavedMonth: 120, roiMonth: 14000, kpiIds: [12] },
    { name: "Agente de Atendimento", area: "Atendimento", description: "Responde dúvidas frequentes no WhatsApp.", status: "building", kpiLabel: "Cobertura", kpiValue: "—", hoursSavedMonth: null, roiMonth: null, kpiIds: [] },
  ],
  // Dois KPIs, e o segundo é o caso que a issue #89 nomeia: **janela sem número**.
  // O `value: null` dentro de um objeto que existe é "ninguém mediu ainda", e a
  // casca de demonstração desenha a lacuna em vez de um zero — pela mesma razão de
  // `measured: null` mais abaixo, e da data que a ADR 0026 removeu daqui.
  kpis: [
    {
      id: 12,
      name: "Horas de conciliação por mês",
      definition: "Horas do time contábil gastas conciliando contas a pagar.",
      formula: "Soma das horas apontadas no fechamento mensal.",
      unit: "hours",
      direction: "down",
      dataSource: "Apontamento de horas do time contábil",
      cadence: "monthly",
      target: 20,
      baseline: { value: 72, periodStart: "2026-03-01", periodEnd: "2026-03-31", measuredAt: "2026-04-02T14:00:00-03:00", confidence: 80 },
      outcome: { value: 21.5, periodStart: "2026-07-01", periodEnd: "2026-07-31", measuredAt: "2026-08-02T11:00:00-03:00", confidence: 90 },
      monitoring: [],
    },
    {
      id: 15,
      name: "Divergências reabertas",
      definition: "Conciliações que voltaram para revisão manual depois de fechadas.",
      formula: null,
      unit: "count",
      direction: "down",
      dataSource: "Fila de exceções do ERP",
      cadence: "monthly",
      target: null,
      baseline: { value: 34, periodStart: "2026-03-01", periodEnd: "2026-03-31", measuredAt: "2026-04-02T14:00:00-03:00", confidence: 70 },
      outcome: { value: null, periodStart: "2026-07-01", periodEnd: null, measuredAt: null, confidence: null },
      monitoring: [],
    },
  ],
  valueLedger: [
    { id: 3, valueType: "cost_saving", amount: 48000, quantity: 606, periodStart: "2026-07-01", periodEnd: "2026-07-31", attributionMethod: "Diferença Baseline→Outcome do KPI 12 × custo-hora do time contábil", kpiId: 12, outcomeMeasuredAt: "2026-08-02T11:00:00-03:00" },
    // A entrada cujo KPI de origem **não está nesta lista**: ela vem do mandato e o
    // indicador vive num projeto irmão. É caso normal, e a tela a mostra sem o
    // vínculo em vez de escondê-la (ADR 0085).
    { id: 4, valueType: "revenue", amount: 12500, quantity: null, periodStart: "2026-06-01", periodEnd: "2026-06-30", attributionMethod: "Receita adicional atribuída ao atendimento fora do horário comercial", kpiId: 41, outcomeMeasuredAt: null },
  ],
  documents: [
    { title: "Plano de implantação v3.pdf", type: "PDF", author: "Biahflow", link: null, updated: "há 1 dia" },
    { title: "Mapa de integrações", type: null, author: "Time Acme", link: null, updated: "há 3 dias" },
    { title: "Política de exceções financeiras.docx", type: "DOCX", author: "Mariana Farias", link: null, updated: "há 5 dias" },
  ],
  meetings: [
    { title: "Comitê de projeto", date: "28 ago", status: "Agendada", hasTranscript: false, recordingUrl: null },
    { title: "Revisão de integrações", date: "21 ago", status: "Realizada", hasTranscript: true, recordingUrl: null },
    { title: "Kickoff do projeto", date: "07 ago", status: "Realizada", hasTranscript: true, recordingUrl: null },
  ],
  decisions: [
    { title: "Adotar fila gerenciada em vez de instância própria", rationale: "O volume previsto não paga o custo fixo, e a fila gerenciada escala a zero fora do horário comercial.", decidedOn: "06 ago", ownerLabel: "Marina Farias", meetingTitle: "Revisão de integrações" },
    { title: "Adiar o PROVE de cobrança para setembro", rationale: "A integração fiscal depende de um cadastro que ainda está em revisão do lado do cliente.", decidedOn: "21 jul", ownerLabel: "Helena Dias", meetingTitle: null },
  ],
  pendings: [
    { id: "demo-pend-1", title: "Aprovar fluxo de exceções", description: null, owner: "Acme Brasil", state: "open", stateLabel: "Aberta", priority: "high", priorityLabel: "Alta", origin: "biahflow", openedByMessageId: null, openedByConversationId: null, commentCount: 0, age: "há 2 dias" },
    { id: "demo-pend-2", title: "Enviar lista de usuários do PROVE", description: null, owner: "Acme Brasil", state: "open", stateLabel: "Aberta", priority: "medium", priorityLabel: "Média", origin: "biahflow", openedByMessageId: null, openedByConversationId: null, commentCount: 0, age: "há 4 dias" },
    { id: "demo-pend-3", title: "Validar cálculo de economia", description: null, owner: "Biahflow", state: "open", stateLabel: "Aberta", priority: "low", priorityLabel: "Baixa", origin: "biahflow", openedByMessageId: null, openedByConversationId: null, commentCount: 0, age: "há 5 dias" },
    { id: "demo-pend-4", title: "Definir alçada de aprovação", description: null, owner: "Biahflow", state: "resolved", stateLabel: "Resolvida", priority: "medium", priorityLabel: "Média", origin: "biahflow", openedByMessageId: null, openedByConversationId: null, commentCount: 0, age: "há 9 dias" },
  ],
  results: { milestonesTotal: 5, milestonesDone: 2, overdue: 0, onTimePercent: 100 },
  // A casca de demonstração não inventa apuração: sem eventos e sem premissa,
  // a aba Resultados mostra "—" e declara a lacuna, igual a um projeto real
  // recém-criado. Fabricar números aqui reintroduziria o que a Fase 3 removeu.
  measured: null,
};
