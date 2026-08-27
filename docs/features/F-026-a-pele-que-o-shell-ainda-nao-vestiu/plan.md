# F-026 — Execution Plan

Produzido pelo Planner a partir da [FDD 026](../../fdd/026-a-pele-que-o-shell-ainda-nao-vestiu.md)
(Feature Contract aceito) e do **DAP r1 aprovado** (visual e cópia, Daniel Campos, 26/08/2026 —
[design-approval.md](design-approval.md)). Formato canônico: o bloco `FEATURE EXECUTION PLAN` do
[contrato do Planner](../../engineering-os/agents/planner.md).

> **Plano real — o gate de design foi atravessado.** A versão anterior deste arquivo era um
> registro de bloqueio (`DESIGN_APPROVAL_REQUIRED`, `tasks: []`), porque F-026 é integralmente
> superfície e o DAP r1 estava `Awaiting approval`. Com o DAP r1 **Approved**, o mapeamento
> utilitário→token está fixado e o Planner decompôs. As duas *Open questions* do DAP foram
> **resolvidas no gate** (26/08/2026, Daniel Campos): `.nav-item` ativo = **`brand-50`** e as abas
> longas entram **nesta fatia** — dobradas em T02 e T03 abaixo.

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
    lógica — sequenciadas para não conflitar no mesmo arquivo. Com as abas nesta fatia, T03 cresce
    (mesmos seletores, mais telas), mas segue no mesmo arquivo e na mesma ordem.

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
           conforme a tabela §1 do DAP (bg-white→bg-surface, slate→muted/surface-sunken, etc.),
           INCLUSIVE o .nav-item ativo = bg-brand-50 text-brand-700 (decisão do gate).
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
    goal: Mapa §2 — status-card, métricas, jornada, pendências, E as abas longas (decisão do gate).
    scope: remapear .status-card/.progress/.status-meta/.timeline-dot/.pending-avatar/
           .priority-pill/.file-icon/.comment-input/.filter-chip em app/globals.css conforme §2;
           E aplicar o mesmo mapa §1–§2 aos seletores das abas longas (Resultados/Documentos/
           Cronograma/Reuniões/Decisões) — herança do mapa, sem token novo (decisão do gate 26/08).
    out_of_scope: sidebar/topbar (T02); primitivas (T04).
    expected_areas: app/globals.css
    acceptance_criteria: idem T02 para os seletores de §2 e das abas longas; correção de contraste
                         (slate-400→muted) aplicada; nenhum slate-*/bg-white cru remanescente nelas.
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
  - RESOLVED (design, DAP §Open questions, gate 26/08/2026): .nav-item ativo = bg-brand-50 (marca).
    Dobrado no escopo de T02.
  - RESOLVED (escopo, DAP §Open questions, gate 26/08/2026): as abas longas entram nesta fatia.
    Dobrado no escopo de T03 (mesmo mapa, mais telas).
