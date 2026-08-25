# ADR 0067 — One como projeção client-facing, não SoR de Delivery

**Status:** aceito
**Data:** 24/08/2026
**Fase:** 7

## Contexto

O produto passa a ser chamado **One**. Ele já reúne andamento, entregas, resultados, documentos, decisões e pendências do cliente. O novo BiahflowOS define ClickUp como fonte da verdade de Delivery e GitHub como fonte da verdade da execução de engenharia.

## Decisão

One continuará com seu próprio banco operacional para segurança, performance, RLS, conversas, documentos, notificações e experiência do cliente, mas o estado de Delivery exibido no produto será tratado como **projeção client-facing**.

One não será owner canônico de backlog, prioridade, status técnico de engenharia ou workflow interno.

A projeção deve expor somente conceitos apropriados ao cliente, como:

- projeto e fase atual;
- progresso;
- milestones e entregas;
- pendências e decisões;
- aprovações/homologação;
- documentos;
- resultados, ROI e próximos passos.

Não devem atravessar a fronteira, salvo decisão explícita futura:

- GitHub Issue/PR IDs;
- branch/CI internals;
- ClickUp custom fields internos;
- estado bruto de LangGraph;
- prompts e traces de LangSmith;
- custos/margens comerciais internos.

## Aceitação

Quando uma entrega entra em `CLIENT_REVIEW`, One pode apresentar a pendência ao cliente. A decisão do cliente deve gerar evento canônico e retornar ao BiahflowOS/ClickUp por contrato explícito.

`client.accepted` pode permitir a transição para `ACCEPTED`; somente regras do lifecycle de Delivery podem concluir `DONE`.

## Consequências

- O webhook/snapshot existente evolui para contrato de projeção versionado.
- One não precisa consultar ClickUp ou GitHub diretamente.
- A experiência continua disponível mesmo que uma ferramenta interna seja substituída, desde que o contrato de projeção permaneça.

*Retificado em 25/08/2026 (ADR 0069), no cabeçalho: esta ADR e a 0068 nasceram com
`**Status:** Accepted` e data em ISO, e o vocabulário da guarda de índice é `{aceito, aceita}`
com data `DD/MM/AAAA` (ADR 0054). O texto da decisão não foi tocado — o que estava errado era o
cabeçalho, e ele deixava `test_roadmap_index.py` vermelho a cada push desde 24/08/2026.*
