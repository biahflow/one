# Contratos de API

Todo endpoint de cliente exige `Authorization: Bearer <access token>` (ADR 0010). Sem token, ou
com token inválido, a resposta é **401 opaca**; sem vínculo com o recurso, **404 — nunca 403**,
para não revelar que o projeto existe.

`GET /api/v1/me` devolve `email`, `fullName`, `isInternal`, `organization`, `projects` e
`roles` do próprio chamador. Um usuário autenticado sem membership recebe 200 com `projects`
vazio: autenticar não é autorizar.

`POST /api/v1/agent-events` recebe `eventId`, `projectId`, `occurredAt`, `agentKey`, `timeSavedSeconds`, `avoidedCostCents` e `runReference`. O `eventId` é idempotente por projeto.

`POST /api/v1/chat` recebe `projectId` e `question`; devolve texto, `sources`, confiança e, quando necessário, a pendência criada. Contratos completos serão publicados automaticamente pelo OpenAPI do FastAPI.
