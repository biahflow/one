-- Papéis do One (ADR 0010) — fonte única, idempotente.
--
-- Motivo: o role `portal` é criado pelo entrypoint do Postgres a partir de
-- POSTGRES_USER e nasce SUPERUSER. Superusuário ignora Row-Level Security
-- incondicionalmente, e `FORCE ROW LEVEL SECURITY` não corrige isso (FORCE só
-- estende a RLS ao *dono* da tabela). A correção é não conectar como
-- superusuário no caminho de requisição — por isso os quatro papéis abaixo, um
-- por tipo de trabalho: migrar, servir requisição, sincronizar e administrar.
--
-- `portal` permanece superusuário de propósito: o Keycloak usa essa credencial
-- (KC_DB_USERNAME) e migra o próprio schema a cada upgrade de versão.
--
-- Uso:
--   psql -v ON_ERROR_STOP=1 \
--        -v app_password=... -v system_password=... -v migrator_password=... \
--        -v admin_password=... \
--        -f roles.sql
--
-- Rodado pelo serviço `db-bootstrap` do docker-compose a cada `up` (cobre tanto
-- volume novo quanto volume já existente) e como step do job api-quality no CI.

\set ON_ERROR_STOP on

-- 1. Extensões e schemas -----------------------------------------------------
-- As duas extensões ficam em `public` **explicitamente**. Sem o WITH SCHEMA
-- elas nascem no primeiro schema do search_path, e foi assim que o btree_gist
-- acabou dentro de `portal` (a migração 0010 o criou com o search_path já
-- fixado em `portal,public`) — o que faz um `DROP SCHEMA portal` do restore
-- falhar por dependência. Em `public` a extensão sobrevive ao schema.
--
-- O btree_gist estava só na migração 0010, e não aqui: um restore não roda
-- migrações, então o dump do schema `portal` chegava num banco sem a classe de
-- operadores do `EXCLUDE USING gist` de `project_financial_assumption` e
-- falhava. Extensão não entra em `pg_dump -n portal` — ela é objeto de banco,
-- não de schema, pela mesma razão que papel é objeto de cluster (ADR 0019).
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public;
CREATE SCHEMA IF NOT EXISTS portal;
CREATE SCHEMA IF NOT EXISTS keycloak;

-- 2. Papéis ------------------------------------------------------------------
-- O CREATE é condicional; o ALTER fica fora do IF para que rotacionar senha
-- seja idempotente.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'portal_migrator') THEN
    CREATE ROLE portal_migrator;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'portal_app') THEN
    CREATE ROLE portal_app;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'portal_system') THEN
    CREATE ROLE portal_system;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'portal_admin') THEN
    CREATE ROLE portal_admin;
  END IF;
END
$$;

-- Dono do schema e das tabelas; roda `alembic upgrade`. Isento de RLS por ser
-- dono (usamos ENABLE, não FORCE) — necessário para backfills em migrações.
ALTER ROLE portal_migrator
  WITH LOGIN NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD :'migrator_password';

-- Caminho de requisição da API e do worker. Sujeito à RLS.
-- O NOBYPASSRLS/NOSUPERUSER é reafirmado a cada execução de propósito: é o
-- invariante do qual toda a segurança de tenant depende.
ALTER ROLE portal_app
  WITH LOGIN NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD :'app_password';

-- Caminho de sistema: webhook do Biahflow, sync_biahflow_project e seed, que
-- criam organizações e projetos (isto é, *criam* o tenant) e portanto não podem
-- ser barrados pela RLS. Privilégio visível na credencial, auditável por
--   SELECT rolname FROM pg_roles WHERE rolbypassrls;
ALTER ROLE portal_system
  WITH LOGIN NOCREATEDB NOCREATEROLE BYPASSRLS
  PASSWORD :'system_password';

-- Caminho de administração de acesso: os endpoints /api/v1/admin, que convidam e
-- revogam membros (ADR 0011). É o único papel com escrita em `membership`, e
-- continua NOBYPASSRLS — o alcance vem de uma GUC publicada só depois de a
-- autorização ser verificada, não de um privilégio de escapar da RLS.
--
-- O motivo de ser uma credencial separada e não mais um GRANT no portal_app: com
-- o grant no caminho de requisição, qualquer bug em qualquer endpoint poderia
-- escrever controle de acesso, com só uma GUC no caminho. Sem o grant, não pode.
ALTER ROLE portal_admin
  WITH LOGIN NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD :'admin_password';

