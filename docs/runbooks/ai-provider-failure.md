# Runbook — Falha do provedor de IA

Desabilitar novas respostas, manter documentos e chat histórico disponíveis e avisar que a
resposta contextual está temporariamente indisponível. Não usar um provedor alternativo sem
revisão de dados e contrato.

## Telemetria de falha (ADR 0018, corrigida na ADR 0021)

O provedor entra por dois adaptadores e falha em **três** lugares — dois no caminho de
requisição e um na indexação:

```bash
docker compose logs api    | grep '"event":"chat.provider_unavailable"'  # resposta do chat
docker compose logs api    | grep '"event":"embedding.unavailable"'      # recuperação do chat
docker compose logs worker | grep '"event":"embedding.failed"'           # indexação
```

Até a Fase 5 esta seção mandava procurar `"event":"http.failed"` para a resposta do chat, e
esse grep **nunca devolvia nada**: `ai/service.py` engole toda exceção do provedor para cair no
respondedor offline, então o `http.failed` do `TraceMiddleware` — que só vê exceção que sobe —
não dispara, e o `logger.warning` que existia não tinha nome de evento. Uma queda real do
provedor degradava em silêncio absoluto. O evento agora existe e traz `responder`, `model` e
`reason` (`ProviderRefused` distingue recusa do classificador de parser quebrado).

`embedding.unavailable` é o mesmo tipo de falha do outro lado da resposta: o embedder de
consulta caiu, e o chat responde **só** com o read model estruturado — sem trecho de documento,
portanto sem as citações que dependiam do índice. Nome distinto de `embedding.failed` de
propósito: lá o documento fica fora do índice até alguém reindexar, aqui a próxima pergunta pode
dar certo, e um nome só faria o limiar do `alerts.md` significar duas coisas.

`embedding.failed` traz o `document_id`: o documento fica `failed` e **não entra no índice**,
então o chat passa a declarar a lacuna para perguntas que dependiam dele — comportamento
correto, por motivo errado. O limiar está em `alerts.md` (5 em 1 h).

## Como a degradação silenciosa se parece

Nenhum dos três derruba o chat, e é justamente por isso que dá para não perceber. O que aparece,
nesta ordem: as respostas **param de citar**, a taxa de lacuna sobe, e a fila de pendências
abertas pelo chat cresce sem que ninguém tenha perguntado nada de novo. Se o painel mostra
"pendências abertas" subindo sem pico de tráfego, comece por estes três greps antes de procurar
regressão de prompt.

Para separar as duas metades, o `chat.answered` de cada turno traz `responder`, `model`,
`confidence` e a contagem de citações; e o mesmo par está gravado em `conversation_message`
(`responder = 'offline_fallback'` é exatamente um turno que caiu no fallback). O log responde
"está acontecendo agora"; a coluna responde "aconteceu na terça passada".

Vale lembrar o que **não** é falha do provedor: sem `ANTHROPIC_API_KEY` ou `VOYAGE_API_KEY` o
portal usa o respondedor e o embedder offline determinísticos (ADRs 0007 e 0014), sem erro
nenhum no log. Uma stack que "não está citando" com as chaves vazias está funcionando como
desenhado.
