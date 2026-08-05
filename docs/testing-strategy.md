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
6. **Contrato: o esquema é artefato, e ele afirma as regras.** `docs/api/openapi.json` é gerado do
   código e versionado; `test_openapi_contract.py` recusa a deriva (como o `alembic check`) e
   afirma sobre **toda** rota — inclusive a que alguém acrescentar amanhã — que ninguém declara
   403, que rota autenticada declara 401, que rota escopada declara 404, que só a de eventos
   aceita chave e que nenhum campo de resposta tem nome de segredo. Dois casos fecham o outro
   lado: o payload real do dashboard e o da apuração atravessam os modelos **e voltam iguais**,
   porque `response_model` filtraria em silêncio o que o modelo não declara. No web,
   `tests/api-contract.test.mjs` valida a fixture do nível 5 contra o mesmo esquema — sem isso a
   API de mentira daquele teste é livre para mentir, e dois enganos combinam entre si.
   *Este nível esteve listado aqui e não existiu até a Fase 5 (ADR 0020).*
7. **E2E: Playwright em Docker Compose** (`tests/e2e/`), o único nível que sobe o Keycloak de
   verdade — porque é o único que prova o que os outros não alcançam: redirect do anônimo,
   code exchange no callback do BFF, dashboard com o nome vindo do token, e o "Sair" que o F5
   não desfaz. Cliente e equipe interna, esta última entrando pela membership org-wide. O
   `invite.spec.ts` vai além e **lê a caixa do Mailpit pela API** (`:8025/api/v1/search`) para
   seguir o link do convite, definir a senha e entrar: é o único ponto onde "o e-mail chega"
   é verificado, e por isso os testes de API podem dublar o Keycloak sem perder nada.
8. **Avaliação de IA: dataset versionado, e o adversarial roda contra o respondedor real.**
   Até a Fase 5 os catorze casos rodavam no `OfflineResponder`, um casador determinístico que não
   tem como obedecer a uma instrução — a eval de prompt injection provava que uma pedra não atende
   ao telefone. A ADR 0021 abriu a costura (`anthropic_client`, na forma do `session_client` do
   Drive) e acrescentou um falso que **registra o pedido** e devolve o que um atacante escolheria:
   fonte inventada, fonte de outro tenant, afirmação sem citação, prosa no lugar de JSON,
   obediência à injeção. Continua determinístico e sem chave, porque o falso é local.
   Duas propriedades do arquivo carregam o resto: o primeiro caso é a **guarda** dos outros treze
   (uma chave configurada seleciona o respondedor real — sem ele, uma fixture quebrada faria o
   conjunto re-testar o offline em verde), e metade das asserções olha o **pedido enviado** e não a
   resposta, que é a única forma de afirmar que segredo e texto de outro projeto não saíram do
   processo.

Cobertura mínima inicial: 80% para código de domínio e componentes críticos. Não use cobertura como substituto de cenários de autorização, segurança ou IA.

## Um pulo não é um teste que passou

Um `skip` afirma algo sobre o **ambiente**: "aqui não dá para provar isto". Na máquina de quem
desenvolve isso costuma ser verdade e é útil — um `pytest` cru passa sem a pilha no ar. No CI a
mesma frase é falsa e é cara: o job *tem* Postgres, o job *sobe* a pilha, e ali um pulo não diz
"falta ambiente", diz "o ambiente não está como se pensava" — em verde.

Foi assim que as três asserções que dão sentido ao backup (ADR 0019) deixaram de rodar por
semanas, por falta de duas variáveis num `env:`. Desde a ADR 0020, `skip_unless_ci` (Python) e
`stackIsMissing` (`tests/e2e/stack.ts`) **falham** quando `CI` está definida. Vale só para o que o
CI deve cobrir: o que ele legitimamente não tem — ClamAV, chave da Voyage — continua pulando, e
ali o pulo continua verdadeiro. É a regra da ADR 0017, *`skipped` não é `clean`*, aplicada ao
próprio arsenal de testes.

Pela mesma razão nenhum job que prova algo é `continue-on-error`. Um job que não pode reprovar não
é um portão, é um enfeite que treina a equipe a ignorar o painel.
