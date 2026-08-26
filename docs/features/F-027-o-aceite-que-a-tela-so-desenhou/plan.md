# F-027 — Execution Plan

Produzido pelo Planner a partir da [FDD 027](../../fdd/027-o-aceite-que-a-tela-so-desenhou.md)
(Feature Contract aceito) e da [ADR 0077](../../adr/0077-a-porta-de-volta-que-a-integracao-nao-tinha.md)
(aceita). Formato canônico: o bloco `FEATURE EXECUTION PLAN` do
[contrato do Planner](../../engineering-os/agents/planner.md).

> **Split registrado (decisão, não silêncio).** O DAP r1 desta feature está `Awaiting approval`
> (gate de design **aberto**). O contrato do Planner manda registrar `DESIGN_APPROVAL_REQUIRED` e
> **não planejar a superfície** de aceite. Este plano decompõe **apenas o trabalho não-interface** —
> identidade do entregável, tabela de aceite, rota/módulo e notificação —, que o `design-approval.md`
> permite avançar com o gate aberto. As tarefas de **UI** (card de revisão vivo, controles
> Aprovar/Pedir ajuste, histórico imutável, distinção merge≠aceite) ficam em `planning_findings` e
> **não** viram Task Contract até o Design Approval. Nada aqui decide desenho.

## FEATURE EXECUTION PLAN

