# FDD 010 — Conector Google Drive

Uma pessoa interna conecta **uma pasta** do Google Drive a um projeto, com acesso somente
leitura. A partir daí o conteúdo daquela pasta entra no mesmo índice do upload, com a mesma
citação, e uma alteração no Drive chega ao índice sem ninguém reenviar nada.

## Estado

- **Conexão OAuth por projeto (Fase 4 / ADR 0016) — feito.** Escopo `drive.readonly`, refresh
  token cifrado com AES-256-GCM amarrado ao tenant, `state` com prazo e uso único, PKCE S256.
- **Travessia da pasta — feita.** Em largura, com teto de profundidade e de arquivos, conjunto
  de visitados e conferência de `parents` antes de qualquer download.
- **Reconciliação idempotente — feita.** Dois portões (`modifiedTime`, depois SHA-256) e remoção
  **só** sobre listagem completa.
- **Formatos nativos — feito.** Docs→DOCX, Slides→PDF, Sheets→CSV pela API de export; daí em
  diante é o `ingestion/extract.py` de sempre.
- **Agendamento — feito.** `celery beat` a cada `DRIVE_SYNC_INTERVAL_SECONDS`, mais o botão
  "Sincronizar agora" na tela.
- **Fora de escopo:** push notifications do Drive, unidades compartilhadas (*shared drives*),
  reindexação por troca de modelo de embedding e retenção por organização — Fase 5.

## Permissões

| Ação | Quem | Papel do Postgres |
|---|---|---|
| Conectar, escolher pasta, sincronizar, desconectar | `internal_admin` no projeto | `portal_admin` |
| Resolver o `state` do OAuth | ninguém (o fluxo) | `portal_system` |
| Ler a pasta e escrever o índice | worker (task, sem principal) | `portal_system` |
| Ler o índice | qualquer membro do projeto, pela recuperação do chat | `portal_app` (SELECT) |

Negação é 404, nunca 403. `portal_app` **não tem policy** em `project_drive_connection`: ele
herda o `SELECT` do `ALTER DEFAULT PRIVILEGES`, mas nenhuma policy se aplica a ele, então a
leitura volta zero linhas — a diferença entre "você não tem permissão" e "a regra não é sobre
você", igual à chave de agente. O refresh token nunca sai da API: não está em nenhuma resposta
nem no `audit_log`.

## Estados da conexão

| Estado | Significado | O que a tela mostra |
|---|---|---|
| não conectada | Nunca houve consentimento, ou foi revogado | "Não conectado" + botão de conectar |
| conectada, sem pasta | Consentimento dado, pasta não escolhida | "Pasta não escolhida" + lista de pastas |
| `idle` | Pronta; o beat sincroniza no próximo tick | Última sincronização e a contagem |
| `running` | Sincronizando agora | Botão de sincronizar desabilitado |
| `failed` | Falha de rede ou do provedor | Motivo; a pasta continua ligada |
| pausada (`enabled = false`) | Consentimento revogado no Google | Motivo + reconectar |

Uma falha **nunca** apaga o índice existente (`docs/runbooks/drive-sync-failure.md`).

## Como o arquivo do Drive vira citação

1. A travessia parte da pasta autorizada. Subpasta entra até `DRIVE_MAX_DEPTH`; **atalho é
   ignorado, nunca seguido**; arquivo cujo `parents` não é nenhuma pasta alcançada é recusado.
2. Nativo do Google é exportado (Docs→DOCX, Slides→PDF, Sheets→CSV); binário é baixado.
   Formato fora da allowlist vira linha com `ingest_state = unsupported` e o motivo na tela.
3. Os bytes vão para o MinIO/S3 com a mesma chave de objeto do upload, e a indexação é a mesma
   task da ADR 0014 — o conector não acrescenta nenhum extrator nem toca no chunking.
4. A citação sai igual à do upload, porque o `Evidence` é o mesmo.

