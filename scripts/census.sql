-- Censo de linhas do schema `portal` — o verificador do backup (ADR 0019).
--
-- Roda com `psql -At -f census.sql` e devolve uma linha de JSON: tabela → nº de
-- linhas. `backup.sh` o guarda no manifesto; `restore.sh` o refaz contra o banco
-- restaurado e compara.
--
-- **Ele tem de rodar com credencial diferente da do dump.** O dump sai sob
-- portal_migrator (dono, isento da RLS); o censo sai sob portal_system
-- (BYPASSRLS). Se os dois usassem a mesma, errariam na mesma direção: um dump
-- tirado com a credencial errada volta vazio, o censo tirado com ela volta zero,
-- e o manifesto confirmaria com entusiasmo que zero linhas viraram zero linhas.
--
-- A lista de tabelas vem do catálogo e não de uma lista escrita à mão, senão
-- toda migração futura precisaria lembrar de vir aqui — e a que esquecesse
-- criaria uma tabela que o backup não confere.
SELECT coalesce(jsonb_object_agg(t, n)::text, '{}')
FROM (
  SELECT
    c.relname AS t,
    (xpath(
      '/row/cnt/text()',
      query_to_xml(
        format('SELECT count(*) AS cnt FROM portal.%I', c.relname),
        false, true, ''
      )
    ))[1]::text::bigint AS n
  FROM pg_class c
  JOIN pg_namespace ns ON ns.oid = c.relnamespace
  WHERE ns.nspname = 'portal'
    AND c.relkind = 'r'
) s;