```text
feature_id: F-027

goal: Dar identidade estável ao entregável e um registro de aceite append-only imutável, com rota
      de cliente (404 nunca 403) e aviso interno — a parte não-interface da FDD 027, sob a ADR 0077.

assumptions:
  - ADR 0077 está aceita: PhaseDeliverable ganha external_ref durável; deliverable_acceptance é
    append-only com GRANT só de INSERT (imutável por privilégio); accepted permite ACCEPTED, nunca
    DONE. A migração pode citá-la (regra 4).
  - O evento persistido é a FONTE DA VERDADE do aceite; o retorno ao Pulse projeta esse evento.
  - Elegibilidade (o que traz um entregável para ready_for_acceptance) vem do contrato de projeção
    (F-028/ADR 0076) ou, na ausência dela, do estado que o snapshot já traz. Não decidida aqui.

risks:
  - PARALLELISM_RISK: T01 e T02 são migrações Alembic — a cadeia de revisões é linear; sequenciar.
  - OPEN DECISION (ADR 0077 §Aberto): o mecanismo concreto do retorno por consumo (Biahflow puxa por
    rota autenticada vs webhook reverso) NÃO está decidido. O plano cobre a PERSISTÊNCIA do evento
    (a fonte da verdade, em T02); a EXPOSIÇÃO/consumo fica em planning_findings, não planejada.
  - superseded/cancelled não estão desenhados (§10 tem cinco rótulos); fora do enum de action.

tasks:
  - id: T01
    role: builder
    goal: Identidade estável do entregável — external_ref durável, populado pelo sync.
    scope: PhaseDeliverable ganha external_ref (id do Biahflow); sync_snapshot passa a populá-lo;
           migração aditiva. Precedente: PendingItem.external_ref.
    out_of_scope: a tabela de aceite (T02); rota (T03); UI.
    expected_areas: apps/api/src/portal_api/models/project.py;
                    apps/api/src/portal_api/integrations/biahflow.py (sync_snapshot);
                    db/migrations/versions/
    acceptance_criteria: alembic upgrade head aplica; alembic check sem deriva;
                         test_migration_rules.py verde; o external_ref sobrevive ao delete/recreate
                         do sync (teste de integração).
    depends_on: []
    validation: api-unit-integration.
    required_capabilities: [alembic, sqlalchemy]
    risk: baixo — aditivo.
    relative_effort: S

  - id: T02
    role: builder
    goal: Tabela deliverable_acceptance append-only, imutável por privilégio, escopo projeto.
    scope: modelo + migração citando ADR 0077 no corpo; herda _ProjectChildMixin; colunas
           deliverable_external_ref/phase_name/deliverable_name denormalizados, action (enum
           accepted|changes_requested), actor_user_id (SET NULL), actor_label, actor_is_internal,
           comment, created_at; policies TO portal_app escopadas a org+project (cópia de
           0021_pending_item_comment); GRANT SELECT, INSERT e NADA de UPDATE/DELETE.
    out_of_scope: rota/módulo (T03); notificação (T04); UI.
    expected_areas: apps/api/src/portal_api/models/; db/migrations/versions/
    acceptance_criteria: test_migration_rules.py verde (aditiva, cita ADR aceita, toca policy/GRANT);
                         test_rls_isolation.py com casos novos — insert cross-tenant rejeitado, e o
                         app role NÃO reescreve a linha (segunda decisão acrescenta).
    depends_on: [T01]
    validation: api-unit-integration (Postgres + papéis locais).
    required_capabilities: [alembic, sqlalchemy, rls]
    risk: médio — a imutabilidade por GRANT e a policy são o núcleo; os testes de RLS a fixam.
    relative_effort: M

  - id: T03
    role: builder
    goal: Módulo dedicado + rota de cliente de aceite (404 nunca 403).
    scope: deliverable_acceptance.py (o único escritor: record_acceptance + list_for_deliverable,
           None→404); POST /api/v1/me/deliverables/{external_ref}/acceptance no molde de
           add_pending_comment (CurrentPrincipal, 201, _refuse_when_read_only→409, TenantContext);
           DeliverableAcceptanceIn/Out em schemas.py (extra="forbid"); regenerar openapi.json.
    out_of_scope: notificação (T04); retorno ao Pulse (aberto); UI.
    expected_areas: apps/api/src/portal_api/deliverable_acceptance.py;
                    apps/api/src/portal_api/main.py; apps/api/src/portal_api/schemas.py;
                    apps/api/src/portal_api/openapi.py; docs/api/openapi.json
    acceptance_criteria: test_authorization.py verde (a rota nega 404 ao trocar de ator, nunca 403);
                         test_openapi_contract.py verde (schema declarado, sem campo com nome de
                         segredo); aprovar e pedir ajuste gravam; segunda decisão ACRESCENTA.
    depends_on: [T02]
    validation: api-unit-integration; contract (web test:contract).
    required_capabilities: [fastapi, pydantic]
    risk: baixo.
    relative_effort: M

  - id: T04
    role: builder
    goal: Aviso interno de aceite/pedido de mudança, sem vazar ao cliente.
    scope: novo NotificationKind (ALTER TYPE ... ADD VALUE, migração aditiva); entrada em AUDIENCE
           = _INTERNAL_ONLY (obrigatória); emitido por task sob portal_system FORA do diff
           (padrão queue_pending_comment_notification), dedupe_key por (external_ref, action),
           exclude_user_id; linha nova em runbooks/alerts.md no mesmo commit.
    out_of_scope: retorno ao Pulse; UI.
    expected_areas: apps/api/src/portal_api/notifications.py; apps/api/src/portal_api/worker.py;
                    db/migrations/versions/; docs/runbooks/alerts.md
    acceptance_criteria: o aviso sai para o time e NÃO chega ao cliente (guarda de AUDIENCE);
                         test_telemetry.py verde (evento tem linha no alerts.md e vice-versa);
                         não avisa o próprio autor.
    depends_on: [T03]
    validation: api-unit-integration; telemetry guard.
    required_capabilities: [sqlalchemy, celery]
    risk: baixo — mas a entrada em AUDIENCE é obrigatória, senão o aviso vaza ao cliente.
    relative_effort: S

parallel_groups:
  - []  # T01/T02 são migrações (cadeia linear); T03/T04 dependem em série. Execução linear.

critical_path: T01 → T02 → T03 → T04
               # T01 dá a âncora; T02 é o registro imutável (o M); T03 a rota; T04 o aviso.

integration_strategy: Uma branch por Task Contract, integrando na ordem do caminho crítico (a
                      cadeia de migrações força a ordem T01→T02). Cada tarefa fecha com validação
                      verde antes da próxima abrir.

human_gates:
  - Design Approval do DAP r1 (obrigatório antes de QUALQUER tarefa de UI — não planejadas aqui).
  - Aprovação de plano (este arquivo) antes de READY_FOR_BUILD.
  - Merge humano por Task Contract; DONE só após evidência, revisão e decisão humana. O One NUNCA
    marca done de Delivery.

planning_findings:
  - DESIGN_APPROVAL_REQUIRED: a superfície de aceite (card vivo, controles, histórico imutável,
    distinção merge≠aceite) NÃO é planejada — DAP r1 Awaiting approval. Vira tarefa após o gate.
  - OPEN DECISION (ADR 0077 §Aberto): o mecanismo concreto do retorno por consumo (rota autenticada
    vs webhook reverso, a decidir com o lado Biahflow) não é planejado. A persistência do evento
    (T02) é a fonte da verdade; a exposição espera a decisão.
  - CROSS-FEATURE: a elegibilidade do entregável depende do contrato de projeção (F-028/ADR 0076)
    ou do estado atual do snapshot; a decidir no gate.
  - superseded/cancelled fora do enum de action — exigem revisão de design própria.
```

## Validação do plano

`PLAN_VALIDATION: PENDENTE`. Aguarda a validação de consistência e o **gate humano de aprovação de
plano** antes de congelar. Enquanto pendente, nenhum Task Contract é derivado. Não me auto-aprovei.

Auto-checagem do Planner (não substitui a validação): IDs únicos (T01–T04); todo `depends_on` nomeia
tarefa existente; sem ciclos (T01→T02→T03→T04); `parallel_groups` vazio é honesto (cadeia de
migrações + fluxo em série); caminho crítico nomeado, esforço dominante em T02.

## PLAN_DEVIATION

Nenhum registrado (plano ainda não congelado).
