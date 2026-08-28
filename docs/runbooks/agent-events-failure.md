# Runbook — API de eventos dos agentes

A rota é `POST /api/v1/agent-events`, autenticada por chave de projeto no header `X-Agent-Key`
(ADR 0013). Ela é a única porta pela qual um resultado entra no portal: parada, o cliente não vê
número errado — vê o número parar de crescer, com a lacuna declarada na tela.

## Sintoma: o produtor recebe 401

As recusas de credencial são **indistinguíveis por desenho** — inexistente, revogada, expirada e
sem escopo devolvem o mesmo corpo. O motivo está no log estruturado da API:

```bash
docker compose logs api | grep '"event":"agent_key.rejected"'
```

Cada linha é um JSON (ADR 0018):

```json
{"ts":"2026-08-05T14:02:11+0000","level":"WARNING","logger":"portal_api.agent_auth",
 "event":"agent_key.rejected","trace_id":"9f2c…","reason":"revoked_agent_key","key_prefix":"plk_l8kBU6XX"}
```

O campo `reason` diz qual foi (`missing_agent_key`, `unknown_agent_key`, `revoked_agent_key`,
`expired_agent_key`, `missing_scope`) e `key_prefix` identifica a chave sem revelá-la — ele é a
única exceção da redação de segredos do formatter, e é obrigatória justamente porque este
runbook depende dele. Até a ADR 0018 os dois campos existiam no código e **não eram
impressos**; se o `grep` acima devolver linhas sem eles, a imagem em execução é anterior a ela.

O `trace_id` da linha leva à requisição inteira (`incident-response.md`).

Causas na ordem em que costumam acontecer:

1. **`AGENT_KEY_PEPPER` mudou ou está vazio.** O pepper entra no HMAC, então trocá-lo invalida
   **todas** as chaves de uma vez — é rotação em massa, não configuração de rotina. Vazio faz a
   API levantar em vez de autenticar com hash previsível: nenhuma chave funciona.
2. **A chave expirou.** Prazo é obrigatório. `GET /api/v1/admin/projects/{id}/keys` mostra
   `expiresAt` e `usable`.
3. **Foi revogada** — inclusive por uma rotação, que revoga a antecessora.
4. **O produtor está mandando `Authorization: Bearer`.** Desde a Fase 3 a rota não aceita sessão
   humana; o Bearer é ignorado e falta a chave.

## Sintoma: 429

O limite é por chave, em janela deslizante de um minuto (`AGENT_EVENTS_RATE_LIMIT`, 120 por
padrão), contada na própria linha da chave. A resposta traz `Retry-After` em segundos — o produtor
deve respeitá-lo em vez de retentar imediatamente. `agent_key.rate_limited` no log tem o prefixo.

Se o volume legítimo cresceu, suba o limite; se um produtor entrou em laço, revogue a chave dele
sem tocar nas outras — é para isso que a chave é por projeto e por agente.

## Sintoma: 404 ao publicar

O `projectId` do corpo não é o projeto da chave. É a conferência funcionando: quem responde "qual
projeto" é a credencial. Confirme qual projeto a chave atende em `/admin/results`.

## Suspeita de chave vazada

1. **Revogue** em `/admin/results` (ou `DELETE .../keys/{keyId}`) — vale na requisição
   seguinte, sem restart.
2. **Rotacione** para o produtor legítimo: a sucessora nasce ligada à antecessora
   (`rotatedFromId`), então a troca fica reconstituível.
3. **Levante o uso** em `audit_log`, ação `agent_event.ingested`, e em `lastUsedAt` na chave.
4. Siga `docs/runbooks/incident-response.md`. A linha revogada **não é apagada**: ela é o rastro
   de que a chave existiu e foi usada.

Não há como recuperar uma chave perdida — o banco só tem o HMAC. O caminho é sempre rotacionar.

## Sintoma: eventos entram, mas o valor não sobe

Os eventos contam como volume e não viram dinheiro quando não há premissa vigente na data deles.
A tela do cliente já declara isso (`no_assumption`, `events_outside_assumption`), e
`GET /api/v1/projects/{id}/results` traz o mesmo em `gaps` com as vigências que cobrem o período.

Abrir uma vigência retroativa **não** reescreve o passado exibido: a nova vigência começa na data
informada, e retroagir sobre a vigência aberta é recusado com 409. Se o valor de um período antigo
precisa mudar, isso é uma correção deliberada de premissa — não uma edição.

## Sintoma: ROI aparece como travessão

Investimento zero ou ausente. O cálculo devolve nulo em vez de dividir por zero, com a lacuna
`no_investment`. Configure o investimento mensal em `/admin/results`.