```

## Validação do plano

`PLAN_VALIDATION: PLAN_VALID`. O gate de **design** foi cumprido (DAP r1 Approved) e o **gate humano
de aprovação de plano** também — aprovado por Daniel Campos em 26/08/2026, com as duas Open questions
resolvidas (nav `brand-50`; abas nesta fatia). O plano está **congelado para execução**: os Task
Contracts (`tasks/T01.md`…) podem ser derivados; qualquer mudança vira `PLAN_DEVIATION`.

Auto-checagem do Planner (não substitui a validação): IDs únicos (T01–T05); todo `depends_on` nomeia
tarefa existente; sem ciclos (T01 isolado; T02→T03→T04→T05); `parallel_groups` só junta T01 (sem
overlap com o resto); caminho crítico nomeado, esforço dominante em T04.

## PLAN_DEVIATION

Registrados pela sessão de execução em 27/08/2026, com autorização humana. O plano congelado
**não** foi editado acima; estes são os desvios entre o planejado e o executado.

### 1 — Uma branch por feature, não por Task Contract

| Campo | Valor |
| --- | --- |
| Tarefa | T01–T05 |
| Planejado | `integration_strategy`: uma branch de tarefa por Task Contract; T02→T03→T04 integradas em série |
| Real | Uma branch/PR por **feature**, com as cinco tarefas em série dentro dela |
| Impacto | Menos pontos de merge humano; diff de revisão maior. A ordem T02→T03→T04 sobre `app/globals.css` foi **preservada** dentro da branch, então o `PARALLELISM_RISK` original segue resolvido |
| Resolução | Autorizado por Daniel Campos em 27/08/2026 |

### 2 — T04 migrou parcialmente: três vocabulários legados permanecem

| Campo | Valor |
| --- | --- |
| Tarefa | T04 |
| Planejado | `scope`: substituir o desenho à mão de estado (`.state--*`/`.health-pill`/`.priority-pill`) por `<StatePill>` e os botões crus (`.ai-button`/`.text-button`) por `<Button>`, "removendo os seletores legados órfãos". `acceptance_criteria`: "nenhum seletor de estado/botão legado sem uso" |
| Real | Migrados `.state--*` (6 sítios) e o `.ai-button` do herói. **Não** migrados `.health-pill`, `.priority-pill` e `.text-button`; `.state--done` removido por ficar órfão |
| Impacto | O shell passa a ter dois vocabulários de estado convivendo. Nenhum valor visual mudou — que era a restrição mais forte |
| Resolução | **Aceito por Daniel Campos em 27/08/2026** como desvio consciente |

**Por que o desvio é a leitura correta dos artefatos aprovados, e não uma tarefa inacabada.**
A migração completa é impossível sem violar um dos dois artefatos que governam a fatia, e a
medição está registrada:

- **Falta variante neutra.** `components/one/StatePill.tsx` expõe exatamente quatro variantes
  (`success`, `warning`, `danger`, `info`). `.health-pill--archived`, `.priority-pill--low` e
  `.state--2` são **cinzas neutros**, sem correspondente. Criá-la é alterar a primitiva, que o
  §Out of Scope da própria T04 proíbe ("não mudar as primitivas").
- **As geometrias divergem.** `.state-pill` é `px-2.5 py-1 text-[10.5px]`; `.health-pill` é
  `px-3 py-1.5 text-[11px]`; `.priority-pill` é `px-2 py-0.5 text-[10px]`. Migrar redimensiona
  a pastilha — um **valor visual novo**, que o DAP aprovado proíbe ("Nenhum valor novo").
  `.state--*` não tem esse problema (mesmo padding e raio de `.state-pill`), e por isso migrou.
- **`.text-button` não tem variante isovalente.** É `text-brand-600 font-bold text-xs`, sem borda
  e sem `min-h-11`; `ghost` é `text-muted` e `secondary` é superfície branca com borda. Converter
  mudaria cor, peso e altura de "Ver cronograma", "Ver todas as pendências" e "Ver a pergunta".

`.state--1/0/2/3`, `.ai-button` e `.text-button` **não são órfãos**: `/admin/*` e `app/error.tsx`
seguem os usando, então removê-los quebraria superfície fora do escopo desta fatia.

**Fica aberto (não é dívida silenciosa).** Fechar o vocabulário exige uma revisão de design que
decida a variante neutra e a geometria única — trabalho de DAP, não de build. Some-se a isso uma
**contradição entre dois artefatos aprovados**, achada ao executar: `design/one-shell-tokens.html`
(linha 130) desenha o neutro `p-grey-d` **com ícone de cadeado**, enquanto as
`../F-025-.../design/captures-r4/` — o alvo de aparência que este plano declara em `assumptions` —
o desenham **sem ícone**. A fatia seguiu o alvo de aparência; a divergência precisa de decisão de
design, e está registrada aqui para não se perder.

### Achados fora de escopo, registrados e não corrigidos

- `aria-current="page"` não existe no item de navegação ativo, embora o DAP o liste em "o que a
  implementação garante". Nenhum Task Contract o possui.
- O DAP afirma que o chat "já consome os tokens; nada muda de forma nem de cor" — **falso**:
  `.chat-panel`, `.message--assistant p`, `.chat-suggestions button` e `.message-feedback*` ainda
  têm `bg-white`, e `.chat-header span i` tem `bg-emerald-500`. Chat está fora de escopo.
- O DAP afirma que vazio/carregando/erro/404 estão "já tokenizados na F-025" — **falso**:
  `.state-card p` é `text-slate-600` e `.state-code code` é `bg-slate-100`. A instrução era
  "conferidos, não reescritos"; foram conferidos e não reescritos.
- Três utilitários crus sem token de destino: `.project-logo` e `.pending-avatar--blue`
  (`sky-50/700`), `.metric-icon--purple` (`fuchsia-50/700`). Não há `sky`/`fuchsia` no `@theme`.