> **A planilha exporta só a primeira aba.** É limitação do `files.export` do Google, não do
> portal. Uma planilha de cinco abas indexa uma; quem precisa das outras exporta à mão e envia
> pelo upload.

### Critérios de aceite

| Critério | Coberto por |
|---|---|
| Só a pasta autorizada é listada | `test_drive_adapter.py::test_only_the_authorized_folder_is_listed` |
| Arquivo com outro pai nunca é baixado | `::test_a_file_whose_parent_is_another_folder_is_never_downloaded` |
| Atalho é ignorado, não seguido | `::test_a_shortcut_inside_the_folder_is_ignored_not_followed` |
| Subpasta entra até a profundidade configurada | `::test_the_walk_descends_into_subfolders_up_to_the_configured_depth` |
| Ciclo de pastas não trava a travessia | `::test_a_folder_cycle_does_not_hang_the_walk` |
| Teto de arquivos trunca em vez de rodar sem fim | `::test_the_file_cap_truncates_instead_of_running_forever` |
| Consentimento pede acesso offline e força o prompt | `::test_the_consent_url_asks_for_offline_access_and_forces_the_prompt` |
| Escopo mais amplo que o pedido não é aceito | `::test_a_broader_granted_scope_is_not_accepted` |
| Consentimento revogado é distinto de falha genérica | `::test_a_revoked_consent_is_told_apart_from_a_generic_failure` |
| Listagem que falha no meio levanta, não devolve lista curta | `::test_a_listing_that_fails_midway_raises_instead_of_returning_a_short_list` |
| Nativo do Google é exportado; planilha vira CSV | `::test_a_google_doc_is_classified_for_export_and_a_spreadsheet_as_csv` |
| Nativo sem export vira motivo, não exceção | `::test_a_native_file_without_an_export_becomes_a_reason_and_not_an_exception` |
| Nativo não tem md5, então o portão é o `modifiedTime` | `::test_a_native_file_carries_no_md5_so_modified_time_is_the_gate` |
| A pasta conectada vira documentos enfileirados | `test_drive_sync.py::test_the_authorized_folder_becomes_queued_documents` |
| O documento do Drive vira trecho citável | `::test_the_indexed_document_from_the_drive_is_citable` |
| Segundo sync sobre o mesmo Drive não baixa nada | `::test_a_second_sync_over_the_same_drive_downloads_nothing` |
| Arquivo tocado com os mesmos bytes não é reindexado | `::test_a_touched_file_with_the_same_bytes_is_not_reindexed` |
| Arquivo alterado é baixado e reenfileirado | `::test_a_changed_file_is_downloaded_again_and_queued_for_reindexing` |
| Arquivo removido do Drive some do portal | `::test_a_file_removed_from_the_drive_leaves_no_row_chunk_or_object` |
| **Listagem que falha no meio nunca apaga** | `::test_a_listing_that_fails_midway_never_deletes` |
| **Listagem truncada nunca apaga** | `::test_a_truncated_listing_never_deletes` |
| **Consentimento revogado pausa e preserva o índice** | `::test_a_revoked_consent_pauses_the_folder_and_keeps_the_index` |
| Documento enviado pela administração sobrevive ao sync | `::test_an_uploaded_document_survives_the_drive_sync` |
| Formato não suportado vira estado que a tela explica | `::test_an_unsupported_drive_file_becomes_a_state_the_screen_can_explain` |
| Arquivo acima do teto é recusado antes do download | `::test_a_file_over_the_cap_is_refused_before_the_download` |
| Atalho nunca vira documento | `::test_a_shortcut_never_becomes_a_document` |
| Sync concorrente encontra a linha reivindicada | `::test_a_second_sync_finds_the_row_claimed_and_returns_busy` |
| Reivindicação velha é recuperada | `::test_a_stale_claim_is_reclaimed_after_the_timeout` |
| Conexão pausada não sincroniza | `::test_a_paused_connection_is_not_synced` |
| O tick do beat só alcança conexões ligadas | `::test_the_beat_tick_only_fans_out_enabled_connections` |
| Chave girada re-sela o token no sync seguinte | `::test_a_rotated_key_reseals_the_token_on_the_next_sync` |
| Sem chave de cifra o sync falha em vez de rodar | `::test_without_an_encryption_key_the_sync_fails_instead_of_running` |
| Segredo selado volta em claro | `test_crypto.py::test_a_sealed_secret_comes_back` |
| Ciphertext movido para outro projeto não abre | `::test_a_ciphertext_moved_to_another_project_does_not_open` |
| Sem chave, nada sela e nada abre | `::test_without_a_key_nothing_seals_and_nothing_opens` |
| A chave anterior ainda abre o que selou | `::test_the_previous_key_still_opens_what_it_sealed` |
| Cliente não alcança nenhuma rota do conector | `test_admin_endpoints.py::test_no_client_member_reaches_the_drive_connector` |
| Admin não conecta Drive em outro tenant | `::test_an_administrator_cannot_connect_a_drive_in_another_tenant` |
| Projeto sem Drive responde "desconectado", não 404 | `::test_a_project_without_a_drive_answers_disconnected_and_not_404` |
| A resposta nunca traz o token | `::test_connecting_stores_the_account_and_never_returns_the_token` |
| `state` reapresentado não acha nada | `::test_a_replayed_state_finds_nothing` |
| `state` expirado é recusado | `::test_an_expired_state_is_refused` |
| `state` de outra pessoa é recusado | `::test_a_state_minted_for_someone_else_is_refused` |
| Escopo mais amplo é recusado e nada é gravado | `::test_a_broader_granted_scope_is_refused_and_nothing_is_stored` |
| Consentimento sem refresh token é recusado | `::test_a_consent_without_a_refresh_token_is_refused` |
| Conectar sem chave de cifra responde 503 | `::test_connecting_without_an_encryption_key_answers_503` |
| A auditoria nunca carrega o token | `::test_the_audit_trail_never_carries_the_token` |
| Desconectar revoga e mantém o rastro | `::test_disconnecting_revokes_and_keeps_the_trail` |
| `portal_app` não lê a conexão | `test_rls_isolation.py::test_the_app_role_cannot_read_a_drive_connection` |
| `portal_app` não escreve a conexão | `::test_the_app_role_cannot_write_a_drive_connection` |
| Conexão de outro tenant é invisível ao admin | `::test_another_tenants_drive_connection_is_invisible_to_the_admin` |
| A tabela nova sai com policy | `::test_every_tenant_table_has_rls_enabled_and_a_policy` |
| A pasta conectada vira citação no chat do cliente | `tests/e2e/drive.spec.ts` |
| **Arquivo fora da pasta nunca entra no índice** (threat model) | `tests/e2e/drive.spec.ts` |
| Cliente não alcança o conector | `tests/e2e/drive.spec.ts` |

### Telemetria

Em `audit_log`: `drive.authorize_started`, `drive.connected`, `drive.folder_changed`,
`drive.sync_requested` e `drive.disconnected`. Carregam a conta e o id da pasta — **nunca o
token, nunca nome de arquivo completo, nunca conteúdo** (`docs/data-classification.md`).

O resultado de cada sincronização vive na própria linha da conexão
(`last_sync_at`, `last_sync_error`, `last_sync_stats` com `{added, updated, removed, skipped,
unsupported, rejected, truncated}`), o que responde "por que a IA não sabe disso?" sem
consultar log. `rejected > 0` é o contador da fronteira: atalhos e arquivos de fora da pasta.

### Casos de avaliação de IA

Os casos da FDD 002 e da FDD 009 continuam valendo. O conector não muda prompt, recuperação nem
modelo — ele só muda **o que entra no índice** —, então não há caso de eval novo. O que o
protege é a fronteira, e ela é coberta pelos testes de sync acima e pelo e2e.
