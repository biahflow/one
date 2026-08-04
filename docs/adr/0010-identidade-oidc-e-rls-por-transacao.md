# ADR 0010 — Identidade OIDC e Row-Level Security por transação

**Status:** Aceito — 04/08/2026

## Contexto

A ADR 0002 promete RLS como **segunda barreira** de isolamento e a ADR 0003 diz que "a API
valida token e associações de projeto". Nenhuma das duas tinha implementação:

- A identidade era um e-mail em header (`X-Portal-User`), preenchido pelo BFF a partir de uma
  variável de ambiente. Qualquer requisição direta à API se passava por qualquer usuário
  trocando um header.
- O isolamento existia só na camada de aplicação (`TenantScopedRepository`). Todo `select()`
  cru escapava — e `biahflow.build_dashboard`, que projeta o dashboard inteiro, é exatamente
  isso.
- O papel `portal` do Postgres, usado pela API, é **superusuário** (o entrypoint da imagem o
  cria assim). Superusuário ignora RLS incondicionalmente, então habilitar policies naquele
  desenho seria um no-op silencioso: as policies existiriam, os testes passariam, e nada seria
  aplicado.
- Os três papéis (`internal_admin`, `internal_member`, `client_member`) existiam no enum e no
  realm, mas nenhum endpoint checava papel — só a existência de uma membership.

## Decisão

### 1. Quatro papéis no Postgres, em vez de `FORCE ROW LEVEL SECURITY`

| Papel | Para quê | RLS |
|---|---|---|
| `portal` | superusuário de bootstrap e credencial do **Keycloak**, que migra o próprio schema | bypass, irrelevante |
| `portal_migrator` | dono do schema e das tabelas; roda `alembic upgrade` | isento por ser dono |
| `portal_app` | API e worker no caminho de requisição | **sujeito** |
| `portal_system` | webhook do Biahflow, sync e seed — os caminhos que *criam* o tenant | `BYPASSRLS` explícito |

`FORCE` **não** foi usado, e a razão importa: `FORCE` só estende a RLS ao *dono* da tabela; o
bypass de superusuário é anterior a qualquer policy e não seria corrigido por ele. A correção
real é **não conectar como superusuário**. Além disso, com `FORCE` o `portal_migrator` deixaria
de enxergar linhas em backfills de migrações futuras — um `UPDATE` de migração passaria a
afetar zero linhas em silêncio, o pior modo de falha disponível.

`BYPASSRLS` fica na **credencial**, não numa GUC de escape, para que o privilégio seja
auditável por `SELECT rolname FROM pg_roles WHERE rolbypassrls` em vez de por leitura de código.

`infra/postgres/bootstrap/roles.sql` é a fonte única e idempotente, com dois chamadores:
`init/002-roles.sh` (volume novo) e o serviço one-shot `db-bootstrap` do compose (volume já
existente, roda a cada `up`).

### 2. Contexto de tenant por transação, em GUCs em cascata

`get_session(principal, *, role)` publica o contexto com `set_config(..., true)` — transacional,
que o Postgres reverte no fim da transação. Um `SET` sem `LOCAL` vazaria para a próxima
requisição que reusasse a conexão do pool.

| Estágio | GUC | Origem | Destranca |
|---|---|---|---|
| 1 | `portal.subject` | claim `sub` verificado | a linha do próprio usuário em `user` |
| 1 | `portal.email` | claim `email` (com `email_verified`) | o *link* de uma linha semeada sem `external_subject` |
| 1 | `portal.user_id` | `user.id` resolvido | `membership` → `organization` e `project` |
| 2 | `portal.organization_id` | do projeto autorizado | as 10 tabelas project-scoped |
| 2 | `portal.project_id` | do projeto autorizado | idem |

O parâmetro é **explícito** em `get_session`, e não um listener de `begin` sobre a engine: o
webhook e o worker precisam de contexto diferente na mesma engine, um controle de segurança
implícito é invisível na revisão, e o `db_session` dos testes cria a Session sobre uma conexão
já em transação — um listener não dispararia e o teste passaria por engano.

`bind_tenant` é **monotônico**: rebindar uma transação para outro tenant levanta `RuntimeError`,
porque isso só acontece por sessão reusada, que é precisamente o bug que a RLS existe para
impedir.

### 3. Policies fail-closed (`0007_rls_tenant_context`)

