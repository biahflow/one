# Contratos de API

**A lista de campos vive em [`api/openapi.json`](api/openapi.json)** (ADR 0020), gerado do código
por `python -m portal_api.openapi` e conferido a cada push — este arquivo descreve as **regras**,
que é o que um esquema não sabe dizer. Até a Fase 5 era o contrário: a lista de campos estava aqui,
em camelCase, e a API respondia snake_case. Nada conferia, e por isso ninguém soube por meses.

Todo endpoint de cliente exige `Authorization: Bearer <access token>` (ADR 0010). Sem token, ou
com token inválido, a resposta é **401 opaca**; sem vínculo com o recurso, **404 — nunca 403**,
para não revelar que o projeto existe. As duas regras são hoje propriedades verificadas do
esquema: `test_openapi_contract.py` recusa qualquer rota que declare 403, cobra o 401 de toda
rota autenticada e o 404 de toda rota escopada por tenant.

**Os identificadores são snake_case**, em todo corpo de requisição e de resposta.

`GET /api/v1/me` diz quem é o chamador e o que ele alcança. É uma das duas rotas de cliente que
**não** respondem 404 (a outra é `PATCH /api/v1/me/preferences`): quem autentica sem membership
recebe 200 com `projects` vazio, porque autenticar não é autorizar e o portal precisa poder dizer
"você ainda não tem projeto".

Notificações e preferências (ADR 0012), sempre do próprio chamador e escopadas ao projeto que a
API resolve para ele — nenhuma delas recebe id de usuário:

- `GET /api/v1/me/notifications?unread_only=&limit=` — a contagem de não lidos e os avisos. Sem
  projeto resolvido, 404.
- `POST /api/v1/me/notifications/read` — `ids` ou corpo vazio para marcar todas as suas; devolve
  quantas foram marcadas.
- `PATCH /api/v1/me/preferences` — hoje só o e-mail das notificações.

As rotas de administração de acesso (ADR 0011) exigem `internal_admin` **no projeto** e vivem
sob `/api/v1/admin`:

- `GET /projects/{id}/members` — nome, e-mail, papel e `active` (e-mail já confirmado no realm;
  `false` é convite pendente).
- `POST /projects/{id}/members` — cria a conta no realm se faltar, grava o vínculo e dispara o
  e-mail de definir senha + verificar endereço. Idempotente por e-mail, e com **resposta
  uniforme** para endereço conhecido e desconhecido.
- `DELETE /projects/{id}/members/{membership_id}` — remove o vínculo; a conta permanece.
  Revogar o próprio acesso responde 409.

As rotas de **resultados** para administração (ADR 0013) ficam sob o mesmo `/api/v1/admin` e
exigem `internal_admin` no projeto:

- `GET|POST /projects/{id}/keys` — chaves dos agentes. O POST devolve `key` **em claro uma única
  vez**; depois só existe o hash. `usable` diz se a chave ainda autentica.
- `POST /projects/{id}/keys/{key_id}/rotate` — emite a sucessora (com `rotated_from_id`) e revoga
  a anterior. `DELETE /projects/{id}/keys/{key_id}` revoga sem apagar a linha.
- `GET|POST /projects/{id}/assumptions` — premissas financeiras. O POST fecha a vigência corrente
  na data informada e abre a nova; `effective_from` anterior à vigência aberta responde **409**.

`POST /api/v1/agent-events` é a **única rota autenticada por chave**, no header `X-Agent-Key`, e
não aceita `Authorization: Bearer` (ADR 0013) — o esquema afirma as duas metades disso, e há um
teste que quebra se uma segunda rota passar a aceitar chave. Cuidado com um nome: o `agent_key`
**do corpo** é o rótulo do agente que executou, não a credencial; a credencial só viaja no header.

O `event_id` é idempotente por projeto: 202 com `status` `accepted` na primeira vez e `duplicate`
no reenvio. `project_id` diferente do projeto da chave é **404**. Chave ausente, desconhecida,
revogada, expirada ou sem escopo é o mesmo **401 opaco**; ritmo acima do limite é **429** com
`Retry-After` — a única recusa que não é opaca, porque o produtor precisa distinguir "seu ritmo"
de "sua credencial" para saber se deve tentar de novo.

`GET /api/v1/projects/{id}/results?from=&to=` devolve a apuração do período — horas, economia,
investimento rateado, ROI, precisão e exceções — **junto das premissas vigentes e das lacunas**
(`gaps`), para todo indicador exibido ter origem verificável. Sem `from`/`to`, os últimos 30 dias.
O mesmo bloco viaja no dashboard como `measured`.

`POST /api/v1/chat` recebe `project_id` e `question`; devolve o texto, as citações **como foram
exibidas**, a confiança e, quando faltou evidência, o aviso de que uma pendência foi aberta —
nunca uma resposta inventada (regra 3 do `AGENTS.md`). `conversation_id` ausente abre uma nova
thread, que é como "nova conversa" funciona sem endpoint próprio (ADR 0015).

## Onde isto é verificado

- `docs/api/openapi.json` — o esquema, versionado. Regerar com
  `PYTHONPATH=apps/api/src python -m portal_api.openapi --write`; o diff é a mudança de contrato.
- `apps/api/tests/test_openapi_contract.py` — o gate de deriva e as regras acima como propriedades
  de **toda** rota, inclusive a que ainda não existe.
- `tests/api-contract.test.mjs` — a fixture do teste de SSR do web validada contra o mesmo esquema,
  para a API de mentira dos testes não poder mentir.
