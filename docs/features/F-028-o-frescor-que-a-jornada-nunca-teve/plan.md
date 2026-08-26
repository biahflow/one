# Plano de execução — F-028

**Estado:** `BLOCKED_ON_DESIGN_APPROVAL` **e** `BLOCKED_ON_ADR`. O Design Approval do DAP r1 e a
**ADR do contrato de projeção versionado** (mudança de integração consequente) precedem o
planejamento. Este arquivo vira DAG válido do Planner depois dos dois.

## Decomposição preliminar (não-vinculante)

- **T01 — Contrato de projeção versionado.** Evoluir o snapshot para carregar `observed_at` e versão
  monotônica (ADR 0067). Guarda de filtro que reprova campo internal-only.
- **T02 — Coluna de frescor/versão no `Project`.** Migração aditiva; `sync_snapshot` grava;
  `build_dashboard` projeta.
- **T03 — Reconciliação anti-regressão.** `sync_snapshot` recusa aplicar snapshot com versão/observação
  anterior (generaliza `mark_project_deleted`). Teste de evento fora de ordem/duplicado.
- **T04 — Decisões/gates na timeline.** Ancorar `Decision` client-safe à fase (marcação do Pulse ou
  heurística por data), projetar em `build_dashboard`.
- **T05 — UI.** Carimbo de frescor, estado stale, timeline com decisão/gate; reusar `readOnlyReason`.
- **T06 — Evidência de navegador.** Frescor, stale, indisponível, encerrado; filtro de campo interno
  provado; isolamento intacto.

Dependências: T01→T02→T03; T04 depende de T01; T05 depende do DAP + T02/T04; T06 do conjunto.
