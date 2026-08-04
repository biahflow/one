# FDD 007 — Login corporativo e isolamento por tenant

O cliente entra no portal com a identidade da empresa (Keycloak/OIDC) e vê **apenas** os
projetos aos quais está vinculado. Tentativas de acesso cruzado falham na API *e* no banco,
não só na camada de aplicação.

## Objetivo e não objetivos

**Objetivo.** Substituir a identidade de mentira — um e-mail em header (`X-Portal-User`),
preenchido a partir de uma variável de ambiente — por um token verificado, e transformar a
promessa de RLS da ADR 0002 em policies que existem e mordem.

**Não objetivos.** Convite e verificação de e-mail (Mailpit), UI de administração de
organizações/projetos/membros e configuração financeira. Seguem na fase seguinte.

**Entregue** (etapas 3–11 do plano da Fase 1): RLS com contexto por transação, validação de
JWT na FastAPI, papéis por endpoint e `GET /api/v1/me`; realm com client confidencial e
usuários semeados; seed alinhado ao realm pelo `sub`; Auth.js v5 no BFF com `/login`, portão de
sessão e logout de verdade; e o fim do fallback de demonstração no `app/page.tsx`.

## Jornada e interface

`/` sem sessão redireciona para `/login`, que tem um botão só — o SSO da empresa; não há mais
campo de senha, porque a credencial nunca chega a este domínio. Na volta do Keycloak, o
dashboard mostra o nome vindo do token, a organização e os projetos vêm de `GET /api/v1/me`, e
trocar de projeto recarrega os dados (`/?project=<id>`) em vez de só trocar o cabeçalho. O menu
de perfil encerra a sessão no cookie **e** no Keycloak, então o F5 não devolve o dashboard.

Quando a API nega ou some, a tela diz o que houve: 401 volta para `/login`, 404 vira "você
ainda não tem um projeto atribuído", e falha de rede vira painel de erro. Nenhum desses
caminhos leva a dado inventado.

## Dados, API e permissões

| Endpoint | Regra |
|---|---|
| `GET /api/v1/me` | qualquer principal válido; devolve 200 com `projects: []` para quem não tem vínculo |
| `GET /api/v1/me/dashboard` | projeto do vínculo direto; para staff org-wide, o projeto mais recente da organização |
| `GET /api/v1/projects/{id}/dashboard` | qualquer vínculo com o projeto |
| `POST /api/v1/chat` | qualquer vínculo; a pendência criada por lacuna registra o autor em `audit_log` |
| `POST /api/v1/agent-events` | exige `internal_admin` **no projeto do evento** |
| webhook do Biahflow | inalterado (HMAC), no papel `portal_system` |

A `membership` é a autoridade de autorização; o realm role do token é indício, usado só para
marcar `is_internal` no provisionamento. Um realm role não sabe *em qual projeto*.

Identidade resolvida em três passos (`portal_api/identity.py`): por `external_subject`; senão
por e-mail sobre uma linha semeada sem `sub`, que é então reivindicada; senão provisionada.

Isolamento no banco: 15 tabelas com RLS, contexto publicado em GUCs por transação
(`portal.subject`, `portal.email`, `portal.user_id`, `portal.organization_id`,
`portal.project_id`). Detalhes e o porquê de cada escolha na ADR 0010.

## Estados de erro e segurança

- **Sempre 404, nunca 403**, em qualquer negação de projeto — a resposta não revela que o
  projeto existe. Com a RLS, isso passa a ser preservado pelo próprio banco: `session.get`
  devolve `None` para não-membro.
- **401 opaco.** Token ausente, expirado, de outro emissor, para outra audiência, sem
  assinatura ou com e-mail não verificado produzem a mesma resposta; o motivo vai só para log
  estruturado, para não virar oráculo de sondagem.
- **Fail-closed.** GUC não publicada ⇒ predicado NULL ⇒ zero linhas. O modo de falha de uma
  implementação errada é "não vejo nada", nunca "vejo tudo". O diagnóstico está em
  `docs/runbooks/auth-failure.md`.
- **Autenticar não é autorizar.** Um usuário do realm sem membership entra e não alcança nada.
- Auditoria: `identity.linked` e `identity.provisioned` como log estruturado (não cabem em
  `audit_log`, que exige organização); `chat.pending_created` em `audit_log`, com o autor e
  **sem** o texto da pergunta (`docs/data-classification.md`).

## Telemetria e critérios de aceite

1. Requisição sem `Authorization: Bearer` recebe 401 em todo endpoint de cliente. ✔
2. Cliente da organização A pedindo projeto da B recebe 404. ✔
3. Sem contexto de tenant ligado, uma leitura crua devolve zero linhas. ✔
4. `client_member` não consegue publicar evento de agente; `internal_admin` consegue, e só na
   sua organização. ✔
5. Usuário semeado sem `sub` é ligado no primeiro login, e o `sub` persiste. ✔
6. Toda tabela nova com `organization_id` nasce com policy — cobrado por meta-teste. ✔
7. Login no navegador ponta a ponta, com logout que o F5 não desfaz. ✔ *(`tests/e2e/login.spec.ts`)*
8. Nenhuma falha da API produz dado fabricado — o demo só existe atrás de `demoShellEnabled()`,
   e há teste que falha se alguém alcançá-lo por fora. ✔

## Testes e avaliações de IA

- `apps/api/tests/test_rls_isolation.py` — isolamento no nível do banco, no papel `portal_app`,
  com `select()` cru e sem repositório; inclui o guard de `rolsuper`/`rolbypassrls` e o
  meta-teste de cobertura de policies.
- `apps/api/tests/test_auth_jwt.py` — validação do token sem Keycloak: par RSA em memória e
  JWKS forjado; cobre emissor, audiência, expiração, `alg: none`, confusão de algoritmo,
  `kid` desconhecido e e-mail não verificado.
- `apps/api/tests/test_authorization.py` — negativos de permissão pelo stack HTTP real.
- `apps/api/tests/test_dashboard_scope.py` — gates de identidade e escopo por membership.
- `apps/api/tests/test_seed_matches_realm.py` — realm e `SEED_USERS` 1:1 (inclusive o mapper de
  audiência, sem o qual todo token válido seria rejeitado); roda sem Keycloak e sem Postgres.
- `tests/rendered-html.test.mjs` — SSR anônimo (307 para `/login`), `/login` renderizada e SSR
  autenticado com cookie forjado pelo `encode()` do Auth.js sobre uma API de mentira que exige
  Bearer; mais a varredura que impede o retorno de `X-Portal-User` e de dado fixo.
- `tests/e2e/login.spec.ts` — o navegador de verdade contra o realm de verdade: cliente,
  interno por membership org-wide, e o fim de sessão.

Avaliações de IA: **não se aplica — esta feature não altera prompt, recuperador, modelo ou
ferramenta.** A única interseção com o chat é o registro de auditoria da pendência.
