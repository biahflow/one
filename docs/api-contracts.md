# Contratos de API

`POST /api/v1/agent-events` recebe `eventId`, `projectId`, `occurredAt`, `agentKey`, `timeSavedSeconds`, `avoidedCostCents` e `runReference`. O `eventId` é idempotente por projeto.

`POST /api/v1/chat` recebe `projectId` e `question`; devolve texto, `sources`, confiança e, quando necessário, a pendência criada. Contratos completos serão publicados automaticamente pelo OpenAPI do FastAPI.
