# Evidência — F-027

**Estado:** baseline registrado; nenhuma implementação (aguarda Design Approval + ADR).

## Baseline (26/08/2026, `main`)

- Superfície de aceite existe **desenhada e reservada** na F-025 §10 (não renderizada).
- `PhaseDeliverable` **não tem** identidade estável (`external_ref`) e é apagado/recriado a cada sync
  — pré-requisito medido para o aceite (dossiê #61).
- Integração Biahflow é **unidirecional** (só `httpx.get` do snapshot; nenhum `post` de volta) — o
  `client.accepted` de retorno é lacuna verde.
- Precedentes de tabela cliente-escrita imutável: `pending_item_comment` (ADR 0032, migração 0021),
  `conversation_message.feedback` (ADR 0015, migração 0012).

## A preencher na execução

- ADR aceita (contrato de retorno + RLS/GRANT) e capturas do DAP aprovado.
- `BUILD REPORT` por tarefa; resultados de `test_rls_isolation`/`test_authorization`/`test_openapi_contract`.
- Prova de imutabilidade (segunda decisão acrescenta) e de que o aviso interno não chega ao cliente.
- Decisões humanas: gate de design, ADR, gate de plano, merge.
