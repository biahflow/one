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
5. **SSR autenticado sem navegador:** `tests/rendered-html.test.mjs` sobe o `next start`, forja
   o cookie de sessão com o `encode()` do próprio Auth.js (o salt é o nome do cookie) e serve
   uma API de mentira em `node:http` que responde **401 sem `Authorization`** — é isso que faz
   as asserções provarem que o token viajou, e não apenas que a página renderizou. O mesmo
   arquivo varre as fontes: `DEMO_OVERVIEW` só pode aparecer dentro do bloco
   `demoShellEnabled()`, e `X-Portal-User`/`PORTAL_CLIENT_EMAIL` não podem voltar.
6. Contrato: OpenAPI e payloads da API de eventos e respostas estruturadas da IA.
7. **E2E: Playwright em Docker Compose** (`tests/e2e/`), o único nível que sobe o Keycloak de
   verdade — porque é o único que prova o que os outros não alcançam: redirect do anônimo,
   code exchange no callback do BFF, dashboard com o nome vindo do token, e o "Sair" que o F5
   não desfaz. Cliente e equipe interna, esta última entrando pela membership org-wide. O
   `invite.spec.ts` vai além e **lê a caixa do Mailpit pela API** (`:8025/api/v1/search`) para
   seguir o link do convite, definir a senha e entrar: é o único ponto onde "o e-mail chega"
   é verificado, e por isso os testes de API podem dublar o Keycloak sem perder nada.
8. Avaliação de IA: dataset versionado, casos adversariais e rubric de correção/citação.

Cobertura mínima inicial: 80% para código de domínio e componentes críticos. Não use cobertura como substituto de cenários de autorização, segurança ou IA.