-- 2b. O NOSUPERUSER, reafirmado onde é possível reafirmá-lo -------------------
--
-- Ele saiu dos quatro ALTER acima e voltou aqui, sob guarda. **A intenção não
-- mudou** — mudou o que o Postgres deixa fazer: só superusuário pode alterar o
-- atributo de superusuário, **mesmo para reafirmá-lo com o valor que já está lá**.
-- Num Postgres gerenciado (Neon, Cloud SQL) não existe superusuário para o portal
-- usar, e sem esta guarda o bootstrap inteiro morria em `permission denied to
-- alter role` numa linha que não muda nada, já que `CREATE ROLE` nasce
-- `NOSUPERUSER`. Medido contra o Neon (PG 16.14): das sete cláusulas, **só esta**
-- é recusada — inclusive `BYPASSRLS`, que é a que carrega o desenho, passa.
--
-- Por que reafirmar ainda vale onde dá: é defesa contra deriva. Se alguém
-- promover `portal_app` a superusuário à mão, rodar o bootstrap desfaz. Onde não
-- há superusuário, ninguém pode promover ninguém, então a defesa é desnecessária
-- pelo mesmo motivo que é impossível.
--
-- O invariante continua guardado onde importa, e por teste e não por bootstrap:
-- `test_rls_isolation.py` afirma `rolsuper` e `rolbypassrls` do papel de
-- requisição, e o `restore.sh` os reafirma depois de restaurar.
DO $$
BEGIN
  IF (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    ALTER ROLE portal_migrator WITH NOSUPERUSER;
    ALTER ROLE portal_app      WITH NOSUPERUSER;
    ALTER ROLE portal_system   WITH NOSUPERUSER;
    ALTER ROLE portal_admin    WITH NOSUPERUSER;
  ELSE
    RAISE NOTICE
      'NOSUPERUSER não reafirmado: % não é superusuário. Esperado em Postgres gerenciado — nenhum papel pode ser promovido lá.',
      current_user;
  END IF;
END
$$;

-- 3. Posse do schema e das tabelas já existentes ------------------------------
-- Em volume novo o loop não encontra nada e as tabelas nascem do migrator. Em
-- volume já existente (tabelas criadas por `portal` antes desta mudança) é este
-- loop que transfere a posse — sem ele, `ALTER TABLE ... ENABLE ROW LEVEL
-- SECURITY` na migração 0007 falharia por falta de permissão.

-- Dar a posse exige **poder virar** o dono. Desde o PG 16, transferir um objeto
-- para um papel requer que quem transfere seja membro dele com a opção SET — e
-- num Postgres gerenciado o papel do bootstrap não é superusuário, então não
-- ganha isso de graça. Sem esta linha, o script morre em `must be able to SET
-- ROLE "portal_migrator"` logo abaixo (medido no Neon, PG 16.14).
--
-- Não afrouxa nada: quem roda este script já é o papel mais privilegiado do
-- banco e poderia conceder a si mesmo de qualquer forma. E é só o `portal_migrator`
-- — o `portal_system`, que é o do BYPASSRLS, não entra.
DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    EXECUTE format('GRANT portal_migrator TO %I', current_user);
  END IF;
END
$$;

ALTER SCHEMA portal OWNER TO portal_migrator;

-- O env.py do Alembic emite `CREATE SCHEMA IF NOT EXISTS portal` para cobrir
-- ambientes que pulam este bootstrap. O Postgres checa o privilégio antes do
-- IF NOT EXISTS, então o dono do schema precisa de CREATE no banco.
DO $$
BEGIN
  EXECUTE format('GRANT CREATE ON DATABASE %I TO portal_migrator', current_database());
END
$$;

DO $$
DECLARE
  r record;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'portal' LOOP
    EXECUTE format('ALTER TABLE portal.%I OWNER TO portal_migrator', r.tablename);
  END LOOP;

  FOR r IN
    SELECT t.typname
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'portal' AND t.typtype = 'e'
  LOOP
    EXECUTE format('ALTER TYPE portal.%I OWNER TO portal_migrator', r.typname);
  END LOOP;
END
$$;

-- 4. Acesso ao schema ---------------------------------------------------------
GRANT USAGE ON SCHEMA portal TO portal_app, portal_system, portal_admin;
-- A extensão `vector` vive em public; a recuperação da Fase 4 precisará do tipo.
GRANT USAGE ON SCHEMA public TO portal_app, portal_system, portal_admin;

-- 5. Privilégios do caminho de sistema nas tabelas já existentes --------------
-- O portal_system tem BYPASSRLS e é o caminho de sistema (webhook, worker,
-- seed): CRUD amplo é o desenho, não uma frouxidão. Os privilégios do
-- portal_app são restritos e concedidos tabela a tabela na migração 0007,
-- junto das policies a que correspondem.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA portal TO portal_system;

-- 6. Privilégios padrão para tabelas futuras ----------------------------------
-- Sem isto, cada migração futura precisaria lembrar de conceder acesso. O
-- padrão do `portal_app` é SELECT: o portal é read-only sobre o read-model do
-- Biahflow (ADR 0006/0008), e as poucas exceções de escrita são concedidas
-- explicitamente, tabela a tabela, na migração 0007.
ALTER DEFAULT PRIVILEGES FOR ROLE portal_migrator IN SCHEMA portal
  GRANT SELECT ON TABLES TO portal_app;
ALTER DEFAULT PRIVILEGES FOR ROLE portal_migrator IN SCHEMA portal
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO portal_system;
-- O portal_admin também nasce só com leitura: as escritas dele são poucas e
-- concedidas tabela a tabela na migração 0008, junto das policies correspondentes.
ALTER DEFAULT PRIVILEGES FOR ROLE portal_migrator IN SCHEMA portal
  GRANT SELECT ON TABLES TO portal_admin;

-- 7. Relatório ----------------------------------------------------------------
\echo 'Papéis do One:'
SELECT rolname, rolsuper, rolbypassrls, rolcanlogin
FROM pg_roles
WHERE rolname IN ('portal', 'portal_migrator', 'portal_app', 'portal_system', 'portal_admin')
ORDER BY rolname;
