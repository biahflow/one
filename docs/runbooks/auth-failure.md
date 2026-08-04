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
