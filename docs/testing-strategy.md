# Estratégia de testes

## Pirâmide

1. Unitários: regras de domínio, parsers, cálculos de ROI, componentes e prompts.
2. Integração: PostgreSQL/pgvector, RLS, Redis, MinIO, Keycloak, jobs e adaptadores simulados.
3. Contrato: OpenAPI e payloads da API de eventos e respostas estruturadas da IA.
4. E2E: Playwright em Docker Compose, com fluxos de cliente e equipe interna.
5. Avaliação de IA: dataset versionado, casos adversariais e rubric de correção/citação.

Cobertura mínima inicial: 80% para código de domínio e componentes críticos. Não use cobertura como substituto de cenários de autorização, segurança ou IA.
