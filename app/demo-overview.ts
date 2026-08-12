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
  { id: "demo-1", name: "Automação Financeira", status: "Em implementação", current: true },
];

export const DEMO_OVERVIEW: Overview = {
  project: "Automação Financeira",
  organization: "Acme Brasil",
  status: "Em implementação",
  completion: 68,
  source: "demo",
  archivedAt: null,
  sourceDeletedAt: null,
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
  decisions: [
    { title: "Adotar fila gerenciada em vez de instância própria", rationale: "O volume previsto não paga o custo fixo, e a fila gerenciada escala a zero fora do horário comercial.", decidedOn: "06 ago", ownerLabel: "Marina Farias", meetingTitle: "Revisão de integrações" },
    { title: "Adiar o piloto de cobrança para setembro", rationale: "A integração fiscal depende de um cadastro que ainda está em revisão do lado do cliente.", decidedOn: "21 jul", ownerLabel: "Helena Dias", meetingTitle: null },
  ],
  pendings: [
    { id: "demo-pend-1", title: "Aprovar fluxo de exceções", description: null, owner: "Acme Brasil", state: "open", stateLabel: "Aberta", priority: "high", priorityLabel: "Alta", origin: "biahflow", openedByMessageId: null, openedByConversationId: null, commentCount: 0, age: "há 2 dias" },
    { id: "demo-pend-2", title: "Enviar lista de usuários piloto", description: null, owner: "Acme Brasil", state: "open", stateLabel: "Aberta", priority: "medium", priorityLabel: "Média", origin: "biahflow", openedByMessageId: null, openedByConversationId: null, commentCount: 0, age: "há 4 dias" },
    { id: "demo-pend-3", title: "Validar cálculo de economia", description: null, owner: "Portal Labs", state: "open", stateLabel: "Aberta", priority: "low", priorityLabel: "Baixa", origin: "biahflow", openedByMessageId: null, openedByConversationId: null, commentCount: 0, age: "há 5 dias" },
    { id: "demo-pend-4", title: "Definir alçada de aprovação", description: null, owner: "Portal Labs", state: "resolved", stateLabel: "Resolvida", priority: "medium", priorityLabel: "Média", origin: "biahflow", openedByMessageId: null, openedByConversationId: null, commentCount: 0, age: "há 9 dias" },
  ],
  results: { milestonesTotal: 5, milestonesDone: 2, overdue: 0, onTimePercent: 100 },
  // A casca de demonstração não inventa apuração: sem eventos e sem premissa,
  // a aba Resultados mostra "—" e declara a lacuna, igual a um projeto real
  // recém-criado. Fabricar números aqui reintroduziria o que a Fase 3 removeu.
  measured: null,
};
