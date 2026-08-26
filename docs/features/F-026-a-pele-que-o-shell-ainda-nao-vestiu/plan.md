# F-026 — Execution Plan

Produzido pelo Planner a partir da [FDD 026](../../fdd/026-a-pele-que-o-shell-ainda-nao-vestiu.md)
(Feature Contract aceito) e do **DAP r1 aprovado** (visual e cópia, Daniel Campos, 26/08/2026 —
[design-approval.md](design-approval.md)). Formato canônico: o bloco `FEATURE EXECUTION PLAN` do
[contrato do Planner](../../engineering-os/agents/planner.md).

> **Plano real — o gate de design foi atravessado.** A versão anterior deste arquivo era um
> registro de bloqueio (`DESIGN_APPROVAL_REQUIRED`, `tasks: []`), porque F-026 é integralmente
> superfície e o DAP r1 estava `Awaiting approval`. Com o DAP r1 **Approved**, o mapeamento
> utilitário→token está fixado e o Planner pode decompor. Duas *Open questions* do DAP **seguem em
> aberto** (a aprovação não as resolveu) e estão registradas em `planning_findings`; o Planner
> **não** as decide — uma é design (`.nav-item` ativo), a outra é escopo (abas longas).

## FEATURE EXECUTION PLAN

```text
feature_id: F-026

goal: Aplicar o mapeamento aprovado (utilitário cru → token semântico) e as primitivas StatePill/
      Button ao shell do cliente e ao dashboard, sem mudar dados/API/permissão.

assumptions:
  - Aparência-alvo = F-025 (DAP r4). O DAP r1 aprovado fixa a tabela de mapeamento §1–§3.
  - Nenhuma mudança de dados/contrato: tests/api-contract.test.mjs prova "dado inalterado".
  - As primitivas StatePill/Button já existem (components/one/); esta fatia as adota, não as cria.

risks:
  - PARALLELISM_RISK: T02, T03 e T04 editam app/globals.css (seletores disjuntos). Merge, não
    lógica — sequenciadas para não conflitar no mesmo arquivo.
  - Uma OPEN QUESTION do DAP (`.nav-item` ativo: brand-50 vs neutro) é decisão de DESIGN, não do
    Planner. T02 aplica todo o mapa §1 exceto esse valor, que fica pendente de micro-decisão.

tasks:
  - id: T01
    role: builder
    goal: Naming provisório remanescente → One.
    scope: "Notificações no portal" → "Notificações no One" em app/DashboardClient.tsx.
    out_of_scope: qualquer token; qualquer primitiva.
    expected_areas: app/DashboardClient.tsx
    acceptance_criteria: rendered-html.test.mjs verde; nenhuma outra ocorrência de "portal" como
                         marca em superfície de cliente.
    depends_on: []
    validation: web-unit-contract (npm test).
    required_capabilities: [react]
    risk: trivial.
    relative_effort: XS

  - id: T02
    role: builder
    goal: Mapa §1 — sidebar e topbar: @apply cru → token semântico.
    scope: remapear .sidebar/.topbar/.sidebar-toggle/.nav-item/.breadcrumb em app/globals.css
           conforme a tabela §1 do DAP (bg-white→bg-surface, slate→muted/surface-sunken, etc.).
           EXCETO o valor de .nav-item ativo (ver planning_findings, open question de design).
    out_of_scope: status-card/métricas/jornada/pendências (T03); primitivas (T04).
    expected_areas: app/globals.css
    acceptance_criteria: guarda de consumo de token verde; nenhum slate-*/bg-white cru remanescente
                         nos seletores de §1; aparência bate com captures-r4 da F-025.
    depends_on: []
    validation: web-unit-contract.
    required_capabilities: [tailwind, css]
    risk: baixo.
    relative_effort: S

  - id: T03
    role: builder
    goal: Mapa §2 — status-card, métricas, jornada, pendências.
    scope: remapear .status-card/.progress/.status-meta/.timeline-dot/.pending-avatar/
           .priority-pill/.file-icon/.comment-input/.filter-chip em app/globals.css conforme §2.
    out_of_scope: sidebar/topbar (T02); primitivas (T04).
    expected_areas: app/globals.css
    acceptance_criteria: idem T02 para os seletores de §2; correção de contraste (slate-400→muted)
                         aplicada.
    depends_on: [T02]
    validation: web-unit-contract.
    required_capabilities: [tailwind, css]
    risk: baixo.
    relative_effort: S

  - id: T04
    role: builder
    goal: Adotar as primitivas StatePill/Button no shell.
    scope: substituir o desenho à mão de estado (.state--*/.health-pill/.priority-pill) por
           <StatePill> e os botões crus (.ai-button/.text-button) por <Button> no shell
           (app/DashboardClient.tsx), removendo os seletores legados órfãos de app/globals.css.
    out_of_scope: mudar as primitivas; mapa de cor (T02/T03).
    expected_areas: app/DashboardClient.tsx; app/globals.css
    acceptance_criteria: inertButtons() verde (Button satisfaz por construção); estados renderizam
                         ícone junto do texto; nenhum seletor de estado/botão legado sem uso.
    depends_on: [T03]
    validation: web-unit-contract.
    required_capabilities: [react, tailwind]
    risk: médio — mexe no JSX do shell; a guarda de affordance e a de literais são a rede.
    relative_effort: M

  - id: T05
    role: builder
    goal: Evidência de navegador e prova de dado inalterado.
    scope: capturas desktop + mobile 390×844 das superfícies tocadas, comparadas às captures-r4 da
           F-025; rodar tests/api-contract.test.mjs (prova de que nenhum campo consumido mudou).
    out_of_scope: qualquer mudança de estilo.
    expected_areas: (evidência) docs/features/F-026-.../evidence/
    acceptance_criteria: capturas presas à revisão aprovada; api-contract verde sem mudança de
                         fixture; foco/teclado validados (anel de foco da F-025 preservado).
    depends_on: [T01, T04]
    validation: web-unit-contract; browser-runtime-validation (na máquina).
    required_capabilities: [playwright]
    risk: baixo.
    relative_effort: S

parallel_groups:
  - [T01]  # naming é independente; roda em paralelo a T02.
           # T02/T03/T04 compartilham app/globals.css → NÃO paralelizar entre si.

critical_path: T02 → T03 → T04 → T05
               # o mapa de cor (T02/T03) precede a adoção das primitivas (T04, o M); T05 fecha.
               # T01 corre à parte.

integration_strategy: Uma branch de tarefa por Task Contract; T02→T03→T04 integradas em série por
                      editarem o mesmo app/globals.css. T05 valida ao fim. api-contract verde em
                      cada integração é a prova contínua de que a pele não tocou o dado.

human_gates:
  - Aprovação deste plano antes de READY_FOR_BUILD.
  - Merge humano por Task Contract; DONE só após evidência de navegador (desktop + mobile), revisão
    e decisão humana.

planning_findings:
  - OPEN QUESTION (design, DAP §Open questions): .nav-item ativo em brand-50 (marca, proposto) vs
    surface-sunken (neutro). É decisão de DESIGN; o Planner não a decide. T02 aplica o resto do
    mapa §1 e deixa esse único valor pendente de micro-decisão — não bloqueia a estrutura do plano.
  - OPEN QUESTION (escopo, DAP §Open questions): as abas longas (Resultados/Documentos/Cronograma/
    Reuniões/Decisões) herdam o mesmo mapa §1–§3 sem decisão visual nova. Incluí-las é MAIS COMMIT,
    não mais decisão. Se o gate de plano optar por incluí-las, estende o escopo de T03 (mesmos
    seletores, outras telas); se não, ficam para fatia seguinte. Não assumido aqui.
```

## Validação do plano

`PLAN_VALIDATION: PENDENTE`. O gate de **design** foi cumprido (DAP r1 Approved), o que destravou
este plano; falta o **gate humano de aprovação deste plano** antes de congelar para execução —
diferente de F-027/F-028, cujos planos já foram aprovados. Enquanto pendente, nenhum Task Contract é
derivado. Não me auto-aprovei.

Auto-checagem do Planner (não substitui a validação): IDs únicos (T01–T05); todo `depends_on` nomeia
tarefa existente; sem ciclos (T01 isolado; T02→T03→T04→T05); `parallel_groups` só junta T01 (sem
overlap com o resto); caminho crítico nomeado, esforço dominante em T04.

## PLAN_DEVIATION

Nenhum registrado (plano ainda não congelado).
