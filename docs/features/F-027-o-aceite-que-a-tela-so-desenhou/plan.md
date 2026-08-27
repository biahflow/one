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

`PLAN_VALIDATION: PLAN_VALID`. Validação de consistência atendida (auto-checagem abaixo) e **gate
humano de aprovação de plano cumprido** — aprovado por Daniel Campos em 26/08/2026. O plano está
**congelado para execução**: os Task Contracts (`tasks/T01.md`…) podem ser derivados; qualquer
mudança de dependência ou trabalho vira `PLAN_DEVIATION`, não edição do plano congelado.

Auto-checagem do Planner (não substitui a validação): IDs únicos (T01–T04); todo `depends_on` nomeia
tarefa existente; sem ciclos (T01→T02→T03→T04); `parallel_groups` vazio é honesto (cadeia de
migrações + fluxo em série); caminho crítico nomeado, esforço dominante em T02.

## PLAN_DEVIATION

Registrados pela sessão de execução em 27/08/2026, com autorização humana. O plano congelado
**não** foi editado acima.

### 1 — Uma branch por feature, não por Task Contract

| Campo | Valor |
| --- | --- |
| Tarefa | T01–T04 |
| Planejado | `integration_strategy`: uma branch por Task Contract, na ordem do caminho crítico |
| Real | Uma branch/PR por **feature**, com as quatro tarefas em série dentro dela |
| Impacto | Menos pontos de merge humano; diff maior. A ordem T01→T02→T03→T04 foi preservada |
| Resolução | Autorizado por Daniel Campos em 27/08/2026 |

### 2 — T03 entregou também a rota `GET` do histórico

| Campo | Valor |
| --- | --- |
| Tarefa | T03 |
| Planejado | `scope` nomeia só `POST /api/v1/me/deliverables/{external_ref}/acceptance` |
| Real | `GET` **e** `POST` no mesmo molde (`add_pending_comment`, que tem o par) |
| Impacto | Uma rota a mais no contrato, com o mesmo predicado de tenant e o mesmo 404 |
| Resolução | Aceito pela sessão em 27/08/2026 |

**Por quê.** O `Goal` da própria T03 diz "e o histórico é **legível**", e o `scope` especifica
`list_for_deliverable` no módulo. Sem a rota, aquela função nasceria **sem chamador** — que é
exatamente o defeito que a ADR 0033 existe para pegar, e que a ADR 0029 resume em "o que ninguém
consome é pergunta para a API". Entregar o escritor sem o leitor contradiria o critério do próprio
contrato.

### 3 — T04 escreveu em `tests/api-contract.test.mjs`, fora do seu `expected_areas`

| Campo | Valor |
| --- | --- |
| Tarefa | T04 |
| Planejado | `expected_areas`: `notifications.py`, `worker.py`, `versions/`, `alerts.md` |
| Real | Também 1 entrada em `NOT_CALLED` e 4 em `NOT_SENT` (`review_by: 2027-02-01`) |
| Impacto | Nenhuma mudança de comportamento; a allowlist passa a carregar dívida datada |
| Resolução | Aceito pela sessão em 27/08/2026 |

**Por quê.** Mesma causa estrutural do desvio equivalente na F-028: a rota nova não tem chamador
no BFF porque **a interface está atrás do gate de Design Approval**, e a guarda de consumo cobra
chamador para toda rota. A isenção com motivo e prazo é o mecanismo declarado do próprio arquivo,
e ela **vence** — as linhas somem no commit que ligar a tela.

### 4 — Renome de revisão por limite do Alembic

`0034_phase_deliverable_external_ref` (35 caracteres) foi renomeada para
`0034_deliverable_external_ref`: `alembic_version.version_num` é `varchar(32)` e o `UPDATE`
falhava com `StringDataRightTruncation`. Medido, não suposto. A F-028 tropeçou no mesmo limite de
forma independente — vale para quem numerar a seguir.

### Ordem de merge obrigatória (PARALLELISM_RISK resolvido, não eliminado)

As migrações `0034`–`0036` desta branch apontam `down_revision` para `0030_whatsapp_reply_kind`,
head do `main` quando as duas features abriram. A F-028 ocupa `0031`. **A F-028 entra primeiro**;
esta branch é então rebaseada (`0034.down_revision` → `0031_projection_freshness`) e só depois é
mergeada. Mergear fora dessa ordem produz **dois heads**, e `alembic upgrade head` falha alto — o
erro é ruidoso, não silencioso, mas é erro.

