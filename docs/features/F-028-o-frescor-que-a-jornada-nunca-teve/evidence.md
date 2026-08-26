# Evidência — F-028

**Estado:** baseline registrado; nenhuma implementação (aguarda Design Approval + ADR).

## Baseline (26/08/2026, `main`)

- Jornada já projetada (`build_dashboard`) e renderizada (`JourneyPanel`).
- **Sem frescor:** não há coluna `observed_at`/`synced_at`; `source` é hardcoded `"live"`; a ADR 0026
  removeu o carimbo inventado "Atualizado há 2 dias".
- **Sem defesa anti-regressão:** sync idempotente (re-busca snapshot inteiro), sem versão/observação
  comparável; único precedente de dedup por evento é `external_event_id` no `AgentEvent`.
- **Contrato não versionado** (ADR 0067 pediu); decisões são lista read-only, sem vínculo a fase.
- Padrão honesto de estado somente-consulta já existe: `readOnlyReason` (`archived_at`/
  `source_deleted_at`, ADR 0036/0037).

## A preencher na execução

- ADR aceita (contrato versionado + reconciliação) e capturas do DAP aprovado.
- `BUILD REPORT` por tarefa; teste de evento fora de ordem; guarda de filtro de campo interno.
- Prova de que stale/indisponível/encerrado são visivelmente distintos; isolamento intacto.
- Decisões humanas: gate de design, ADR, gate de plano, merge.
