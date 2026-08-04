# FDD 004 — Resultados

Agentes enviam eventos idempotentes. Horas poupadas e custos evitados são agregados por período.
ROI líquido usa `(benefícios - investimento) / investimento` e mostra premissas configuradas
internamente.

## Estado

- **API de eventos autenticada por chave (Fase 3 / ADR 0013) — feito.** `POST /api/v1/agent-events`
  grava de fato, por `X-Agent-Key`. O tenant é propriedade da chave; `projectId` divergente é 404.
- **Premissa financeira com vigência (Fase 3 / ADR 0013) — feito.** `project_financial_assumption`
  e a tela `/admin/resultados` que a mantém.
- **Apuração por período (Fase 3 / ADR 0013) — feito.** `results.py`, exposto em
  `GET /api/v1/projects/{id}/results` e no bloco `measured` do dashboard.
- **Os três cards de demonstração — removidos.** Transações automatizadas, precisão do fluxo e
  exceções tratadas passaram a ler a apuração. Junto foi o fallback de `roiValue()`, que devolvia
  um percentual fixo quando o projeto não tinha ROI no snapshot.
- **Fora de escopo:** agregado materializado por dia (só faz sentido com volume que o justifique)
  e remoção das colunas legadas `hours_saved`/`value_amount`, que é item da Fase 5.

## Como o número é produzido

Um agente publica uma execução: quanto tempo poupou, quanto custo evitou, como terminou. O evento
guarda **o que foi reportado**, em inteiros — segundos e centavos. Nada é convertido na escrita.

Na leitura, cada evento é avaliado pela premissa vigente **no dia em que aconteceu**, o que impede
um aumento de valor-hora hoje de reprecificar março. As premissas, todas visíveis na resposta e na
tela:

| Grandeza | Regra |
|---|---|
| Horas economizadas | Σ `time_saved_seconds` ÷ 3600 |
| Economia apurada | Σ(horas × valor-hora vigente) + Σ `avoided_cost_cents` |
| Investimento do período | Investimento mensal rateado por dia, mês comercial de 30 dias |
| ROI apurado | (economia − investimento) ÷ investimento; **nulo** se investimento = 0 |
| Precisão do fluxo | (total − falhas) ÷ total; exceção tratada conta como acerto |
| Exceções tratadas | Contagem de `exception_handled`, com a fatia sem intervenção humana |
| Transações automatizadas | Contagem de eventos do período |

Onde falta base, o número vem nulo **com a razão** em `gaps` (`no_assumption`, `no_investment`,
`no_events`, `events_outside_assumption`) e a tela mostra um travessão e a explicação — a mesma
disciplina da regra 3 do `AGENTS.md`.

O ROI **projetado** (do snapshot do Biahflow) e o **apurado** convivem lado a lado, rotulados. São
números diferentes com origens diferentes, e fundir os dois faria o mesmo rótulo significar duas
coisas em momentos distintos.

## Credencial

Chave por projeto, com escopo, expiração obrigatória, rotação e revogação, emitida em
`/admin/resultados` por quem tem `internal_admin`. A chave em claro aparece **uma vez**: o banco
guarda um HMAC sob pepper de servidor, e não há caminho de volta. Recusa de credencial é sempre o
mesmo 401 opaco; estourar o rate limit é 429 com `Retry-After`.

### Critérios de aceite

