# ADR 0008 — Abas do projeto a partir do snapshot e origem das pendências

**Status:** Aceito

## Contexto

As abas Cronograma, Documentos, Reuniões e Pendências do portal ainda renderizavam arrays
fixos no componente: o cliente via os mesmos documentos e as mesmas pendências
independentemente do projeto. Enquanto isso, o Biahflow já passara a emitir os blocos
`documents` (com `type`, `author`, `link`), `meetings`, `pendencias`, `resultados` e o campo
`party` nos marcos (ADR 0005 do `portal_biahflow`), sem consumidor do lado do portal.

Há um conflito específico em pendências: o chat cria uma `PendingItem` quando falta evidência
(ADR 0007), mas o sync do read model substitui ("replace") o que vem do Biahflow. Um sync
apagaria a pendência aberta pela IA.

## Decisão

O read model passa a espelhar `documents`, `meetings` e `pendencias` do snapshot, e
`build_dashboard` os projeta em `GET /api/v1/me/dashboard` junto de `results` — KPIs de
andamento **recalculados a partir dos marcos já espelhados**, não denormalizados em colunas,
para não divergirem do read model.

`PendingItem` ganha `origin` (`biahflow` | `portal`) e `external_ref` (migração
`0006_portal_sync_fields`). O sync substitui **apenas** `origin=biahflow`; as de origem
`portal` — hoje só as que a IA abre — sobrevivem a qualquer número de webhooks. O `party` do
Biahflow vira `owner_label` no sync (`provider` → "Portal Labs", `client` → nome da
organização).

O portal continua **read-only** (ADR 0006): nada nessas abas é editável pelo cliente, e o item
"CRUD interno" da Fase 2 do roadmap fica superado — a digitação permanece só no Biahflow.

## Consequências

Todas as abas passam a refletir o projeto real, e a pendência criada pela IA fica visível ao
cliente — o loop do chat fecha. Os novos `object_type` do webhook (`meeting`, `pendencia`) não
exigem tratamento próprio: o handler só lê `project_id` e refaz o snapshot inteiro.

O texto das transcrições **não** atravessa: o snapshot informa apenas `has_transcript`. A
recuperação de evidência do chat (`ai/retrieval.py`) segue sobre projeto, marcos e pendências
— documentos e reuniões viram evidência citável apenas com a ingestão de texto da Fase 4
(ADR 0004), o que exigirá novas avaliações de IA.

Três cards da aba Resultados (transações automatizadas, precisão do fluxo, exceções tratadas)
permanecem com valores de demonstração, marcados no código, até a Fase 3 dos eventos dos
agentes lhes dar fonte.
