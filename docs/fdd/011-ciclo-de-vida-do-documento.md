# FDD 011 — Ciclo de vida do documento: varredura, download e retenção

**Fase:** 5 (primeira fatia) · **ADR:** 0017 · **Status:** implementado

## Estado

Um arquivo passa a ter começo, meio e fim declarados:

1. **Chega** pela tela de administração ou pelo sync do Drive, e o objeto vai para o storage.
2. **É varrido** antes de qualquer parser abrir seus bytes. Só o veredito decide se ele segue.
3. **Vira índice** e, a partir daí, citação — e a citação agora **abre o documento**.
4. **Sai** por decisão de alguém (a tela, ou um pedido de apagamento), nunca por idade.

O que fica de fora desta fatia, e é funcionalidade e não dívida: revarredura periódica por
assinatura nova, e a tela do cliente que explica o prazo de retenção dos dados dele.

## Permissões

| Ação | Papel | Rota |
|---|---|---|
| Enviar documento | `internal_admin` | `POST /api/v1/admin/projects/{id}/documents` |
| Ver estado da varredura | `internal_admin` | `GET /api/v1/admin/projects/{id}/documents` |
| Abrir documento citado | qualquer membro do projeto | `GET /api/v1/me/documents/{id}/download` |
| Ler/definir prazo | `internal_admin` da organização | `.../admin/organizations/{id}/retention` |
| Pedir apagamento | `internal_admin` da organização | `POST .../admin/organizations/{id}/erasure` |

Negação é 404 em todas, como no resto da API. O papel de banco é `portal_admin` para as rotas de
administração e `portal_app` para o download; a poda e o expurgo rodam sob `portal_system`, no
worker — nenhuma rota HTTP apaga dado.

## Estados da varredura

| `scan_state` | Significado | Indexa? |
|---|---|---|
| `pending` | O arquivo chegou e ninguém varreu ainda | não |
| `clean` | Um scanner capaz olhou e não achou nada | sim |
| `skipped` | **Ninguém** que pudesse afirmar isso olhou | sim |
| `infected` | Assinatura encontrada; objeto destruído | nunca |
| `error` | Havia scanner e ele não respondeu | não |

`skipped` não é `clean`, e a diferença é o centro do desenho (ADR 0017 §2): sem `CLAMAV_HOST` a
stack local continua indexando, mas o banco e a tela nunca afirmam que o arquivo foi verificado.

`ingest_state` ganhou `rejected`, que é onde o documento infectado para — em vez de ficar
`pending` para sempre.

## Como o arquivo vira citação clicável

```
upload / sync do Drive
  └→ queue_document_scan        ← a porta única
       └→ scan_document          (portal_system)
            ├ infected → rejected + objeto apagado do bucket
            └ clean|skipped → queue_document_ingestion
                 └→ ingest_document  (recusa o que não passou — 2ª barreira)
                      └→ document_chunk + embedding
                           └→ citação com document_id
                                └→ GET /me/documents/{id}/download → URL assinada, TTL curto
```

## Retenção

Padrões em `config.py`, sobrescritos por organização em `organization_retention_policy`. Coluna
nula = usa o padrão, **não** "guarda para sempre".

| Família | Padrão | Critério de idade |
|---|---|---|
| `notification` | 180 dias | `created_at` |
| `agent_event` | 730 dias | `occurred_at` (o dia do fato, que é o que o ROI usa) |
| `conversation` | 365 dias | `last_message_at` — **não** `updated_at`: um polegar não é uma conversa (ADR 0015) |
| `document` | — | **nunca por idade**: é a evidência da citação |

O `beat` acorda uma vez por dia. A poda é por lote (`retention_batch_size`) e por organização,
uma transação cada: um erro numa não desfaz a poda das outras.

## Expurgo por organização

`POST .../erasure` grava a intenção e responde **202**. Exige motivo e o `slug` da organização
digitado — a confirmação existe porque é a única ação do portal que nenhuma tela desfaz.

O worker executa: storage primeiro (pelo prefixo `org/<id>/`, que existe na chave desde a
ADR 0014 exatamente para isto), banco depois. Sai o conteúdo dos projetos e os vínculos; ficam a
linha `organization` (âncora do tenant, e o que segura o registro do expurgo) e as linhas `user`
(a identidade é do realm, e a pessoa pode pertencer a outra organização).

O pedido guarda a contagem do que removeu, por tabela. Nunca amostra do que removeu.

### Critérios de aceite

- [x] Um arquivo com a assinatura EICAR é barrado, some do bucket e **não** vira trecho.
- [x] `ingest_document` recusa um documento não varrido mesmo quando chamada diretamente.
- [x] O arquivo vindo do Drive passa pela mesma varredura, sem código próprio.
- [x] Um documento limpo é indexado, e a citação no chat abre o arquivo por URL assinada.
- [x] Documento de outro projeto, não varrido ou infectado: 404 no download, sem distinção.
- [x] A poda remove o que venceu, preserva o que não venceu e nunca cruza organização.
- [x] A poda não toca em documento.
- [x] Um feedback numa conversa antiga não a preserva da poda.
- [x] O expurgo remove conteúdo e vínculos, preserva a organização, o usuário e o registro.
- [x] `portal_app` lê zero linhas das duas tabelas novas e não escreve em nenhuma.
- [x] `portal_admin` não reescreve o registro de um pedido de expurgo.

### Testes

- `apps/api/tests/test_document_scan.py` — o adapter (incluindo "sem scanner ≠ limpo" e "clamd
  morto ≠ limpo") e a task contra o Postgres.
- `apps/api/tests/test_retention.py` — janelas, fronteira entre organizações, documento
  preservado, expurgo e o vínculo de escopo organizacional.
- `apps/api/tests/test_authorization.py` — os três 404 do download e as negações das rotas de
  retenção.
- `apps/api/tests/test_rls_isolation.py` — policies das duas tabelas novas.
- `tests/e2e/documents.spec.ts` — no navegador: o EICAR é recusado na tela, o arquivo limpo é
  indexado e o cliente abre a fonte da citação.

### Telemetria

`scan_state` e `scan_error` vivem na própria linha do documento, e não só no log — é o que faz
"por que este arquivo não responde no chat?" ser respondível pela tela, a mesma escolha do
`last_sync_error` da ADR 0016. Contadores: documentos por `scan_state`, rejeições por período,
linhas podadas por tabela e por organização, pedidos de expurgo por estado.

`infected > 0` é o controle funcionando, não uma falha do sistema — leia como o `rejected` do
conector do Drive.

### Casos de avaliação de IA

Nenhum novo: a fatia não muda prompt, retriever nem modelo. O que ela muda é *o que entra* no
índice, e o eval que já existe (`docs/ai/eval-dataset.md`) continua valendo — um documento
barrado simplesmente nunca vira trecho recuperável.
