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

Nenhum registrado (plano ainda não congelado).
