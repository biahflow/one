# Plano de execução — F-027

**Estado:** `BLOCKED_ON_DESIGN_APPROVAL` **e** `BLOCKED_ON_ADR`. Dois gates precedem o planejamento:
o Design Approval do DAP r1 e a **ADR do contrato de retorno + nova tabela** (decisão arquitetural
consequente; a migração de policy/GRANT não passa em `test_migration_rules.py` sem uma ADR aceita
que a cite). Este arquivo só vira DAG válido do Planner depois dos dois.

## Decomposição preliminar (não-vinculante)

- **T01 — `external_ref` do entregável.** Migração aditiva dando `PhaseDeliverable.external_ref`
  durável; `sync_snapshot` passa a populá-lo. Pré-requisito de tudo (o aceite ancora nele).
- **T02 — Tabela `deliverable_acceptance`.** Migração aditiva (append-only, RLS org+project, GRANT só
  `INSERT`), citando a ADR da F-027. Casos em `test_rls_isolation.py`.
- **T03 — Módulo + rota.** `deliverable_acceptance.py` (o único escritor) + `POST /api/v1/me/
  deliverables/{external_ref}/acceptance` no molde de `add_pending_comment`; schemas + OpenAPI;
  `test_authorization.py` (404 nunca 403).
- **T04 — Notificação interna.** Novo `NotificationKind` (`ALTER TYPE ADD VALUE`), `AUDIENCE`
  `_INTERNAL_ONLY`, task sob `portal_system`, linha em `alerts.md`.
- **T05 — Emissor de retorno ao Pulse.** Conforme a ADR: POST outbound ou evento consumível. Evento
  imutável como fonte da verdade.
- **T06 — UI.** Superfície de aceite viva (DAP), estados, histórico imutável, distinção merge≠aceite.
- **T07 — Evidência de navegador.** Fluxo aprovar/pedir-ajuste, histórico com supersessão, cross-tenant
  negado; capturas presas à revisão aprovada.

Dependências: T01→T02→T03; T04/T05 dependem de T03; T06 depende do DAP; T07 do conjunto.
