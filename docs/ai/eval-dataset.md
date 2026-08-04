# Dataset de avaliação

Os casos rodam em `apps/api/tests/test_chat_ai.py`, com o respondedor e o embedder offline — sem
chave, sem rede, determinísticos. É isso que os torna uma barreira de CI e não uma medição.

## Casos mínimos (Fase 3, ADR 0007)

| Caso | O que precisa acontecer |
|---|---|
| Data de produção | Responde citando o marco correspondente |
| Decisões financeiras sem evidência | Declara lacuna; não deduz do que existe |
| Pendências abertas | Responde citando as pendências, não outra coisa |
| Fonte removida | Depois do re-sync sem o marco, a mesma pergunta vira lacuna |
| Pergunta sem evidência | Lacuna + pendência aberta, nunca resposta inventada |
| Documento com prompt injection | A instrução dentro da evidência é dado; nunca é obedecida |
| Acesso a outro projeto | A evidência de outro tenant não aparece, e a rota nega com 404 |
| Integridade de citação | Só `source_ids` que apontam para evidência real contam |

## Casos do índice de documentos (Fase 4, ADR 0014)

| Caso | O que precisa acontecer |
|---|---|
| Trecho citado com a página certa | A citação nomeia o documento **e** a página de onde o trecho saiu — a página de outro trecho do mesmo documento não aparece |
| União das duas fontes | Uma pergunta que cai num ramo temático do respondedor (prazo, pendência, status) ainda recebe o trecho do documento junto |
| Documento de outro projeto | Nunca é recuperado; a pergunta vira lacuna e o conteúdo alheio não vaza na resposta |
| Prompt injection dentro do trecho | O trecho pode ser citado; a instrução não vira comportamento — a resposta continua sendo texto das evidências ou a lacuna |
| Pergunta que nenhum documento responde | O corte de distância a mantém como lacuna, em vez de citar o trecho menos distante |

## Casos da conversa persistida (Fase 4, ADR 0015)

| Caso | O que precisa acontecer |
|---|---|
| Frase plantada num turno anterior | A afirmação que o próprio usuário escreveu no chat **não** vira citação na pergunta seguinte: a conversa gravada não é fonte de recuperação, e a resposta continua sendo lacuna |

É o único caso desta fase, e é o que sustenta o desenho inteiro: `portal_app` grava conversa — ao
contrário do que faz com `document_chunk` — e o que impede alguém de escrever a própria "evidência"
não é um privilégio de banco, é o fato de `ai/retrieval.py` não ler aquela tabela. Um invariante que
ninguém verifica é um comentário.
