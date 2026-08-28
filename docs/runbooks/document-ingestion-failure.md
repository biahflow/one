# Runbook — ingestão de documentos

O documento entra por `POST /api/v1/admin/projects/{id}/documents` (tela `/admin/knowledge`),
vira objeto no storage e é indexado pela task `portal_api.ingest_document` no worker (ADR 0014).
Parada, o assistente não responde errado — ele volta a declarar lacuna sobre o que aquele
documento diria, e abre pendência para o time.

O estado de cada documento fica na própria linha e aparece na tela: `pending`, `indexed`, `failed`
ou `unsupported`. **Comece sempre por ali** — o motivo da falha está em `ingest_error`.

## Sintoma: o documento fica "Na fila" para sempre

`pending` significa que a task não rodou. Na ordem:

1. **O worker está no ar?**
   ```bash
   docker compose ps worker && docker compose logs --tail=50 worker
   ```
2. **O broker está no ar?** O enfileiramento engole um Redis morto de propósito — o upload já
   respondeu 201 e o arquivo já está no storage, então derrubar a requisição por causa da fila
   trocaria uma degradação por uma indisponibilidade. O preço é este: o documento espera.
3. **Reenfileire o que ficou para trás**, sem reenviar arquivo nenhum:
   ```bash
   docker compose exec api python -c "
   from portal_api.worker import reindex_project
   print(reindex_project('<organization_id>', '<project_id>'))"
   ```
   Ele varre os `pending` do projeto. Rodar duas vezes é inofensivo.

## Sintoma: "Falhou"

`ingest_error` diz qual dos três foi:

- **`Falha ao ler <chave>`** — o storage não devolveu o objeto. Confira
  `STORAGE_ENDPOINT_URL`/`STORAGE_BUCKET` no worker (elas precisam ser as **mesmas** da API: quem
  grava é uma, quem lê é a outra) e se o MinIO está de pé (`docker compose ps minio`).
- **`Storage sem credencial configurada`** — `STORAGE_ACCESS_KEY`/`STORAGE_SECRET_KEY` vazias. O
  upload responde 503 antes de gravar linha nenhuma, então isto só aparece se a configuração mudou
  depois do envio.
- **`Embeddings: …`** — o provedor não respondeu. Sem `VOYAGE_API_KEY` o embedder é o offline e
  não sai da máquina; com chave, veja `docs/runbooks/ai-provider-failure.md`. O documento fica
  `failed` e volta a ser pego por `reindex_project` depois — nada se perde.

Reprocessar depois de corrigir: reenfileire o documento pelo id.
```bash
docker compose exec api python -c "
from portal_api.worker import ingest_document
print(ingest_document('<document_id>'))"
```

## Sintoma: "Não suportado"

Dois casos distintos, e o `ingest_error` separa:

- **`Formato não suportado: …`** — o MIME está fora da allowlist (PDF, DOCX, TXT, Markdown, CSV).
  O upload já recusa com 415; este estado só aparece se o arquivo entrou antes de a lista mudar.
- **`Documento sem texto extraível (digitalizado?)`** — o PDF é imagem. O portal não faz OCR. O
  caminho é subir uma versão com camada de texto; marcar `indexed` com zero trechos deixaria o
  chat mudo sem explicar por quê.

## Sintoma: o documento está indexado, mas o chat não o cita

1. **A pergunta está longe do trecho.** A recuperação corta por distância
   (`RAG_MAX_DISTANCE` com provedor, `RAG_OFFLINE_MAX_DISTANCE` sem) justamente para não citar o
   "menos distante". Sem chave de embeddings, a recuperação é **lexical**: ela acha o que repete
   as palavras da pergunta, e paráfrase não basta.
2. **É outro projeto.** O índice é filtrado por organização e projeto no repositório e pela RLS
   abaixo dele. Um documento indexado no projeto errado é invisível — e é o desenho.
3. **O modelo de embedding mudou.** Trechos vetorizados por um modelo não são comparáveis com a
   pergunta vetorizada por outro. `document_chunk.embedding_model` diz qual produziu cada linha;
   reindexe o projeto depois de trocar.

## Sintoma: um documento reapareceu depois do sync

Não reaparece: quem some é o espelhado. O sync do Biahflow substitui os documentos com
`origin='biahflow'` e nunca toca nos de `origin='portal'`. Se um documento **enviado** sumiu, é
bug — verifique o filtro em `integrations/biahflow.py` antes de qualquer outra hipótese.

## Documento enviado por engano

Remover pela tela apaga linha, trechos (por CASCADE) e o objeto no storage. Se a remoção do objeto
falhar, a linha sai mesmo assim e fica um órfão no bucket — registrado como
`document.object_not_removed`, com a chave em `storage_key`:

```bash
docker compose logs api | grep '"event":"document.object_not_removed"'
```

*Corrigido em 06/08/2026 (ADR 0034): esta instrução mandava procurar a prosa
`Objeto … não removido do storage`, e era a única do repositório que só se cumpria por
substring — porque a linha era interpolada e produzia um `event` diferente a cada
ocorrência. Todo o resto destes runbooks manda filtrar por `event`, e agora esta também.*

Para conteúdo sensível, confirme no MinIO:
```bash
docker compose exec minio mc ls --recursive local/portal-documents/org/<organization_id>/
```
