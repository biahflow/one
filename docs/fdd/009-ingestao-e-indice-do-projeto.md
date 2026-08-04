# FDD 009 — Índice do projeto

Uma pessoa interna envia um documento; o portal extrai o texto, divide em trechos com a página de
origem e os indexa em `pgvector`. A partir daí o assistente cita aquele documento — e continua
declarando lacuna quando não há evidência.

## Estado

- **Storage real (Fase 4 / ADR 0014) — feito.** `portal_api/storage.py` fala S3: MinIO no
  compose, S3 em produção, mesma configuração. A chave do objeto carrega o tenant inteiro.
- **Extração e chunking (Fase 4 / ADR 0014) — feito.** PDF, DOCX, TXT, Markdown e CSV. O trecho
  nunca cruza a virada de página.
- **Embeddings e recuperação (Fase 4 / ADR 0014) — feito.** Adapter Voyage/offline,
  `document_chunk.embedding` com índice HNSW por distância de cosseno, filtro de tenant no
  repositório e policy de RLS abaixo dele.
- **Tela `/admin/conhecimento` — feita.** Envio, estado da ingestão e remoção.
- **Fora de escopo desta fatia:** conector do Google Drive (segue aberto na Fase 4), reindexação
  automática por troca de modelo de embedding, e retenção/exclusão por organização — Fase 5.

## Permissões

| Ação | Quem | Papel do Postgres |
|---|---|---|
| Enviar, listar e remover documento | `internal_admin` no projeto | `portal_admin` |
| Escrever o índice | worker (task, sem principal) | `portal_system` |
| Ler o índice | qualquer membro do projeto, pela recuperação do chat | `portal_app` (SELECT) |

Negação é 404, nunca 403 — como no resto da API. `portal_app` **não** tem escrita em
`document_chunk`: se o caminho de requisição pudesse gravar um trecho, poderia gravar a evidência
que quisesse ver citada.

## Estados da ingestão

| Estado | Significado | O que a tela mostra |
|---|---|---|
| `pending` | Na fila, ou o broker estava fora do ar | "Na fila" |
| `indexed` | Trechos e embeddings gravados | "Indexado" + contagem de trechos |
| `failed` | Storage inacessível, arquivo ilegível, provedor de embeddings fora | "Falhou" + motivo |
| `unsupported` | Formato fora da allowlist, ou sem texto extraível (PDF digitalizado) | "Não suportado" + motivo |

O motivo guardado é a mensagem do erro, **nunca** trecho do conteúdo
(`docs/data-classification.md`).

## Como o trecho vira citação

O texto é extraído página a página. O chunking recomeça em cada virada de página e, dentro dela,
corta em parágrafos com sobreposição — a frase que responde costuma estar na emenda de dois
trechos. Cada trecho guarda a localização exibida (`"página 3"`), vazia quando o formato não
pagina.

Na pergunta, o embedder vetoriza a questão, o repositório busca por distância de cosseno dentro do
tenant e devolve os `RAG_TOP_K` mais próximos que estejam **dentro do corte de distância**. Sem
corte, toda pergunta encontraria o trecho menos distante e o citaria; é o corte que permite à
recuperação dizer "não há evidência" e deixar o serviço abrir a pendência (ADR 0007).

O trecho entra na mesma lista de `Evidence` do read model estruturado, então a política de citação
não muda: afirmação factual cita evidência real, e sem evidência há lacuna e pendência.

### Critérios de aceite

