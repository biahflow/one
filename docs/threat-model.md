# Threat model

| Ameaça | Controle principal | Verificação |
| --- | --- | --- |
| Cliente acessa outro projeto | autorização + RLS | integração e E2E negativos |
| IDOR em arquivo/documento | IDs não autorizam; vínculo de projeto obrigatório | teste de download cruzado |
| Token de agente vazado | hash, escopo, rotação e rate limit | teste de revogação |
| Prompt injection em documento | contexto delimitado e sem ferramentas implícitas | conjunto adversarial de IA |
| Upload malicioso | allowlist, tamanho, antivírus e bucket privado | teste de tipo e malware simulado |
| Abuso de chat | rate limit, quotas e auditoria | teste de carga |
| OAuth Drive excessivo | escopo readonly e folder allowlist | teste de sync fora da pasta |
