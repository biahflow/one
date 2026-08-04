# ADR 0006 — Biahflow como fonte da verdade e sincronização por webhook

**Status:** Aceito

## Contexto

O status dos projetos (Project, Milestone/Task, Document) já é mantido pela ferramenta
interna **Portal Biahflow** (Django/DRF), onde o time de Vendas/Entrega conduz a
oportunidade até a execução. O portal do cliente precisa exibir esse status, mas não deve
ter um segundo lugar de digitação — dois lugares dividiriam a fonte da verdade e
divergiriam.

## Decisão

O portal do cliente permanece um **serviço separado**, com backend próprio (FastAPI) para
autenticação do cliente, isolamento por organização/projeto, read model e IA/RAG. O
**Biahflow é a fonte da verdade** do status. A sincronização é por **webhook (push,
assinado com HMAC)** do Biahflow para o portal, complementada por um **backfill inicial e
reconciliação periódica** (pull com token de leitura) como rede de segurança para eventos
perdidos. O portal chama o Biahflow **servidor-a-servidor** (evita CORS; o Biahflow é
session+CSRF, mesma origem).

## Consequências

O portal nunca origina status: ele espelha o Biahflow no seu read model (reusando os
modelos de `apps/api/src/portal_api/models/`), guardando apenas o subconjunto que o cliente
pode ver. Clientes externos ficam isolados do CRM interno. O contrato `/api/v1/` do Biahflow
é preservado; as mudanças lá (emissão de webhook, token de leitura) são aditivas. Auth do
cliente e RAG são entregas seguintes (ver `docs/adr/0002`, `0003`, `0004`). Ver também
`portal_biahflow/docs/adr/0003`.
