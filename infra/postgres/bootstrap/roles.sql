-- Papéis do Portal Labs (ADR 0010) — fonte única, idempotente.
--
-- Motivo: o role `portal` é criado pelo entrypoint do Postgres a partir de
-- POSTGRES_USER e nasce SUPERUSER. Superusuário ignora Row-Level Security
-- incondicionalmente, e `FORCE ROW LEVEL SECURITY` não corrige isso (FORCE só
-- estende a RLS ao *dono* da tabela). A correção é não conectar como
-- superusuário no caminho de requisição — por isso os três papéis abaixo.
--
-- `portal` permanece superusuário de propósito: o Keycloak usa essa credencial
-- (KC_DB_USERNAME) e migra o próprio schema a cada upgrade de versão.
--
-- Uso:
--   psql -v ON_ERROR_STOP=1 \
--        -v app_password=... -v system_password=... -v migrator_password=... \
--        -f roles.sql
--
-- Rodado pelo serviço `db-bootstrap` do docker-compose a cada `up` (cobre tanto
-- volume novo quanto volume já existente) e como step do job api-quality no CI.

\set ON_ERROR_STOP on

-- 1. Extensões e schemas -----------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;
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
END
$$;

-- Dono do schema e das tabelas; roda `alembic upgrade`. Isento de RLS por ser
-- dono (usamos ENABLE, não FORCE) — necessário para backfills em migrações.
ALTER ROLE portal_migrator
  WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD :'migrator_password';

-- Caminho de requisição da API e do worker. Sujeito à RLS.
-- O NOBYPASSRLS/NOSUPERUSER é reafirmado a cada execução de propósito: é o
-- invariante do qual toda a segurança de tenant depende.
ALTER ROLE portal_app
  WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD :'app_password';

-- Caminho de sistema: webhook do Biahflow, sync_biahflow_project e seed, que
-- criam organizações e projetos (isto é, *criam* o tenant) e portanto não podem
-- ser barrados pela RLS. Privilégio visível na credencial, auditável por
--   SELECT rolname FROM pg_roles WHERE rolbypassrls;
ALTER ROLE portal_system
  WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS
  PASSWORD :'system_password';

-- 3. Posse do schema e das tabelas já existentes ------------------------------
-- Em volume novo o loop não encontra nada e as tabelas nascem do migrator. Em
-- volume já existente (tabelas criadas por `portal` antes desta mudança) é este
-- loop que transfere a posse — sem ele, `ALTER TABLE ... ENABLE ROW LEVEL
-- SECURITY` na migração 0007 falharia por falta de permissão.

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
GRANT USAGE ON SCHEMA portal TO portal_app, portal_system;
-- A extensão `vector` vive em public; a recuperação da Fase 4 precisará do tipo.
GRANT USAGE ON SCHEMA public TO portal_app, portal_system;

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

-- 7. Relatório ----------------------------------------------------------------
\echo 'Papéis do Portal Labs:'
SELECT rolname, rolsuper, rolbypassrls, rolcanlogin
FROM pg_roles
WHERE rolname IN ('portal', 'portal_migrator', 'portal_app', 'portal_system')
ORDER BY rolname;