| Critério | Coberto por |
|---|---|
| Reenvio do mesmo evento não duplica resultado | `test_agent_events.py::test_the_same_event_resent_does_not_duplicate` |
| O produtor distingue gravado de já existente | mesmo teste (`accepted` / `duplicate`) |
| O evento é guardado exatamente como reportado | `test_agent_events.py::test_the_event_is_stored_exactly_as_reported` |
| Sem chave, a rota é fechada | `test_agent_events.py::test_without_a_key_the_route_is_shut` |
| Chave revogada, expirada ou sem escopo não autentica | `test_a_revoked_key_is_rejected`, `test_an_expired_key_is_rejected`, `test_a_key_without_the_scope_is_rejected` |
| Toda recusa de credencial é indistinguível | `test_agent_events.py::test_every_refusal_looks_the_same` |
| Uma chave não publica em projeto alheio | `test_agent_events.py::test_a_key_cannot_publish_into_another_project`, `test_authorization.py::test_a_key_cannot_publish_into_another_organizations_project` |
| Sessão humana não vale nesta rota | `test_authorization.py::test_agent_events_reject_a_human_session` |
| Ritmo excessivo responde 429, não 401 | `test_agent_events.py::test_going_over_the_window_answers_429` |
| A janela reabre | `test_agent_events.py::test_a_new_window_lets_the_producer_through_again` |
| A chave nunca aparece na auditoria | `test_agent_events.py::test_the_audit_entry_carries_no_secret`, `test_admin_endpoints.py::test_the_key_audit_never_carries_the_secret` |
| A chave em claro é devolvida uma vez e não é armazenada | `test_admin_endpoints.py::test_the_plaintext_key_is_returned_once_and_never_stored` |
| O que a tela emite é o que o agente usa | `test_admin_endpoints.py::test_a_minted_key_actually_authenticates_the_ingestion` |
| Rotacionar substitui e preserva o rastro | `test_admin_endpoints.py::test_rotating_replaces_the_key_and_keeps_the_trail` |
| Revogar corta o acesso na hora | `test_admin_endpoints.py::test_a_revoked_key_stops_working_immediately` |
| Nenhuma rota nova de resultados é alcançável por cliente | `test_admin_endpoints.py::test_no_client_member_reaches_the_results_administration` |
| Valor-hora posterior não reescreve evento anterior | `test_results.py::test_a_later_rate_does_not_rewrite_an_earlier_event` |
| Investimento é rateado por dia | `test_results.py::test_investment_is_prorated_by_day` |
| Investimento zero declara lacuna em vez de ROI infinito | `test_results.py::test_without_investment_the_roi_is_a_gap_not_a_number` |
| Sem premissa, o volume conta e o dinheiro não | `test_results.py::test_without_any_assumption_money_is_zero_and_the_gap_is_declared` |
| Vigências não se sobrepõem, garantido pelo banco | `test_results.py::test_overlapping_assumptions_are_impossible` |
| Períodos adjacentes não contam o mesmo evento duas vezes | `test_results.py::test_the_period_is_half_open` |
| Exceção tratada conta como acerto na precisão | `test_results.py::test_accuracy_counts_a_handled_exception_as_a_success` |
| Evento de outro projeto não entra na soma | `test_results.py::test_another_projects_events_never_enter_the_sum` |
| Premissa nova fecha a corrente, sem buraco | `test_admin_endpoints.py::test_a_new_assumption_closes_the_current_one` |
| Premissa não retroage sobre a vigente | `test_admin_endpoints.py::test_an_assumption_cannot_retroact_over_the_open_one` |
| As duas tabelas novas saem com policy de RLS | `test_rls_isolation.py::test_every_tenant_table_has_rls_enabled_and_a_policy` |
| Os números de demonstração não voltam | `tests/rendered-html.test.mjs` (guarda de literais + `overview.measured`) |
| O cliente vê o número e a premissa que o produziu | `tests/e2e/results.spec.ts` |
| Cliente não alcança a administração de resultados | `tests/e2e/results.spec.ts` |

### Telemetria

`agent_key.rejected` e `agent_key.rate_limited` em log estruturado, com o prefixo da chave e
nunca a chave. Em `audit_log`: `agent_event.ingested` (sem payload), `agent_key.created`,
`agent_key.rotated`, `agent_key.revoked` e `assumption.changed` — todos com prefixo ou id, nunca
segredo (`docs/data-classification.md`). `last_used_at` na linha da chave responde "esta chave
ainda é usada?" sem consultar log.

Retenção de `agent_event`: não definida ainda; a poda entra com a da `notification`, na Fase 5.

### Casos de avaliação de IA

Nenhum: nada aqui passa por modelo. A única ligação com IA é o chat poder ser perguntado sobre os
números da tela, e esse caminho já tem seus casos na FDD 002 — o que muda é que agora as respostas
sobre resultados têm um read model com premissa declarada para citar, em vez de três constantes.
