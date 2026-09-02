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
      // O programa a que ele pertence (ADR 0079). O caso `null` — projeto que o
      // Biahflow ainda não associou — é exercitado por override em
      // `rendered-html.test.mjs`, sobre esta mesma base.
      engagement_id: "99999999-8888-4777-8666-555555555555",
      engagement_name: "Transformação Financeira",
    },
  ],
  roles: ["client_member"],
};

export const DASHBOARD = {
  project: "Automação Financeira",
  // O mesmo programa que `ME.projects[0]` traz, porque é o mesmo projeto servido
  // (ADR 0079). É daqui que o topo lê o rótulo, e não da lista: quando o projeto da
  // tela não está em `me.projects`, esta é a única fonte que sabe de qual programa
  // ele é.
  engagement: {
    id: "99999999-8888-4777-8666-555555555555",
    name: "Transformação Financeira",
    status: "active",
  },
  // Qual projeto a resposta serviu (ADR 0061) — o mesmo id que `ME.projects[0]` traz,
  // porque é o mesmo cliente semeado. É o que a tela lê para marcar o projeto atual, em
  // vez de compará-lo pelo nome.
  project_id: "11111111-2222-4333-8444-555555555555",
  organization: "Acme Brasil",
  status: "in_implementation",
  completion: 68,
  // `null` é projeto ativo (ADR 0036). O caso preenchido é exercitado por
  // `archivedDashboard()` em `rendered-html.test.mjs`, sobre esta mesma base.
  archived_at: null,
  // Idem para a exclusão na origem (ADR 0037), que só chega por webhook.
  source_deleted_at: null,
  // Frescor da projeção (ADR 0076). As duas datas são mutuamente exclusivas e **qual delas
  // veio é o rótulo**: aqui a origem carimbou, então é "atualizado há X". O caminho do
  // fallback (`observed_at: null`, `synced_at` preenchido, "sincronizado há X") é o do
  // Biahflow que ainda não numera, e vale a pena lembrar que os dois nulos também são um
  // estado legítimo — projeto sem passagem de sync não ganha carimbo inventado. Os três
  // casos são exercitados por override em `rendered-html.test.mjs`, sobre esta mesma base.
  //
  // **Relativo ao instante do teste, e é o único campo desta fixture que precisa ser.** Um
  // instante fixo aqui não descreve um estado fixo: "há 2 horas" hoje é "há 3 meses" no
  // trimestre que vem, de modo que a fixture mudaria de significado sozinha e o caso
  // recente viraria o caso stale sem ninguém tocar em nada.
  observed_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
  synced_at: null,
  projection_version: 12,
  milestones: [
    { title: "Validação de integrações", state: "in_progress", due_date: "2026-09-09", owner_label: "Acme Brasil" },
    { title: "Treinamento da operação", state: "planned", due_date: "2026-09-18", owner_label: "Biahflow" },
    { title: "Entrada em produção", state: "planned", due_date: "2026-09-30", owner_label: "Acme Brasil" },
  ],
  journey: {
    current_phase: "Prove",
    phases: [
      // `external_ref` é a identidade do entregável no Biahflow (ADR 0077) e o caminho
      // da rota de aceite. Os mesmos ids do snapshot semeado.
      //
      // O degrau da FDE e o gate (ADR 0081) chegam como a API os entrega. `Welcome` é
      // fase do Biahflow com `canonical_stage=discover` — o One **não** reclassifica o
      // que a origem afirma (Language Map §3, regra 2), e é por isso que ela continua
      // aqui embora tenha saído da casca de demonstração, que é nossa. `Prove` é o
      // ramo "exige gate e ninguém decidiu"; o ramo decidido é injetado por override
      // no teste de SSR, pela mesma razão dos outros: uma fixture só desenha um caso.
      { name: "Welcome", description: "Boas-vindas e acessos.", state: "done", target_date: null, canonical_stage: "discover", gate_decision: null, requires_gate: false, deliverables: [{ name: "Acesso ao portal", state: "delivered", link: null, external_ref: "91" }] },
      { name: "Prove", description: "A menor implementação real, em produção controlada.", state: "active", target_date: "2026-09-20", canonical_stage: "prove", gate_decision: null, requires_gate: true, deliverables: [{ name: "Funcionário Digital", state: "pending", link: null, external_ref: "92" }] },
      { name: "Scale", description: "Expansão para mais áreas.", state: "locked", target_date: null, canonical_stage: "scale", gate_decision: null, requires_gate: false, deliverables: [] },
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
      // Aditivo (ADR 0085): os quatro campos legados acima continuam vindo, e a
      // lista nova diz quais KPIs este funcionário move. Os dois ids estão em
      // `kpis` abaixo — o caso "id que não casa com nenhum KPI local" é do Value
      // Ledger, e é exercitado lá, porque só ele é escopado por mandato.
      kpi_ids: [12, 15],
    },
  ],
  // Os KPIs do projeto, e os dois casos de nulidade que a issue #89 separa
  // (ADR 0085): o `12` está medido dos dois lados; o `15` tem **janela sem
  // número** no Outcome — "a janela existe e ninguém mediu ainda" —, que é
  // exatamente o que não pode virar zero na tela.
  kpis: [
    {
      id: 12,
      name: "Horas de conciliação por mês",
      definition: "Horas do time contábil gastas conciliando contas a pagar.",
      formula: "Soma das horas apontadas no fechamento mensal.",
      unit: "hours",
      direction: "down",
      data_source: "Apontamento de horas do time contábil",
      cadence: "monthly",
      target: 20.0,
      baseline: { value: 72.0, period_start: "2026-03-01", period_end: "2026-03-31", measured_at: "2026-04-02T14:00:00-03:00", confidence: 80 },
      outcome: { value: 21.5, period_start: "2026-07-01", period_end: "2026-07-31", measured_at: "2026-08-02T11:00:00-03:00", confidence: 90 },
      monitoring: [
        { value: 38.0, period_start: "2026-05-01", period_end: "2026-05-31", measured_at: "2026-06-02T10:00:00-03:00", confidence: 70 },
      ],
    },
    {
      id: 15,
      name: "Divergências reabertas",
      definition: "Conciliações que voltaram para revisão manual depois de fechadas.",
      formula: null,
      unit: "count",
      direction: "down",
      data_source: "Fila de exceções do ERP",
      cadence: "monthly",
      // Sem meta é `null`, nunca zero — zero seria a tela afirmando uma meta que
      // ninguém combinou.
      target: null,
      baseline: { value: 34.0, period_start: "2026-03-01", period_end: "2026-03-31", measured_at: "2026-04-02T14:00:00-03:00", confidence: 70 },
      outcome: { value: null, period_start: "2026-07-01", period_end: null, measured_at: null, confidence: null },
      monitoring: [],
    },
  ],
  // O razão do **mandato**, não do projeto (ADR 0085). A segunda entrada aponta
  // para um KPI que não está em `kpis` acima: ele vive num projeto irmão do mesmo
  // Engagement, e não casar é caso normal — a tela mostra a entrada sem o vínculo.
  value_ledger: [
    { id: 3, value_type: "cost_saving", amount: 48000.0, quantity: 606.0, period_start: "2026-07-01", period_end: "2026-07-31", attribution_method: "Diferença Baseline→Outcome do KPI 12 × custo-hora do time contábil", kpi_id: 12, outcome_measured_at: "2026-08-02T11:00:00-03:00" },
    { id: 4, value_type: "revenue", amount: 12500.0, quantity: null, period_start: "2026-06-01", period_end: "2026-06-30", attribution_method: "Receita adicional atribuída ao atendimento fora do horário comercial", kpi_id: 41, outcome_measured_at: null },
  ],
  // O Discovery da **conta** (ADR 0086), com os três casos que a aba tem de saber
  // desenhar: um achado com evidência, uma **pergunta em aberto** (rotulada como
  // lacuna, e que não some), e uma oportunidade **sem Opportunity Score**, que vai
  // para o fim da lista com a frase e nunca com um zero. O caso de tudo vazio — que
  // é o estado real enquanto o Pulse não tiver tela de publicar — é exercitado por
  // override em `rendered-html.test.mjs`, sobre esta mesma base.
  processes: [
    {
      id: 301,
      name: "Conciliação de contas a pagar",
      position: 0,
      updated_at: "2026-08-10T09:00:00-03:00",
      steps: [
        { id: 3101, position: 0, name: "Receber a nota", pessoas: "2 analistas", sistema: "ERP", dados: "XML da NF-e", tempo: "4h/dia", erro: "Nota em duplicidade", retrabalho: "Refazer o lançamento" },
        { id: 3102, position: 1, name: "Conferir o pedido", pessoas: "1 analista", sistema: "Planilha", dados: "Pedido de compra", tempo: "2h/dia", erro: null, retrabalho: null },
      ],
    },
  ],
  findings: [
    {
      id: 401,
      statement: "A conferência do pedido é feita duas vezes pela mesma pessoa.",
      epistemic_status: "fact",
      confidence: 90,
      process_id: 301,
      step_id: 3102,
      evidences: [
        { id: 5001, kind: "observation", reference: "Sessão de Discovery de 12/08", captured_at: "2026-08-12T15:00:00-03:00" },
      ],
    },
    { id: 402, statement: "Não se sabe quantas notas chegam fora do padrão do fornecedor.", epistemic_status: "unknown", confidence: null, process_id: 301, step_id: null, evidences: [] },
  ],
  pain_points: [
    { id: 501, title: "Retrabalho na conferência", description: "A mesma nota é conferida duas vezes antes de virar lançamento.", impact_type: "time", impact_estimate: 120.0, finding_ids: [401, 402], status: "confirmed" },
    // Impacto **não quantificado**: `null`, e a tela escreve a frase — nunca "0".
    { id: 502, title: "Fila de exceções sem dono", description: null, impact_type: null, impact_estimate: null, finding_ids: [], status: "confirmed" },
  ],
  improvement_opportunities: [
    {
      id: 601,
      title: "Automatizar a conferência de notas",
      desired_change: "Conferir por regra, com exceção encaminhada para uma pessoa.",
      impact_hypothesis: "Devolve cerca de 4h/dia ao time contábil.",
      pain_point_ids: [501],
      status: "backlog",
      priority_assessment: { version: 2, score: 82, dimensions: { impact: 5, evidence_strength: 4, feasibility: 3, time_to_value: 4, economics: 5 } },
      solution_hypotheses: [
        { id: 701, statement: "Um Funcionário Digital concilia por regra.", intervention: "Regras no ERP mais fila de exceção", expected_effect: "70% das notas sem toque humano", status: "proposed" },
      ],
    },
    { id: 602, title: "Dar dono à fila de exceções", desired_change: null, impact_hypothesis: null, pain_point_ids: [502], status: "backlog", priority_assessment: null, solution_hypotheses: [] },
  ],
  documents: [
    { title: "Plano de implantação v3.pdf", type: "PDF", author: "Biahflow", link: null, updated_at: "2026-08-03T12:00:00+00:00" },
  ],
  meetings: [
    { title: "Comitê de projeto", date: "2026-08-28", recording_url: null, has_transcript: false, status: "scheduled" },
  ],
  // Uma com proveniência e outra sem: é o corte que o filtro da aba oferece, e o
  // `meeting_title` nulo é o caso real de uma reunião arquivada no Biahflow.
  decisions: [
    { title: "Adotar fila gerenciada", rationale: "O volume previsto não paga o Memorystore.", decided_on: "2026-08-06", owner_label: "Marina Farias", meeting_title: "Comitê de projeto" },
    { title: "Adiar o PROVE de cobrança", rationale: null, decided_on: null, owner_label: null, meeting_title: null },
  ],
  // Três abertas com prioridades diferentes, e a alta é a **mais antiga** de
  // propósito: é o que torna a ordenação da ADR 0029 observável no HTML do SSR.
  // Ordenada por data, "Aprovar fluxo de exceções" viria por último.
  //
  // A `priority` dizia `"normal"` até esta fatia — valor que `PendingPriority`
  // não tem. Passava porque o contrato declarava `str`; hoje declara os três.
  pendings: [
    { id: "eeeeeeee-1111-4222-8333-000000000001", title: "Renovar o certificado do integrador", description: null, owner_label: "Acme Brasil", state: "open", priority: "low", origin: "biahflow", opened_by_message_id: null, opened_by_conversation_id: null, comment_count: 0, created_at: "2026-08-04T10:00:00+00:00", resolved_at: null },
    { id: "eeeeeeee-1111-4222-8333-000000000002", title: "Enviar lista de usuários do PROVE", description: null, owner_label: "Acme Brasil", state: "open", priority: "medium", origin: "biahflow", opened_by_message_id: null, opened_by_conversation_id: null, comment_count: 0, created_at: "2026-08-03T10:00:00+00:00", resolved_at: null },
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

/** `GET /api/v1/me/notifications` — a caixa do projeto atual (Fase 2, ADR 0012).
 *
 *  Os dois `link` eram `null` até a ADR 0056, e nada pegava: o esquema declara
 *  `string | null`, então o ramo `<a>` da Central — o único controle que o campo
 *  tem — era **código morto nos testes**. É a mesma classe de defeito que a
 *  ADR 0043 encontrou no próprio campo, um nível acima. Agora eles trazem o link
 *  real, com a âncora do item, e batem com o rótulo das listas acima. */
export const NOTIFICATIONS = {
  unread_count: 2,
  items: [
    {
      id: "aaaaaaaa-1111-4222-8333-444444444444",
      kind: "milestone_done",
      title: "Marco concluído",
      detail: "Validação de integrações",
      link: "/?project=11111111-2222-4333-8444-555555555555&tab=Cronograma&item=milestone%3AValida%C3%A7%C3%A3o%20de%20integra%C3%A7%C3%B5es",
      occurred_at: "2026-08-03T12:00:00+00:00",
      read: false,
    },
    {
      id: "bbbbbbbb-1111-4222-8333-444444444444",
      kind: "document_added",
      title: "Novo documento no projeto",
      detail: "Plano de implantação v3.pdf",
      link: "/?project=11111111-2222-4333-8444-555555555555&tab=Documentos&item=document%3APlano%20de%20implanta%C3%A7%C3%A3o%20v3.pdf",
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
      item_anchor: "document:Contrato de manutenção",
    },
    {
      kind: "chunk",
      title: "Contrato de manutenção",
      detail: "…a cláusula de rescisão antecipada exige aviso de trinta dias…",
      location: "página 2",
      tab: "Documentos",
      document_id: "cccccccc-1111-4222-8333-444444444444",
      item_anchor: "document:Contrato de manutenção",
    },
  ],
};

/** `GET /api/v1/me/deliverables/{ref}/acceptance` — o histórico de aceite (ADR 0077).
 *
 *  Duas decisões e nesta ordem, que é a da escrita: a supersessão só existe
 *  porque a **última** é a que vale, e uma fixture com uma decisão só deixaria o
 *  histórico riscado — o núcleo da fatia — sem exercício nenhum.
 *
 *  Não é o que o stub serve por padrão: o estado comum é "ninguém decidiu ainda",
 *  e é ele que o contador de "aguardando você" precisa saber contar. Quem quer o
 *  histórico o injeta, como `archivedDashboard()` injeta o projeto encerrado. */
export const ACCEPTANCES = {
  deliverable_external_ref: "91",
  items: [
    {
      id: "dddddddd-1111-4222-8333-444444444441",
      deliverable_external_ref: "91",
      phase_name: "Welcome",
      deliverable_name: "Acesso ao portal",
      action: "changes_requested",
      actor_label: "Marina Farias",
      actor_is_internal: false,
      comment: "Faltou o anexo de custos na seção 4.",
      created_at: "2026-08-18T09:10:00+00:00",
    },
    {
      id: "dddddddd-1111-4222-8333-444444444442",
      deliverable_external_ref: "91",
      phase_name: "Welcome",
      deliverable_name: "Acesso ao portal",
      action: "accepted",
      actor_label: "Marina Farias",
      actor_is_internal: false,
      comment: "Aprovado. Pode seguir para produção.",
      created_at: "2026-08-19T14:22:00+00:00",
    },
  ],
};
