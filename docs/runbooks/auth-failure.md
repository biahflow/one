# Runbook — falha de autenticação e acesso

## Sintoma: "todo mundo vê 404" (ou dashboards vazios)

**É o modo de falha mais provável desta fase, e quase nunca é permissão de verdade.** Com a
RLS ligada, um contexto de tenant não publicado faz o predicado das policies ser NULL — e a
consulta devolve **zero linhas, sem erro**. O sintoma é indistinguível de "o usuário não tem
acesso".

Ordem de diagnóstico:

1. **A credencial é a certa?**

   ```sql
   SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;
   ```

   `portal_app` com `(f, f)` é o esperado no caminho de requisição. Se vier `portal` ou
   `rolbypassrls = t`, o problema é o oposto: a RLS está sendo ignorada e **ninguém está
   protegido** — trate como incidente, não como bug de acesso.

2. **As GUCs chegaram na transação?** Dentro da mesma transação da requisição:

   ```sql
   SELECT current_setting('portal.user_id', true), current_setting('portal.organization_id', true);
   ```

   Vazio no estágio 1 ⇒ o endpoint não passou o `principal` para `get_session`.
   Vazio só no estágio 2 ⇒ alguém resolveu o projeto sem passar por `access.scoped_project`/
   `access.default_project`, que são quem chamam `bind_tenant`. **Essa é a causa mais comum.**

3. **A policy existe na tabela?**

   ```sql
   SELECT relname, relrowsecurity FROM pg_class c
     JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'portal' AND relname = '<tabela>';
   SELECT policyname, cmd FROM pg_policies WHERE schemaname = 'portal' AND tablename = '<tabela>';
   ```

   Tabela nova sem policy é bug de migração — o teste
   `test_every_tenant_table_has_rls_enabled_and_a_policy` deveria ter barrado no CI.

4. **É `GRANT` e não policy?** `permission denied for table X` é privilégio, não RLS: a
   matriz vive na migração `0007` e em `infra/postgres/bootstrap/roles.sql`. Lembre que
   `INSERT ... RETURNING` exige **também** SELECT — é por isso que `AuditLog` usa
   `eager_defaults=False`.

## Sintoma: todo token é rejeitado (401)

O corpo do 401 é sempre opaco, de propósito. O motivo está no log estruturado, em
`auth.rejected`, com o campo `reason`:

| `reason` | Causa provável |
|---|---|
| `missing_bearer_token` | o BFF não encaminhou o `Authorization` |
| `invalid_token` (`ExpiredSignatureError`) | relógio fora de sincronia ou refresh quebrado no BFF |
| `invalid_token` (`InvalidIssuerError`) | `OIDC_ISSUER` ≠ o host que o navegador usou para logar |
| `invalid_token` (`InvalidAudienceError`) | falta o audience mapper no client do realm — o `aud` vem `account` |
| `invalid_token` (`PyJWKClientError`) | JWKS inalcançável ou chave rotacionada |
| `email_not_verified` | usuário do realm sem `emailVerified` |
| `unexpected_azp` | token emitido por outro client |

**`iss` ≠ JWKS é esperado**, não um erro de configuração: o navegador fala com o Keycloak em
`localhost:8080` (e é esse valor que entra no `iss`), enquanto o container da API o alcança em
`keycloak:8080`. São duas settings separadas justamente por isso.

## Sintoma: o usuário volta para `/login` sem ter saído

O `proxy.ts` trata "refresh falhou" como "sem sessão", de propósito — a alternativa seria um
dashboard cujas requisições voltam todas 401. A marca é `token.error` no cookie, e a causa está
no `callbacks.jwt` de `auth.ts`:

- **refresh token expirado ou já usado.** O Keycloak rotaciona o refresh token; se uma resposta
  se perdeu, o token guardado ficou para trás e o próximo refresh falha. Sair e entrar resolve.
- **`KEYCLOAK_INTERNAL_URL` errado.** O refresh é server-to-server: ele usa o endereço interno,
  não o público. Se só o login funciona e a sessão morre alguns minutos depois, é este.