| Critério | Coberto por |
|---|---|
| Um documento enviado vira trechos com embedding | `test_document_ingestion.py::test_a_document_becomes_chunks_with_an_embedding` |
| Reingestão do mesmo arquivo não recobra nem duplica | `test_document_ingestion.py::test_reingesting_the_same_file_is_a_no_op` |
| Arquivo trocado substitui o índice inteiro | `test_document_ingestion.py::test_a_changed_file_replaces_the_whole_index` |
| O trecho nunca cruza a fronteira da página | `test_document_ingestion.py::test_a_chunk_never_spans_two_pages` |
| Página longa é dividida com sobreposição e ordem estável | `test_document_ingestion.py::test_a_long_page_is_split_with_overlap_and_stays_ordered` |
| PDF mantém uma página por página | `test_document_ingestion.py::test_a_pdf_keeps_one_page_per_page` |
| Formato desconhecido vira estado, não exceção | `test_document_ingestion.py::test_an_unsupported_format_becomes_a_state_the_screen_can_explain` |
| Arquivo sem texto extraível declara o motivo | `test_document_ingestion.py::test_a_file_without_extractable_text_says_so_instead_of_indexing_nothing` |
| Storage inacessível marca o documento, não perde a task | `test_document_ingestion.py::test_a_missing_object_marks_the_document_failed` |
| O que o broker perdeu é recuperável | `test_document_ingestion.py::test_reindex_project_picks_up_what_the_broker_lost` |
| Vetor tem a dimensão que a coluna declara | `test_embeddings.py::test_the_vector_has_the_dimension_the_column_declares` |
| O embedder offline é determinístico e normalizado | `test_embeddings.py::test_the_same_text_always_produces_the_same_vector`, `::test_the_vector_is_normalized_so_cosine_distance_is_comparable` |
| Trecho relevante entra no corte, irrelevante não | `test_embeddings.py::test_the_relevant_excerpt_lands_inside_the_cut_and_the_unrelated_one_does_not` |
| O corte pertence ao embedder | `test_embeddings.py::test_the_cut_belongs_to_the_embedder_and_not_to_the_retriever` |
| Nenhuma rota de conhecimento é alcançável por cliente | `test_admin_endpoints.py::test_no_client_member_reaches_the_knowledge_administration` |
| Administrador não envia para outro tenant | `test_admin_endpoints.py::test_an_administrator_cannot_upload_into_another_tenant` |
| Upload é guardado pendente e enfileirado | `test_admin_endpoints.py::test_an_upload_is_stored_pending_and_queued_for_indexing` |
| Formato ilegível não chega ao storage | `test_admin_endpoints.py::test_a_format_the_portal_cannot_read_never_reaches_the_storage` |
| Arquivo acima do teto é recusado antes de qualquer escrita | `test_admin_endpoints.py::test_a_file_over_the_cap_is_refused_before_anything_is_written` |
| O tipo é conferido no servidor | `test_admin_endpoints.py::test_the_markdown_the_browser_calls_octet_stream_is_still_accepted` |
| Remover apaga linha, índice e objeto | `test_admin_endpoints.py::test_deleting_removes_the_row_the_index_and_the_object` |
| Documento espelhado do Biahflow não é removível aqui | `test_admin_endpoints.py::test_a_document_mirrored_from_biahflow_is_not_deletable_here` |
| O upload é auditado sem o conteúdo | `test_admin_endpoints.py::test_the_upload_is_audited_without_the_content` |
| O documento enviado sobrevive ao sync | `test_biahflow_integration.py::test_sync_replaces_biahflow_documents_but_keeps_the_uploaded_ones` |
| Trecho de outro tenant é invisível pela RLS | `test_rls_isolation.py::test_another_tenants_document_chunk_is_invisible` |
| O caminho de requisição não escreve o índice | `test_rls_isolation.py::test_the_app_role_cannot_write_the_index`, `::test_the_app_role_cannot_rewrite_an_indexed_excerpt` |
| A tabela nova sai com policy | `test_rls_isolation.py::test_every_tenant_table_has_rls_enabled_and_a_policy` |
| O documento enviado vira citação no chat do cliente | `tests/e2e/documents.spec.ts` |
| Cliente não alcança a administração de conhecimento | `tests/e2e/documents.spec.ts` |

### Telemetria

Em `audit_log`: `document.uploaded` e `document.deleted`, com `mime_type` e tamanho — nunca nome
completo nem conteúdo. O estado da ingestão vive na própria linha do documento, o que responde
"por que a IA não sabe disso?" sem consultar log. Falha de extração e de embeddings vai para o log
estruturado do worker, com o id do documento.

Retenção de `document`/`document_chunk`: não definida ainda; entra com a política por organização
da Fase 5.

### Casos de avaliação de IA

Os casos da FDD 002 continuam valendo e ganharam três (`docs/ai/eval-dataset.md`):

- resposta cita o trecho **com a página de onde ele saiu**
  (`test_chat_ai.py::test_eval_a_document_excerpt_is_cited_with_the_page_it_came_from`);
- documento de outro projeto nunca é recuperado, e a pergunta vira lacuna
  (`::test_eval_another_projects_document_is_never_retrieved`);
- prompt injection dentro do documento é tratado como dado
  (`::test_eval_prompt_injection_inside_a_document_is_treated_as_data`);
- pergunta que nenhum documento responde continua sendo lacuna
  (`::test_eval_a_question_no_document_answers_stays_a_gap`).
