# Threat model

| Ameaça | Controle principal | Verificação |
| --- | --- | --- |
| Cliente acessa outro projeto | autorização + RLS | integração e E2E negativos |
| IDOR em arquivo/documento | IDs não autorizam; vínculo de projeto obrigatório | teste de download cruzado |
| Token de agente vazado | hash, escopo, rotação e rate limit | teste de revogação |
| Prompt injection em documento | contexto delimitado e sem ferramentas implícitas; citação sem evidência real vira lacuna, para **qualquer** respondedor (ADR 0021) | conjunto adversarial contra o respondedor real, com modelo hostil: `test_chat_ai.py`, seção adversarial. O limite é declarado — o portal não impede um modelo remoto de parafrasear a injeção dentro da resposta; impede que afirmação sem citação chegue como fato |
| Upload malicioso | allowlist, tamanho, antivírus e bucket privado (ADR 0017) | teste de tipo e EICAR barrado antes de indexar (`test_document_scan.py`, `documents.spec.ts`) |
| Abuso de chat | rate limit por pessoa (janela de 1 min na própria linha, ADR 0021) e auditoria. **Quotas não existem** — dependem do ambiente de homologação, junto da carga; esta linha prometia as três desde a Fase 1 e entregava zero | `test_chat_rate_limit.py` — inclusive o que dá sentido ao controle: a requisição recusada não grava pendência nem mensagem, porque a ameaça é a enxurrada na caixa do time interno, não a conta de token |
| Segredo ou contexto alheio enviado ao modelo | evidência escopada a montante; nada de settings entra no prompt | contra-asserção sobre o **pedido** enviado, e não sobre a resposta: `test_chat_ai.py::test_eval_no_secret_ever_reaches_the_model` e `::test_eval_another_projects_text_never_reaches_the_model` |
| OAuth Drive excessivo | escopo readonly (recusado se o Google conceder outro), pasta autorizada conferida duas vezes, atalho não seguido | `test_drive_adapter.py::test_a_file_whose_parent_is_another_folder_is_never_downloaded`, `::test_a_shortcut_inside_the_folder_is_ignored_not_followed`, `tests/e2e/drive.spec.ts` |
| Refresh token do Drive vazado do banco | AES-256-GCM sob chave que vive só no ambiente, com AAD do tenant | `test_crypto.py::test_a_ciphertext_moved_to_another_project_does_not_open` |
