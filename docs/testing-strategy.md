# Estratégia de testes

## Pirâmide

1. Unitários: regras de domínio, parsers, cálculos de ROI, componentes e prompts.
2. Integração: PostgreSQL/pgvector, Redis, MinIO, Keycloak, jobs e adaptadores simulados.
3. **Isolamento no banco:** um nível próprio, porque é o único que prova a segunda barreira.
   `test_rls_isolation.py` roda no papel `portal_app` com `select()` cru e **sem repositório** —
   passar por um repositório testaria a camada de aplicação de novo, não a policy. Inclui o
   guard de `rolsuper`/`rolbypassrls` (sem ele, uma `DATABASE_URL` apontada para o superusuário
   faria todo o arquivo passar sem provar nada) e o meta-teste que cobra policy de toda tabela
   nova com `organization_id`.
4. **Token sem Keycloak:** `test_auth_jwt.py` gera um par RSA em memória e serve um JWKS falso,
   então emissor, audiência, expiração, `alg: none` e confusão de algoritmo são cobertos no CI
   sem subir realm nenhum — mais rápido e determinístico que um Keycloak de teste.
5. Contrato: OpenAPI e payloads da API de eventos e respostas estruturadas da IA.
6. E2E: Playwright em Docker Compose, com fluxos de cliente e equipe interna.
7. Avaliação de IA: dataset versionado, casos adversariais e rubric de correção/citação.

Cobertura mínima inicial: 80% para código de domínio e componentes críticos. Não use cobertura como substituto de cenários de autorização, segurança ou IA.