### Registro de qualidade da execução

Sem achados de revisão. Confirmado de forma independente pela sessão, em banco isolado: **680
passed, 0 failed** (baseline do `main`: 665), `alembic check` sem deriva, e a prova que mais
importa tirada do próprio Postgres — `\dp portal.deliverable_acceptance` devolve
`portal_app=ar`, isto é **INSERT e SELECT e nada mais**: sem `w` (UPDATE) e sem `d` (DELETE). A
imutabilidade é privilégio, não convenção. O contrato publicado declara `404` e `409` nas duas
rotas e **nenhum 403**.

---

# F-027 — Execution Plan · Revisão 2 (superfície de aceite)

> **Por que existe uma revisão 2.** A revisão 1 acima foi congelada com o gate de design **aberto**:
> o contrato do Planner mandou registrar `DESIGN_APPROVAL_REQUIRED` e **não planejar a superfície**,
> e ela decompôs só o trabalho não-interface. O gate foi atravessado — **DAP r1 `Approved`** (Daniel
> Campos, 26/08/2026) — e as três *Open questions* que a aprovação deixou explicitamente em aberto
> foram **resolvidas no gate de 27/08/2026** (registro em §Resoluções do gate). Com o desenho fixado,
> o Planner decompõe a superfície.
>
> A revisão 1 **não é reescrita**: T01–T04 permanecem como executados. Esta revisão **acrescenta**
> T05–T08. É o mesmo princípio que a feature implementa no banco — quem escreve não reescreve.

## Resoluções do gate (27/08/2026, Daniel Campos)

| Open question do DAP r1 | Resolução | Efeito no plano |
| --- | --- | --- |
| Onde a superfície vive | **Aba própria "Revisão"** no nav, com contador de "aguardando você", **mais atalho** a partir do card do entregável na jornada | T05 cria a aba; T07 cria o atalho |
| Comentário em **Aprovar** | **Opcional** (campo presente, dispensável). Em *Pedir ajuste* segue esperado | T06 |
| Elegibilidade (`ready_for_acceptance`) | Vem do estado que o snapshot **já** traz; se F-028 entregar contrato de projeção antes, ele passa a ser a fonte | Assunção de T05, declarada |
| `superseded`/`cancelled` como rótulo visual | **Fora** — exige revisão de design própria | permanece fora |

## FEATURE EXECUTION PLAN (revisão 2 — acréscimo)

