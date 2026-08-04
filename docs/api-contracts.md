# Contratos de API

Todo endpoint de cliente exige `Authorization: Bearer <access token>` (ADR 0010). Sem token, ou
com token inválido, a resposta é **401 opaca**; sem vínculo com o recurso, **404 — nunca 403**,
para não revelar que o projeto existe.

`GET /api/v1/me` devolve `email`, `fullName`, `isInternal`, `notifyByEmail`, `organization`,
`projects` e `roles` do próprio chamador. Um usuário autenticado sem membership recebe 200 com
`projects` vazio: autenticar não é autorizar.

Notificações e preferências (ADR 0012), sempre do próprio chamador e escopadas ao projeto que a
API resolve para ele — nenhuma delas recebe id de usuário:

- `GET /api/v1/me/notifications?unreadOnly=&limit=` — `{unreadCount, items[]}`, cada item com
  `kind`, `title`, `detail`, `link`, `occurredAt` e `read`. Sem projeto resolvido, 404.
- `POST /api/v1/me/notifications/read` — `{ids}` ou `{}` para marcar todas as suas; devolve
  quantas foram marcadas.
- `PATCH /api/v1/me/preferences` — `{notifyByEmail}`.

As rotas de administração de acesso (ADR 0011) exigem `internal_admin` **no projeto** e vivem
sob `/api/v1/admin`:

- `GET /projects/{id}/members` — nome, e-mail, papel e `active` (e-mail já confirmado no realm;
  `false` é convite pendente).
- `POST /projects/{id}/members` — `email`, `fullName` e `role`. Cria a conta no realm se
  faltar, grava o vínculo e dispara o e-mail de definir senha + verificar endereço. Idempotente
  por e-mail, e com **resposta uniforme** para endereço conhecido e desconhecido.
- `DELETE /projects/{id}/members/{membershipId}` — remove o vínculo; a conta permanece.
  Revogar o próprio acesso responde 409.

`POST /api/v1/agent-events` recebe `eventId`, `projectId`, `occurredAt`, `agentKey`, `timeSavedSeconds`, `avoidedCostCents` e `runReference`. O `eventId` é idempotente por projeto.

`POST /api/v1/chat` recebe `projectId` e `question`; devolve texto, `sources`, confiança e, quando necessário, a pendência criada. Contratos completos serão publicados automaticamente pelo OpenAPI do FastAPI.
