# Classificação de dados

- **Público:** material comercial aprovado.
- **Interno:** cronograma, status e documentação de operação.
- **Confidencial do cliente:** transcrições, documentos, eventos e indicadores por projeto.
- **Segredo:** chaves, tokens, credenciais e material criptográfico.
- **Comportamento de pessoa identificada:** *quando* uma pessoa nomeada alcançou cada degrau de
  valor no portal (ADR 0039). Classe própria, e não "confidencial do cliente", porque o risco é de
  outra natureza: as demais descrevem o **projeto**, e esta descreve a **pessoa**. É por isso que
  ela não é exposta a nenhuma rota de cliente, que o papel de requisição não tem policy sobre ela,
  e que o log carrega só o tenant e o nome do degrau — nunca o `user_id`, que fica na linha, onde a
  retenção e o apagamento o alcançam. *Desde a ADR 0040 ela sai do banco por duas portas — a rota
  `GET /api/v1/admin/organizations/{id}/onboarding`, restrita a `internal_admin` e negando com 404,
  e a linha de notificação cuja audiência é `_INTERNAL_ONLY` —, e **nenhuma das duas carrega
  pessoa**: o que trafega é o degrau, uma contagem de dias e de que lado está a espera. Quem
  alcançou o degrau continua sendo pergunta que só a linha responde.*

Desde a ADR 0016 há um segredo **em repouso no banco**: o refresh token do Google Drive, um por projeto. Ele é cifrado com AES-256-GCM sob uma chave que vive só no ambiente — nunca no banco que ela protege — e amarrado à organização e ao projeto pelo dado associado, de modo que um ciphertext movido de linha não abre. É o único segredo do portal que precisa voltar em claro; todos os outros são verificados por hash e nunca recuperados.

Dados confidenciais e segredos não entram em logs. Conteúdo enviado ao provedor de IA segue a política contratada de não treinamento/retenção e deve ser removível por organização. *(A remoção existe desde a ADR 0017:
prazo por organização com poda diária, e apagamento por pedido gravado que o worker cumpre —
inclusive os objetos do storage, pelo prefixo `org/<id>/`. O documento nunca sai por idade: é a
evidência que sustenta uma citação já dada.)* *(E desde a ADR 0039 o funil tem prazo próprio,
mais longo que os outros — a régua só significa algo comparada com a de coortes anteriores — e é a
segunda exclusão escrita à mão no apagamento por decisão: escopado por organização, ele não vem no
CASCADE do projeto.)*