- **Sessão de SSO encerrada no Keycloak** (logout em outra aba, ou `bruteForceProtected` tendo
  bloqueado a conta).

## Sintoma: "HTTPS required" na tela do Keycloak

A tela de login do realm responde 400 com "We are sorry… HTTPS required". É o `sslRequired` do
realm: no padrão (`external`) o Keycloak exige TLS para quem não chega pelo loopback — e uma
requisição publicada por porta do Docker chega pelo gateway da rede, não pelo loopback. O realm
local declara `"sslRequired": "none"` justamente para não depender dessa heurística; se o
sintoma voltar, confirme que o realm importado é o versionado (o import é ignorado quando o
realm **já existe** no banco: apague o schema `keycloak`, rode `db-bootstrap` e reinicie).

Em ambiente com TLS, o valor correto é o padrão — não copie `none` para fora do local.

## Sintoma: o convite não chega

O `POST /api/v1/admin/projects/{id}/members` respondeu 201, a pessoa aparece como "convite
pendente" e nenhum e-mail chegou. Em ordem de probabilidade:

1. **SMTP do realm.** É a causa mais comum e a mais silenciosa: sem `smtpServer`, o Keycloak
   aceita o `execute-actions-email` e não manda nada. Confira em
   *Realm settings → Email*, ou no JSON versionado (`infra/keycloak/portal-local-realm.json`).
   Local, o destino é o Mailpit em `mailpit:1025`, e a caixa fica em `localhost:8025`.
2. **Service account sem permissão.** 502 na resposta, com `keycloak.failed` no log: o client
   `portal-admin` precisa de `manage-users` **e** `view-users` do `realm-management`.
   `test_seed_matches_realm.py` cobra isso no build justamente porque a falta só aparece
   quando alguém tenta convidar.
3. **`redirect_uri` recusado.** O link do convite volta para `PORTAL_WEB_URL/login`, que
   precisa estar nos `redirectUris` do client `portal-web`.
4. **Link expirado.** `INVITATION_LIFESPAN_SECONDS` (24h por padrão). Reconvidar é idempotente:
   não cria conta nova nem duplica vínculo, só reenvia.

## Sintoma: conta bloqueada por `user_temporarily_disabled`

Aparece no log do Keycloak como `type="LOGIN_ERROR" ... error="user_temporarily_disabled"`, com
a senha certa. É o `bruteForceProtected` do realm. Ver o estado e limpar:

```bash
docker compose exec keycloak /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master --user admin --password admin_local_only
docker compose exec keycloak /opt/keycloak/bin/kcadm.sh \
  delete attack-detection/brute-force/users -r portal-local
```

**A pegadinha da configuração:** o realm é importado com `--import-realm`, cuja estratégia é
`IGNORE_EXISTING`, e ele vive no schema `keycloak` do Postgres. Editar
`infra/keycloak/portal-local-realm.json` **não altera uma stack que já subiu** — vale só para um
ambiente novo. Para aplicar no que existe, use `kcadm.sh update realms/portal-local -s <campo>=…`
ou derrube o schema e deixe reimportar.

## Sintoma: Keycloak fora do ar

Login novo para de funcionar; sessões já emitidas continuam válidas até expirar, e a API segue
respondendo enquanto o JWKS estiver em cache (`OIDC_JWKS_CACHE_SECONDS`). Verifique
`/health/ready` na porta de management (9000) antes de olhar a aplicação.

## Rotação de chaves do realm

`PyJWKClient` refaz o fetch ao ver um `kid` desconhecido, então a rotação não exige restart.
Se muitos `PyJWKClientError` aparecerem, confirme que a API alcança a URL do JWKS pela rede
interna e que o realm é o mesmo do `OIDC_ISSUER`.

## Restaurar um backup

Papéis são objetos de **cluster** e não vêm num `pg_dump` do banco. Rode
`infra/postgres/bootstrap/roles.sql` **antes** do restore, senão os grants e as policies
apontam para papéis inexistentes. Ver `docs/runbooks/backup-restore.md`.
