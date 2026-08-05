# Threat model

| Ameaça | Controle principal | Verificação |
| --- | --- | --- |
| Cliente acessa outro projeto | autorização + RLS | integração e E2E negativos |
| IDOR em arquivo/documento | IDs não autorizam; vínculo de projeto obrigatório | teste de download cruzado |
| Token de agente vazado | hash, escopo, rotação e rate limit | teste de revogação |
| Prompt injection em documento | contexto delimitado e sem ferramentas implícitas | conjunto adversarial de IA |
| Upload malicioso | allowlist, tamanho, antivírus e bucket privado (ADR 0017) | teste de tipo e EICAR barrado antes de indexar (`test_document_scan.py`, `documents.spec.ts`) |
| Abuso de chat | rate limit, quotas e auditoria | teste de carga |
| OAuth Drive excessivo | escopo readonly (recusado se o Google conceder outro), pasta autorizada conferida duas vezes, atalho não seguido | `test_drive_adapter.py::test_a_file_whose_parent_is_another_folder_is_never_downloaded`, `::test_a_shortcut_inside_the_folder_is_ignored_not_followed`, `tests/e2e/drive.spec.ts` |
| Refresh token do Drive vazado do banco | AES-256-GCM sob chave que vive só no ambiente, com AAD do tenant | `test_crypto.py::test_a_ciphertext_moved_to_another_project_does_not_open` |
