# Classificação de dados

- **Público:** material comercial aprovado.
- **Interno:** cronograma, status e documentação de operação.
- **Confidencial do cliente:** transcrições, documentos, eventos e indicadores por projeto.
- **Segredo:** chaves, tokens, credenciais e material criptográfico.

Desde a ADR 0016 há um segredo **em repouso no banco**: o refresh token do Google Drive, um por projeto. Ele é cifrado com AES-256-GCM sob uma chave que vive só no ambiente — nunca no banco que ela protege — e amarrado à organização e ao projeto pelo dado associado, de modo que um ciphertext movido de linha não abre. É o único segredo do portal que precisa voltar em claro; todos os outros são verificados por hash e nunca recuperados.

Dados confidenciais e segredos não entram em logs. Conteúdo enviado ao provedor de IA segue a política contratada de não treinamento/retenção e deve ser removível por organização. *(A remoção existe desde a ADR 0017:
prazo por organização com poda diária, e apagamento por pedido gravado que o worker cumpre —
inclusive os objetos do storage, pelo prefixo `org/<id>/`. O documento nunca sai por idade: é a
evidência que sustenta uma citação já dada.)*