`current_setting('portal.x', true)` devolve NULL quando a GUC nunca foi setada; o predicado
então não é TRUE e a linha é filtrada. **Contexto ausente devolve zero linhas, nunca tudo.**

- **10 tabelas project-scoped** — comparação de coluna pura (`organization_id` e `project_id`),
  sem subquery: é para isto que o `TenantMixin` denormaliza as chaves. Escrita só onde há caso
  de uso: `pending_item` recebe `FOR INSERT`, porque o chat abre pendência (ADR 0007). As demais
  **não recebem policy de escrita**, o que materializa no banco a regra de que o portal é
  read-only sobre o Biahflow (ADR 0006/0008).
- **`project`** não pode usar a GUC de organização, porque é lido *antes* de a organização ser
  conhecida. A policy espelha em SQL o `roles_for_project`: membership direta ou org-wide.
- **`membership`** usa só GUC, sem subquery — é isso que impede recursão, já que `project` e
  `organization` fazem subquery nela.
- **`user`** tem três ramos (ler a própria linha, inserir a linha do próprio `sub`, reivindicar
  uma linha semeada sem dono), o que permite provisionar no primeiro login sem papel
  privilegiado.
- **`audit_log`** é append-only para a aplicação: policy de `INSERT` e **nenhuma de `SELECT`**.

A matriz de `GRANT` é mantida igualmente estreita. RLS e privilégio são portões independentes:
uma policy frouxa é barrada pelo grant, um grant largo é barrado pela policy.

### 4. Identidade: Auth.js v5 no BFF, PyJWT como resource server

O BFF (Next.js) faz o Authorization Code + PKCE com client **confidencial**, guarda os tokens
no cookie cifrado e manda `Authorization: Bearer` server-to-server. A API **nunca** faz code
exchange: valida assinatura, `iss`, `aud`, `exp` e `email_verified` com `jwt.PyJWKClient`
(cache de JWKS e refresh por `kid` desconhecido embutidos). `python-jose` foi descartada
(CVEs e manutenção irregular) e `authlib` também (é cliente OIDC completo, que a API não é).

`issuer` e `jwks_url` são settings separadas de propósito: o navegador fala com o Keycloak em
`localhost:8080` — e é esse valor que vem no `iss` —, mas o container da API só o alcança por
`keycloak:8080`.

### 5. A `membership` é a autoridade; o realm role é indício

Um realm role não sabe *em qual projeto*. Ele só define `is_internal` no provisionamento do
usuário. A autorização continua vindo da `membership`, como a ADR 0002 estabelece.

## Consequências

- **O 404 passa a ser preservado pelo próprio banco.** `session.get(Project, ...)` devolve
  `None` para um não-membro por RLS, e `access.py` já traduz `None` em 404 — a política "404,
  nunca 403" deixa de depender da disciplina do chamador.
- **`build_dashboard` não muda uma linha** e passa a ser filtrado por baixo. É a demonstração
  mais limpa de que a barreira funciona onde a camada de aplicação não chega.
- **Contexto esquecido vira 404 geral, não vazamento.** É o modo de falha mais provável desta
  fase e está documentado em `docs/runbooks/auth-failure.md`; `bind_tenant` é chamado dentro de
  `access.scoped_project`/`default_project` para que nenhum endpoint precise lembrar dele.
- **Um usuário do realm sem `membership` autentica e não autoriza nada** — 404 em todo endpoint
  e estado vazio na UI. Autenticação não é autorização; é por isso que o fluxo de convite é
  trabalho separado.
- **Toda tabela nova com `organization_id` precisa nascer com policy.** Um meta-teste em
  `test_rls_isolation.py` varre `pg_class`/`pg_policies` e quebra o CI sozinho se alguém
  esquecer — inclusive nas tabelas de conhecimento da Fase 4.
- **Papéis são objetos de cluster e não entram num `pg_dump` do banco.** Restaurar um backup
  exige rodar `roles.sql` antes, senão grants e policies apontam para papéis inexistentes.
- **Auditoria de identidade tem limite:** `audit_log.organization_id` é NOT NULL, e no primeiro
  login ainda não há organização. `identity.provisioned` e `identity.linked` vão para log
  estruturado; a auditoria em tabela começa quando a organização é conhecida.
- Supera a ADR 0003, que descrevia a intenção sem desenho. A ADR 0002 permanece válida e passa
  a ter a segunda barreira que ela prometia.
