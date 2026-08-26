# F-026 — Execution Plan

Produzido pelo Planner a partir da [FDD 026](../../fdd/026-a-pele-que-o-shell-ainda-nao-vestiu.md)
(Feature Contract aceito). Formato canônico: o bloco `FEATURE EXECUTION PLAN` do
[contrato do Planner](../../engineering-os/agents/planner.md).

> **Plano bloqueado por design — e a razão é diferente da de F-027/F-028.** Aqueles têm trabalho
> não-interface (contrato, migração, reconciliação) que um DAP aberto não impede planejar, e por
> isso foram decompostos por *split*. **F-026 não tem esse split:** a feature **é** a superfície —
> remapear o `@apply` do shell de utilitário cru para token semântico e adotar as primitivas
> `StatePill`/`Button` **é** o que o DAP r1 decide (a tabela de mapeamento). Planejar as tarefas
> agora seria decompor a superfície não aprovada — exatamente o que o contrato do Planner proíbe:
> *"If the Feature Contract is classified `INTERFACE_CHANGE` and references no approved Design
> Approval Package for the affected surface, record `DESIGN_APPROVAL_REQUIRED` and do not plan that
> surface; do not decide the design."* O DAP r1 está `Awaiting approval`. Logo, este arquivo
> **registra o bloqueio e não produz um DAG de tarefas**. A decomposição contingente abaixo é
> **esboço, não plano** — não vira Task Contract até o gate.

## FEATURE EXECUTION PLAN

```text
feature_id: F-026

goal: Aplicar os tokens e primitivas já aprovados na F-025 ao shell do cliente e ao dashboard —
      uma feature integralmente de superfície.

assumptions:
  - A aparência-alvo é a já aprovada na F-025 (DAP r4). Esta fatia não introduz valor visual novo;
    o que o DAP r1 desta feature decide é o MAPEAMENTO utilitário→token e a adoção das primitivas.
  - Nenhuma mudança de dados/API/permissão: tests/api-contract.test.mjs é a rede que prova isso.

risks:
  - Sem o mapeamento aprovado, qualquer tarefa inventaria qual slate vira qual token — que é o
    desenho, e o Planner não o decide.

tasks: []   # NENHUMA. DESIGN_APPROVAL_REQUIRED: a feature é a superfície e o DAP r1 não está
            # aprovado. Decompor agora violaria o contrato do Planner. Ver planning_findings.

parallel_groups: []
critical_path: (indefinível antes do DAP aprovado)
integration_strategy: (definida após o gate — provável: uma branch, o mapa aplicado em
                       app/globals.css, com api-contract verde como prova de dado inalterado)

human_gates:
  - Design Approval do DAP r1 — BLOQUEIA todo o planejamento desta feature, não só parte dela.
  - Aprovação de plano (o plano real, produzido APÓS o Design Approval) antes de READY_FOR_BUILD.
  - Merge humano; DONE só após evidência de navegador (desktop + mobile), revisão e decisão humana.

planning_findings:
  - DESIGN_APPROVAL_REQUIRED (dominante): a feature é integralmente INTERFACE_CHANGE. Diferente de
    F-027/F-028, não há parcela não-interface a planejar com o gate aberto. O plano real nasce
    quando o DAP r1 for aprovado e o mapeamento utilitário→token estiver fixado.
  - OPEN QUESTION do DAP (não resolvível por agente): .nav-item ativo em brand-50 (marca) vs
    surface-sunken (neutro); e se as abas longas entram nesta fatia ou na seguinte. As duas mudam o
    recorte das tarefas — por isso o plano espera a resposta.
```

## Decomposição contingente (esboço, **não** é plano)

Só para dimensionar o que o plano real conterá **depois** do Design Approval. Não é um DAG válido,
não tem critérios de aceite completos e **não** deriva Task Contract. Muda com o que o gate aprovar.

- **~T01** — Naming: "Notificações no portal" → "One" (`DashboardClient.tsx`).
- **~T02** — Mapa §1 (sidebar/topbar): remapear `@apply` em `app/globals.css`.
- **~T03** — Mapa §2 (status-card/métricas/jornada/pendências): remapear `@apply`.
- **~T04** — Primitivas: adotar `StatePill`/`Button` no shell.
- **~T05** — Evidência de navegador (desktop + mobile 390×844) comparada às `captures-r4/` da F-025;
  `api-contract` verde.

Observação de recorte que o gate resolve: `~T02`/`~T03` editam o mesmo arquivo (`app/globals.css`)
em seletores disjuntos — `PARALLELISM_RISK` de merge, não de lógica; provavelmente uma tarefa só.

## Validação do plano

`PLAN_VALIDATION: N/A — BLOQUEADO`. Não há DAG a validar: o plano real depende do Design Approval do
DAP r1. Enquanto o gate estiver aberto, nenhum Task Contract é derivado e este arquivo permanece um
registro do bloqueio, não um plano de execução.

## PLAN_DEVIATION

Nenhum (não há plano congelado).