```text
feature_id: F-027

goal: Tornar real a superfície reservada da F-025 §10 — card de revisão vivo, controles que agem,
      histórico imutável com supersessão visível e a distinção merge≠aceite na tela.

assumptions:
  - DAP r1 Approved é a autoridade visual; nenhum token de cor novo (os cinco rótulos e seus tons
    são retidos da F-025). Se o pacote divergir do CSS, o CSS vence.
  - T01–T04 (revisão 1) estão integrados: existe external_ref, tabela append-only, rota de aceite e
    aviso interno. A UI CONSOME essa rota; não cria caminho de escrita novo.
  - A elegibilidade sai do snapshot atual (ver §Resoluções do gate).

risks:
  - PARALLELISM_RISK: T05, T06 e T07 editam a mesma superfície nova; sequenciadas.
  - A aba nova toca tabs.py, que é compartilhado com o link de notificação (ADR 0043) — um rótulo
    de aba errado quebra LINK_TAB e o sino. A guarda de link é a rede.
  - inertButtons() reprova controle sem onClick: os controles TÊM de agir nesta fatia.

tasks:
  - id: T05
    role: builder
    goal: Aba "Revisão" + card de revisão vivo, com os cinco rótulos e a distinção merge≠aceite.
    scope: nova aba em tabs.py (?tab= linkable, precedente ADR 0043) com contador de "aguardando
           você"; card do entregável elegível renderizando os cinco rótulos exatos e seus tons
           (ready_for_acceptance=brand, client_review=info, accepted=success,
           changes_requested=warning, done=CINZA); marcador separando "entrega de engenharia
           concluída" de "seu aceite pendente"; links de contexto/evidência já autorizados.
    out_of_scope: os controles que agem (T06); o histórico (T07); estados de superfície (T08).
    expected_areas: app/ (aba + card); apps/api/src/portal_api/tabs.py
    acceptance_criteria: rendered-html.test.mjs verde com asserções novas; guarda de LINK_TAB verde;
                         done renderiza CINZA (o cliente não o declara); nenhum token de cor novo.
    depends_on: []
    validation: web-unit-contract.
    required_capabilities: [react, tailwind]
    risk: médio — toca tabs.py, compartilhado com o sino.
    relative_effort: M

  - id: T06
    role: builder
    goal: Controles Aprovar / Pedir ajuste que AGEM, consumindo a rota de T03.
    scope: <Button> (primitiva da F-025) para "Aprovar entrega" com comentário OPCIONAL e "Pedir
           ajuste" com comentário esperado; repouso/hover/foco/desabilitado-enviando; confirmação
           "Enviado ao time da Biahflow"; anel de foco da F-025 preservado.
    out_of_scope: mudar a rota ou o contrato (T03 fechou); histórico (T07).
    expected_areas: app/
    acceptance_criteria: inertButtons() verde (todo controle age); a decisão chega à rota e volta
                         confirmada; 409 de projeto encerrado e 429 tratados sem fabricar resposta.
    depends_on: [T05]
    validation: web-unit-contract.
    required_capabilities: [react]
    risk: médio — é o caminho de escrita do cliente.
    relative_effort: M

  - id: T07
    role: builder
    goal: Histórico imutável visível, com supersessão explícita, e o atalho da jornada.
    scope: uma linha por decisão (ator + data); uma segunda decisão ACRESCENTA e a anterior aparece
           SUPERADA (riscada, com rótulo), nunca apagada — o reflexo na tela do GRANT só de INSERT;
           atalho [Revisar] do card do entregável na jornada para ?tab=revisao#<ancora>.
    out_of_scope: editar decisão in-place (proibido por desenho E por privilégio).
    expected_areas: app/
    acceptance_criteria: duas decisões renderizam duas linhas, a primeira marcada superada; nenhuma
                         affordance de edição de decisão; o atalho resolve a âncora (guarda de
                         âncora existente verde).
    depends_on: [T06]
    validation: web-unit-contract.
    required_capabilities: [react]
    risk: baixo.
    relative_effort: S

  - id: T08
    role: builder
    goal: Estados de superfície e evidência de navegador da revisão aprovada.
    scope: carregando, erro (serviço indisponível) e não autorizado (404, nunca 403); capturas
           desktop + mobile 390×844 dos estados aguardando/aprovado/ajuste-pedido; foco/teclado.
    out_of_scope: qualquer mudança de estilo nova.
    expected_areas: (evidência) docs/features/F-027-.../evidence/
    acceptance_criteria: as três telas de estado existem e não fabricam dado; capturas presas à
                         revisão aprovada do DAP; navegação por teclado alcança os controles.
    depends_on: [T07]
    validation: web-unit-contract; browser-runtime-validation.
    required_capabilities: [playwright]
    risk: baixo.
    relative_effort: S

parallel_groups:
  - []  # T05→T06→T07→T08 compartilham a superfície; execução linear.

critical_path: T05 → T06 → T07 → T08

integration_strategy: Uma branch para a superfície inteira (ver PLAN_DEVIATION 1), integrando após
                      T01–T04 estarem em main — a UI consome a rota que aquelas criaram.

human_gates:
  - Aprovação desta revisão 2 antes de READY_FOR_BUILD da superfície.
  - Merge humano. DONE só após evidência desktop+mobile, revisão e decisão humana.
  - O One NUNCA marca done de Delivery — o aceite do cliente permite ACCEPTED, nunca DONE.

planning_findings:
  - RESOLVED no gate de 27/08/2026: aba própria; comentário opcional em Aprovar. Ver §Resoluções.
  - OPEN DECISION (ADR 0077 §Aberto): o mecanismo do retorno ao Pulse (rota autenticada vs webhook
    reverso) segue não decidido e NÃO é planejado. A persistência do evento (T02) é a fonte da
    verdade; a exposição espera decisão com o lado Biahflow.
  - superseded/cancelled seguem fora do enum e fora do desenho.
```

`PLAN_VALIDATION: PLAN_VALID` — pendente do gate humano de aprovação desta revisão 2.
Auto-checagem: IDs únicos e não colidentes com a revisão 1 (T05–T08); `depends_on` nomeia tarefa
existente; sem ciclos; `parallel_groups` vazio é honesto (superfície compartilhada).

