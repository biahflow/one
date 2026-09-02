# F-028 — Execution Plan

Produzido pelo Planner a partir da [FDD 028](../../fdd/028-o-frescor-que-a-jornada-nunca-teve.md)
(Feature Contract aceito) e da [ADR 0076](../../adr/0076-o-snapshot-que-precisava-de-versao-e-hora.md)
(aceita). O formato canônico é o bloco `FEATURE EXECUTION PLAN` do
[contrato do Planner](../../engineering-os/agents/planner.md).

> **Split registrado (decisão, não silêncio).** O DAP r1 desta feature está `Awaiting approval`
> (gate de design **aberto**). O contrato do Planner manda registrar `DESIGN_APPROVAL_REQUIRED` e
> **não planejar a superfície** não aprovada. Este plano decompõe **apenas o trabalho não-interface**
> — contrato de projeção, migração, reconciliação, projeção de API e a guarda de filtro —, que o
> `design-approval.md` permite avançar com o gate aberto. As tarefas de **UI** (carimbo de frescor,
> estado stale, decisões/gates na timeline) ficam listadas em `planning_findings` e **não** viram
> Task Contract até o Design Approval. Nada aqui decide desenho.

> **Leia antes das duas revisões (02/09/2026).** Tudo o que este arquivo diz sobre a ancoragem
> decisão→fase estar `DEPENDENCY_BLOCKED` **deixou de ser verdade em 31/08/2026**. O plano não é
> reescrito; a correção está em [`PLAN_DEVIATION 2`](#plan_deviation-2--o-dependency_blocked-caiu-02092026),
> no fim do arquivo.

## FEATURE EXECUTION PLAN

```text
feature_id: F-028

goal: Dar ao contrato de projeção Pulse→One versão e hora observada, com frescor honesto,
      reconciliação anti-regressão e filtro client-safe como portão — a parte não-interface da
      FDD 028, sob a ADR 0076 aceita.

assumptions:
  - ADR 0076 está aceita: observed_at + projection_version no envelope, colunas no Project,
    reconciliação por versão, filtro client-safe como teste. A migração pode citá-la (regra 4).
  - O lado Biahflow carimbará observed_at + projection_version no snapshot. Se não carimbar na
    primeira versão do contrato, vale o FALLBACK declarado na ADR 0076: synced_at = now() rotulado
    como "sincronizado há X" (não "observado há X"), e a reconciliação fica limitada a synced_at.
    O plano é válido nos dois casos; a diferença é qual coluna alimenta o frescor.
  - Nenhuma mudança de RLS/policy: só colunas novas e leitura. O portal segue sem originar status
    (ADR 0006/0008); a reconciliação recusa regressão, não decide fase.

risks:
  - PARALLELISM_RISK: T02, T03 e T04 editam todas integrations/biahflow.py (sync_snapshot e
    build_dashboard). São sequenciadas de propósito; não paralelizar entre si.
  - Dependência cross-repo (Biahflow) para observed_at/projection_version. Mitigada pelo fallback:
    a fatia entrega valor mesmo sem o carimbo da origem, dizendo a verdade sobre o que mediu.
  - A ancoragem decisão→fase na timeline está ABERTA na ADR 0076 (§Aberto) — não planejada aqui.

tasks:
  - id: T01
    role: builder
    goal: Colunas de frescor/versão no Project e migração aditiva que cita a ADR 0076.
    scope: models/project.py ganha observed_at, projection_version (e synced_at do fallback);
           migração Alembic aditiva em db/migrations/versions/, citando ADR 0076 no corpo.
    out_of_scope: qualquer leitura/projeção desses campos; qualquer UI.
    expected_areas: apps/api/src/portal_api/models/project.py; db/migrations/versions/
    acceptance_criteria: alembic upgrade head aplica; alembic check sem deriva;
                         test_migration_rules.py verde (aditiva, cita ADR aceita).
    depends_on: []
    validation: api-unit-integration (com Postgres/papéis locais); supply-chain n/a.
    required_capabilities: [alembic, sqlalchemy]
    risk: baixo — puramente aditivo.
    relative_effort: S

  - id: T02
    role: builder
    goal: sync_snapshot consome observed_at/projection_version do snapshot, com fallback.
    scope: em integrations/biahflow.py, ler os campos do envelope e persistir nas colunas de T01;
           sem carimbo da origem, gravar synced_at = now() e marcar a proveniência do dado.
    out_of_scope: a recusa anti-regressão (T03); a projeção (T04); UI.
    expected_areas: apps/api/src/portal_api/integrations/biahflow.py (sync_snapshot)
    acceptance_criteria: um snapshot com os campos os persiste; um sem eles cai no fallback rotulado;
                         teste de integração cobrindo os dois caminhos.
    depends_on: [T01]
    validation: api-unit-integration.
    required_capabilities: [sqlalchemy]
    risk: baixo.
    relative_effort: S

  - id: T03
    role: builder
    goal: Reconciliação anti-regressão em sync_snapshot, generalizando mark_project_deleted.
    scope: recusar aplicar snapshot com projection_version menor que o persistido (empate resolve
           por observed_at; ausência dos dois = comportamento atual, declarado); emitir
           projection.stale_rejected (sem interpolação) e adicionar a linha em runbooks/alerts.md
           no mesmo commit (guarda bidirecional, ADR 0034).
    out_of_scope: projeção (T04); UI.
    expected_areas: apps/api/src/portal_api/integrations/biahflow.py; docs/runbooks/alerts.md
    acceptance_criteria: snapshot fora de ordem/duplicado NÃO regride a projeção (teste dedicado);
                         test_telemetry.py verde (evento tem linha no alerts.md e vice-versa).
    depends_on: [T02]
    validation: api-unit-integration; telemetry guard.
    required_capabilities: [sqlalchemy]
    risk: médio — é a lógica central; o teste de fora-de-ordem é o que a fixa.
    relative_effort: M

  - id: T04
    role: builder
    goal: build_dashboard projeta frescor/versão; schemas + OpenAPI declarados.
    scope: em integrations/biahflow.py (build_dashboard) projetar observed_at/synced_at e a idade
           derivável; DashboardOut/MyDashboardOut em schemas.py ganham os campos (extra="forbid");
           regenerar docs/api/openapi.json (python -m portal_api.openapi --write).
    out_of_scope: renderização no BFF/tela (gated por Design Approval); reconciliação (T03).
    expected_areas: apps/api/src/portal_api/integrations/biahflow.py (build_dashboard);
                    apps/api/src/portal_api/schemas.py; apps/api/src/portal_api/openapi.py;
                    docs/api/openapi.json
    acceptance_criteria: test_openapi_contract.py verde (campos novos declarados, nenhum com nome de
                         segredo, 404 preservado); test_authorization.py verde (404 nunca 403).
    depends_on: [T01]
    validation: api-unit-integration; contract (web test:contract).
    required_capabilities: [pydantic, fastapi]
    risk: baixo.
    relative_effort: S

  - id: T05
    role: builder
    goal: Guarda de filtro client-safe — campo internal-only na projeção reprova.
    scope: teste que deriva do contrato os campos client-safe e reprova se um campo da lista
           internal-only da ADR 0067 (GitHub/CI/ClickUp/LangGraph/LangSmith/margens) aparecer na
           saída de build_dashboard; no espírito das guardas de consumo/telemetria existentes.
    out_of_scope: alterar o contrato; UI.
    expected_areas: apps/api/tests/ (nova guarda)
    acceptance_criteria: a guarda reprova ao injetar um campo internal-only na projeção e passa no
                         estado atual; roda sem rede/banco.
    depends_on: [T04]
    validation: api-unit-integration.
    required_capabilities: [pytest]
    risk: baixo.
    relative_effort: S

parallel_groups:
  - []  # nenhum: T02/T03/T04 compartilham biahflow.py; T01 precede tudo; T05 fecha.
        # T04 e T02 dependem só de T01, mas ambos editam biahflow.py → PARALLELISM_RISK,
        # por isso NÃO formam grupo paralelo. Execução é essencialmente linear.

critical_path: T01 → T02 → T03 → (T04 → T05)
               # T01 destrava tudo; T02/T03 são a reconciliação (o M do caminho); T04/T05 são a
               # projeção e sua guarda. Esforço dominante em T03.

integration_strategy: Uma branch de tarefa por Task Contract, integrando na ordem do caminho
                      crítico para não haver dois builders reescrevendo biahflow.py ao mesmo tempo.
                      Cada tarefa fecha com sua validação verde antes da próxima abrir.

human_gates:
  - Design Approval do DAP r1 (obrigatório antes de QUALQUER tarefa de UI — não planejadas aqui).
  - Aprovação de plano (este arquivo) antes de READY_FOR_BUILD.
  - Merge humano por Task Contract; DONE só após evidência, revisão e decisão humana.

planning_findings:
  - DESIGN_APPROVAL_REQUIRED: as superfícies de frescor/stale (carimbo, estado stale) e de
    decisões/gates na timeline NÃO são planejadas — o DAP r1 está Awaiting approval. Viram tarefas
    (renderização no BFF/JourneyPanel/status-card reusando o padrão readOnlyReason) só após o gate.
  - OPEN DECISION (ADR 0076 §Aberto): a ancoragem decisão→fase (marcação explícita do Pulse vs
    heurística por data) não está decidida; não planejada. Precisa de decisão com o lado Biahflow.
  - OPS PARAMETER: o limiar do stale é configuração de operação, fora do escopo de build.
  - CROSS-REPO: observed_at/projection_version dependem do lado Biahflow; o fallback da ADR 0076
    mantém a fatia entregável enquanto isso não chega.
```

## Validação do plano

`PLAN_VALIDATION: PLAN_VALID`. Validação de consistência atendida (IDs únicos, dependências
existentes, aciclicidade, critérios/validação/capacidades por tarefa, paralelismo seguro, caminho
crítico, estratégia de integração — auto-checagem abaixo) e **gate humano de aprovação de plano
cumprido** — aprovado por Daniel Campos em 26/08/2026. O plano está **congelado para execução**: os
Task Contracts (`tasks/T01.md`…) podem ser derivados; qualquer mudança vira `PLAN_DEVIATION`, não
edição do plano congelado.

Auto-checagem do Planner (não substitui a validação): IDs únicos (T01–T05); todo `depends_on` nomeia
tarefa existente; sem ciclos (T01→T02→T03; T01→T04→T05); `parallel_groups` vazio é honesto por
causa do `PARALLELISM_RISK` em `biahflow.py`; caminho crítico nomeado com o esforço dominante em T03.

## PLAN_DEVIATION

Registrados pela sessão de execução em 27/08/2026, com autorização humana. O plano congelado
**não** foi editado acima.

### 1 — Uma branch por feature, não por Task Contract

| Campo | Valor |
| --- | --- |
| Tarefa | T01–T05 |
| Planejado | `integration_strategy`: uma branch de tarefa por Task Contract |
| Real | Uma branch/PR por **feature**, com as cinco tarefas em série dentro dela |
| Impacto | Menos pontos de merge humano; diff maior. A ordem T02→T03→T04 sobre `integrations/biahflow.py` foi preservada, então o `PARALLELISM_RISK` original segue resolvido |
| Resolução | Autorizado por Daniel Campos em 27/08/2026 |

### 2 — T04 escreveu em `tests/` do BFF, fora do seu `expected_areas`

| Campo | Valor |
| --- | --- |
| Tarefa | T04 |
| Planejado | `expected_areas`: `integrations/biahflow.py`, `schemas.py`, `openapi.py`, `docs/api/openapi.json`. `out_of_scope`: "renderização no BFF/tela (gated por Design Approval)" |
| Real | Também `tests/fixtures/dashboard.mjs` e `tests/api-contract.test.mjs`, com **seis entradas em `NOT_CONSUMED`** (`review_by: 2026-11-30`) |
| Impacto | Nenhuma mudança de comportamento; a allowlist passa a carregar dívida datada |
| Resolução | Aceito pela sessão em 27/08/2026 |

**Por quê.** É consequência estrutural do split do plano, não descuido. A guarda de consumo da
ADR 0033 exige que todo campo de resposta tenha leitor no BFF; T04 entrega os três campos de
frescor e tem a renderização **proibida** pelo próprio contrato (gate de design). Sem a isenção,
o critério de aceite do T04 (`npm run test:contract` verde) era inalcançável. As duas
alternativas eram piores e estão registradas: mapear no BFF sem renderizar produz código morto
que a guarda **daria por consumido** — o defeito exato que a ADR 0033 existe para pegar —, e
segurar a API até a tela existir deixaria a origem sem onde carimbar. A isenção **vence**
(`review_by` real), no prazo da rodada de UI: se a tela não chegar, a guarda cobra de novo.

### Registro de qualidade da execução

Sem achados de revisão. A guarda nova (T05) foi **medida por mutação** — três mutações sobre a
projeção (campo interno no `return`; campo interno também declarado no contrato, o "atacante
diligente"; campo só no contrato, sem produtor) e uma sobre a de telemetria, cada uma verificada
vermelha e restaurada. Confirmado de forma independente pela sessão: **688 passed, 0 failed**
(baseline do `main`: 665), com a cadeia `0001…0031` aplicada do zero em banco isolado e
`alembic check` sem deriva.

---

# F-028 — Execution Plan · Revisão 2 (superfície de frescor e jornada)

> **Por que existe uma revisão 2.** A revisão 1 acima foi congelada com o gate de design **aberto**:
> o Planner registrou `DESIGN_APPROVAL_REQUIRED` e decompôs só o trabalho não-interface. O gate foi
> atravessado — **DAP r1 `Approved`** (Daniel Campos, 26/08/2026) — e as *Open questions* foram
> tratadas no gate de 27/08/2026. Com o desenho fixado, o Planner decompõe a superfície **exceto uma**
> (ver abaixo: a ancoragem decisão→fase ficou `DEPENDENCY_BLOCKED`, por decisão e não por omissão).
>
> A revisão 1 **não é reescrita**: T01–T05 permanecem como executados. Esta revisão **acrescenta**
> T06–T08.

## Resoluções do gate (27/08/2026, Daniel Campos)

| Open question do DAP r1 | Resolução | Efeito no plano |
| --- | --- | --- |
| `observed_at` da origem ou `synced_at` da cópia | **`observed_at` da origem**; sem carimbo, fallback para a hora da cópia **dito como tal** | Já implementado em T02 (rev. 1); T06 apenas **rotula com honestidade** |
| Limiar do stale | **Parâmetro de operação**, não de design | Fora do escopo de build; a tela reflete o resultado |
| Ancoragem decisão→fase | **Marcação explícita do Pulse** (`phase_ref` no snapshot) — o One projeta, **não infere** | **`DEPENDENCY_BLOCKED`**: exige campo novo no repositório Biahflow. **Não vira Task Contract aqui.** |

**A superfície "decisão/gate ancorada à fase" do DAP §Surfaces fica de fora desta fatia.** Não por
esquecimento: a alternativa (heurística por data) foi considerada e **recusada no gate**, porque
inferir a fase a partir de `decided_on` é exatamente a falsa precisão que `results.py` recusa por
princípio e contradiz "o One não origina nem bifurca estado do Pulse". A superfície entra quando o
lado Biahflow carimbar `phase_ref`.

## FEATURE EXECUTION PLAN (revisão 2 — acréscimo)

```text
feature_id: F-028

goal: Mostrar na jornada o frescor que T01–T04 passaram a medir — com rótulo honesto sobre O QUE foi
      medido — e representar visivelmente o stale, o indisponível e o carregando.

assumptions:
  - DAP r1 Approved é a autoridade visual; a pele é a da F-025, que a F-026 aplicou ao shell.
  - T01–T05 (revisão 1) estão integrados: as colunas existem, o sync as popula, a reconciliação
    recusa regressão, build_dashboard projeta e a guarda client-safe protege a fronteira.
  - O limiar do stale chega por configuração, não por constante no componente.

risks:
  - A tentação de rotular a hora da cópia como frescor da origem. É o defeito que a fatia inteira
    existe para negar; o rótulo é o entregável, não um detalhe de cópia.
  - A jornada já respeita encerrado/removido (ADR 0036/0037) — não regredir esse comportamento.

tasks:
  - id: T06
    role: builder
    goal: Carimbo de frescor na jornada, com rótulo honesto, e o estado stale.
    scope: renderizar "Atualizado há X" quando o dado vem de observed_at da origem, e
           "Sincronizado há X" quando vem do fallback — NUNCA a hora da cópia disfarçada de frescor
           da origem; acima do limiar, pill de stale + mensagem, no padrão readOnlyReason.
    out_of_scope: decidir o limiar (é operação); ancoragem decisão→fase (DEPENDENCY_BLOCKED).
    expected_areas: app/ (JourneyPanel/status-card)
    acceptance_criteria: os dois rótulos são distinguíveis e corretos por origem do dado (teste
                         cobrindo AMBOS); o stale aparece acima do limiar; nenhum token novo.
    depends_on: []
    validation: web-unit-contract.
    required_capabilities: [react, tailwind]
    risk: médio — o rótulo é a promessa da fatia.
    relative_effort: M

  - id: T07
    role: builder
    goal: Projeção indisponível e carregando, sem passar cache por atual.
    scope: estado de falha de fetch da projeção mostrado COMO indisponível (não como dado velho
           silencioso) e estado de carregando; preservar o comportamento de encerrado/removido.
    out_of_scope: fabricar qualquer dado de fallback.
    expected_areas: app/
    acceptance_criteria: falha de projeção NÃO renderiza dado cacheado sem indicação; encerrado e
                         removido seguem como antes (asserções existentes verdes).
    depends_on: [T06]
    validation: web-unit-contract.
    required_capabilities: [react]
    risk: baixo.
    relative_effort: S

  - id: T08
    role: builder
    goal: Evidência de navegador da revisão aprovada.
    scope: capturas desktop + mobile 390×844 de recente, stale e indisponível; foco/teclado.
    out_of_scope: mudança de estilo.
    expected_areas: (evidência) docs/features/F-028-.../evidence/
    acceptance_criteria: capturas presas à revisão aprovada do DAP; os três estados cobertos.
    depends_on: [T07]
    validation: web-unit-contract; browser-runtime-validation.
    required_capabilities: [playwright]
    risk: baixo.
    relative_effort: S

parallel_groups:
  - []  # T06→T07→T08 compartilham a superfície da jornada; execução linear.

critical_path: T06 → T07 → T08

integration_strategy: Uma branch para a superfície (ver PLAN_DEVIATION 1), integrando após T01–T05
                      estarem em main — a tela consome o que a projeção passou a devolver.

human_gates:
  - Aprovação desta revisão 2 antes de READY_FOR_BUILD da superfície.
  - Merge humano. DONE só após evidência desktop+mobile, revisão e decisão humana.

planning_findings:
  - DEPENDENCY_BLOCKED (decidido no gate de 27/08/2026): a ancoragem decisão→fase exige `phase_ref`
    carimbado pelo Pulse. É trabalho no repositório Biahflow e NÃO é planejado aqui. A superfície do
    DAP §Surfaces correspondente fica declaradamente fora desta fatia.
  - OPS PARAMETER: o limiar do stale é configuração de operação, fora do escopo de build.
  - A Issue #62 NÃO fecha por inteiro enquanto a ancoragem decisão→fase não existir — o critério
    "decisões/gates" depende dela. Registrado para não virar verde por omissão.
```

`PLAN_VALIDATION: PLAN_VALID` — pendente do gate humano de aprovação desta revisão 2.
Auto-checagem: IDs únicos e não colidentes com a revisão 1 (T06–T08); `depends_on` nomeia tarefa
existente; sem ciclos; `parallel_groups` vazio é honesto (superfície compartilhada).

## PLAN_DEVIATION 2 — o `DEPENDENCY_BLOCKED` caiu (02/09/2026)

| Campo | Valor |
| --- | --- |
| Tarefa | nenhuma das planejadas — a superfície estava **fora** das duas revisões |
| Estado planejado | ancoragem decisão→fase `DEPENDENCY_BLOCKED`, sem Task Contract, à espera de `phase_ref` no Pulse |
| Estado real | o Pulse carimba `phase_ref` desde **31/08/2026** (`biahflow/pulse#46`, ADR 0057 e FDD 032 de lá); o campo chegava no envelope e era **descartado na ingestão** |
| Impacto | o único critério de aceite em aberto da Issue #62 passou a ser construível, e as duas revisões deste plano ficaram afirmando um bloqueio que não existia mais |
| Resolução | construído fora deste plano, em fatia própria, sob a [ADR 0088](../../adr/0088-a-decisao-que-nao-sabia-que-fase-destravou.md), dentro do DAP r1 já aprovado (a superfície é a que ele desenha em §Surfaces) |

**As duas revisões acima não são reescritas** — elas registram o que foi planejado e por quê, e a
decisão que carregam continua valendo: a heurística por `decided_on` × janela da fase foi recusada
em dois gates humanos independentes e **não** foi reintroduzida como fallback. O que mudou é a
premissa de fato, não a decisão. Onde o texto delas diz `DEPENDENCY_BLOCKED` — linhas 40, 146,
217, 228, 262, 313 e 317 —, leia-se *resolvido em 02/09/2026 por esta deviation*.

