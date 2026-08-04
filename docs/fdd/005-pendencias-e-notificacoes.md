# FDD 005 — Pendências

Cliente pode abrir e acompanhar pendências. Falta de contexto no chat cria uma pendência com pergunta, fontes consultadas e responsável. Mudanças geram central de notificações e e-mail.

## Estado

- **Pendência por lacuna de contexto (Fase 3 / ADR 0007) — feito:** o chat cria uma
  `PendingItem` quando não há evidência suficiente, em vez de inventar resposta.
- **Aba Pendências (Fase 2 / ADR 0008) — feito:** a aba mostra abertas e resolvidas vindas do
  read model, com responsável (`party` do Biahflow → `owner_label`) e idade. Pendências têm
  **origem**: `biahflow` (espelhadas, substituídas a cada sync) e `portal` (abertas pela IA,
  preservadas em qualquer sync) — coluna `origin` na migração `0006_portal_sync_fields`. A
  origem `portal` é marcada na UI como "aberta pela IA". O contador do menu lateral usa a
  contagem real de pendências abertas.

  Critério de aceite coberto por teste: uma pendência criada pelo chat continua visível depois
  de um novo webhook do Biahflow (`test_sync_replaces_biahflow_pendings_but_keeps_portal_ones`).

- **Pendente:** central de notificações e e-mail (Fase 2); resolução de pendência pelo cliente
  segue fora de escopo — o portal é read-only e a pendência é resolvida no Biahflow (ADR 0006).
