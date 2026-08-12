#!/usr/bin/env bash
#
# Restore do Portal Labs (Fase 5, ADR 0019).
#
#   ./scripts/restore.sh <dir-do-backup> --database NOME [--with-objects]
#
# A ordem não é preferência, é dependência:
#
#   1. cria o banco alvo;
#   2. roda `infra/postgres/bootstrap/roles.sql` — papéis são objetos de
#      *cluster* e extensões são objetos de *banco*, e nem uns nem outras entram
#      num `pg_dump -n portal`. Sem este passo o restore falha em
#      `public.vector` e no `EXCLUDE USING gist` de project_financial_assumption;
#   3. `pg_restore --clean --if-exists --exit-on-error`, que traz tabelas, dados,
#      policies e GRANTs (inclusive os de coluna);
#   4. confere o censo do manifesto contra o banco restaurado, com credencial
#      diferente da que tirou o dump;
#   5. afirma que portal_app continua sem SUPERUSER e sem BYPASSRLS. É a
#      verificação de uma linha que o runbook sempre prescreveu, agora como
#      código de saída;
#   6. lista os expurgos da ADR 0017 que este backup desfaz.
#
# ATENÇÃO: o passo 2 escreve papéis, que são do **cluster** inteiro — restaurar
# num banco descartável do cluster de produção redefine a senha dos quatro
# papéis nele. Restaure noutro cluster, ou passe as senhas em vigor.
#
# Num Postgres gerenciado a unidade não é o cluster (ADR 0044, ADR 0048). No Neon
# os papéis pertencem ao **branch**, e cada branch tem os seus: `--database ensaio`
# no mesmo branch redefine as senhas em vigor exatamente como o aviso acima
# descreve, e **criar um branch é a saída barata** — ele nasce com os papéis
# copiados e sai de graça.
#
# Duas variáveis existem para esse alvo, e as duas têm default que preserva o
# comportamento do compose:
#
#   RESTORE_ADMIN_URL       — a DSN administrativa inteira. Sem ela, é montada a
#                             partir de DATABASE_MIGRATION_URL trocando usuário e
#                             senha por POSTGRES_USER/POSTGRES_PASSWORD. Num
#                             gerenciado isso não alcança o alvo: o papel de maior
#                             privilégio **e o endpoint** mudam por branch.
#   POSTGRES_MAINTENANCE_DB — o banco de onde se emite `CREATE DATABASE`
#                             (padrão `postgres`; no Neon costuma ser `neondb`).

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

SOURCE=""
TARGET_DB=""
WITH_OBJECTS=0
ALLOW_PLAINTEXT=1  # o restore não cifra nada; a variável existe para o lib.sh

while [ $# -gt 0 ]; do
  case "$1" in
    --database) TARGET_DB="$2"; shift 2 ;;
    --with-objects) WITH_OBJECTS=1; shift ;;
    # O intervalo é **derivado**, e não `sed -n '2,26p'` como era: com o número
    # escrito à mão, crescer o cabeçalho truncava a ajuda em silêncio — e foi o que
    # aconteceu ao documentar o alvo gerenciado. Imprime da linha 2 até a primeira
    # linha que não é comentário. `test_backup_restore.py` afirma que a última linha
    # do cabeçalho aparece na saída.
    -h|--help) awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"; exit 0 ;;
    -*) die "argumento desconhecido: $1" ;;
    *) SOURCE="$1"; shift ;;
  esac
done

[ -n "$SOURCE" ] || die "informe o diretório do backup"
[ -d "$SOURCE" ] || die "não é um diretório: $SOURCE"
[ -n "$TARGET_DB" ] || die "informe --database NOME (nunca o banco em uso, por padrão)"

load_env

: "${DATABASE_MIGRATION_URL:?DATABASE_MIGRATION_URL não definido}"
: "${DATABASE_SYSTEM_URL:?DATABASE_SYSTEM_URL não definido}"

# `POSTGRES_USER`/`POSTGRES_PASSWORD` só são exigidos quando a DSN administrativa
# **não** foi dada inteira: com `RESTORE_ADMIN_URL` elas não descrevem nada, e
# cobrá-las obrigaria a inventar um valor para passar pelo `:?` — que é o modo de
# falha que o `preflight` existe para impedir, um nível acima.
if [ -z "${RESTORE_ADMIN_URL:-}" ]; then
  : "${POSTGRES_USER:?POSTGRES_USER não definido (ou passe RESTORE_ADMIN_URL, ver --help)}"
  : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD não definido (ou passe RESTORE_ADMIN_URL, ver --help)}"
fi
MAINTENANCE_DB="${POSTGRES_MAINTENANCE_DB:-postgres}"

require_cmd "$PSQL" "\`$PSQL\` não encontrado; ver PSQL no runbook"
require_cmd "$PG_RESTORE" "\`$PG_RESTORE\` não encontrado; ver PG_RESTORE no runbook"

# 0. Decifra numa área temporária ---------------------------------------------
# O diretório do backup nunca é escrito: um restore que altera o backup é um
# restore que não se pode tentar duas vezes.
# O template é explícito porque o `mktemp` do BSD (macOS) ignora TMPDIR quando
# não recebe um — e o restore precisa poder escrever onde quem o chama mandou.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/portal-restore.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
# `if` e não `[ … ] && cp`: sob `set -e`, uma lista `&&` cujo teste falha devolve
# 1 e derruba o script — e aqui o teste falha o tempo todo, porque cada arquivo
# existe ou em claro ou cifrado, nunca dos dois jeitos.
for file in manifest.json dump.pgc objects.tar; do
  if [ -f "$SOURCE/$file" ]; then cp "$SOURCE/$file" "$WORK/"; fi
  if [ -f "$SOURCE/$file.age" ]; then cp "$SOURCE/$file.age" "$WORK/"; fi
done
decrypt_file "$WORK/manifest.json"
decrypt_file "$WORK/dump.pgc"
if [ "$WITH_OBJECTS" = "1" ]; then decrypt_file "$WORK/objects.tar"; fi

TAKEN_AT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["taken_at"])' "$WORK/manifest.json")"
log "backup de $TAKEN_AT"

# Integridade antes de tocar em qualquer banco.
WORK="$WORK" WITH_OBJECTS="$WITH_OBJECTS" python3 - <<'PY' || die "digest do backup não confere"
import hashlib, json, os, pathlib, sys

work = pathlib.Path(os.environ["WORK"])
manifest = json.loads((work / "manifest.json").read_text())
targets = [("dump.pgc", "dump_sha256")]
if os.environ["WITH_OBJECTS"] == "1":
    targets.append(("objects.tar", "objects_sha256"))
for name, field in targets:
    actual = hashlib.sha256((work / name).read_bytes()).hexdigest()
    if actual != manifest[field]:
        sys.exit(f"{name}: esperado {manifest[field]}, obtido {actual}")
print("digests conferem")
PY

# 1. O banco alvo --------------------------------------------------------------
# A DSN administrativa. Dada inteira em `RESTORE_ADMIN_URL`, é usada como está (só o
# banco é trocado); ausente, é montada a partir da do migrator trocando usuário e
# senha, que é o que o compose sempre fez. **A diferença importa num gerenciado**: lá
# o papel de maior privilégio e o *endpoint* mudam por branch, de modo que trocar
# duas peças sobre a URL do migrator não descreve o alvo (ADR 0048).
if [ -n "${RESTORE_ADMIN_URL:-}" ]; then
  SUPERUSER_URL="$(swap_url "$(libpq_url "$RESTORE_ADMIN_URL")" --db "$MAINTENANCE_DB")"
else
  SUPERUSER_URL="$(swap_url "$(libpq_url "$DATABASE_MIGRATION_URL")" \
    --user "$POSTGRES_USER" --password "$POSTGRES_PASSWORD" --db "$MAINTENANCE_DB")"
fi
TARGET_SUPER_URL="$(swap_url "$SUPERUSER_URL" --db "$TARGET_DB")"
TARGET_SYSTEM_URL="$(swap_url "$(libpq_url "$DATABASE_SYSTEM_URL")" --db "$TARGET_DB")"

log "criando o banco $TARGET_DB em $(redacted_url "$SUPERUSER_URL")"
if [ -z "$("$PSQL" "$SUPERUSER_URL" -At -c \
      "SELECT 1 FROM pg_database WHERE datname = '$TARGET_DB'")" ]; then
  "$PSQL" "$SUPERUSER_URL" -q -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$TARGET_DB\""
else
  log "  $TARGET_DB já existe; o --clean do pg_restore substitui o conteúdo"
fi

# 2. Papéis e extensões --------------------------------------------------------
log "roles.sql (papéis do cluster + extensões do banco) em $TARGET_DB"
"$PSQL" "$TARGET_SUPER_URL" -q -v ON_ERROR_STOP=1 \
  -v app_password="${POSTGRES_APP_PASSWORD:?POSTGRES_APP_PASSWORD não definido}" \
  -v system_password="${POSTGRES_SYSTEM_PASSWORD:?POSTGRES_SYSTEM_PASSWORD não definido}" \
  -v migrator_password="${POSTGRES_MIGRATOR_PASSWORD:?POSTGRES_MIGRATOR_PASSWORD não definido}" \
  -v admin_password="${POSTGRES_ADMIN_PASSWORD:?POSTGRES_ADMIN_PASSWORD não definido}" \
  -f "$REPO_ROOT/infra/postgres/bootstrap/roles.sql" >/dev/null

# 2b. A associação de que o passo 3 depende, e que ninguém tinha escrito ----------
# O dump traz `ALTER ... OWNER TO portal_migrator` e ACLs, e desde o PG 16 transferir
# posse exige **ser membro** do papel de destino. Num superusuário isso é gratuito;
# fora dele, quem concede é o próprio `roles.sql` acima (`GRANT portal_migrator TO
# current_user`, no ramo de não-superusuário da ADR 0044). É uma dependência de
# ordem entre os passos 2 e 3 que nenhum comentário registrava — e cuja falha aparece
# no meio do `pg_restore`, como erro de posse de um objeto, longe da causa.
log "conferindo a associação a portal_migrator"
if [ "$("$PSQL" "$TARGET_SUPER_URL" -At -v ON_ERROR_STOP=1 \
      -c "SELECT pg_has_role(current_user, 'portal_migrator', 'MEMBER')")" != "t" ]; then
  die "quem roda o restore não é membro de portal_migrator, e o --clean do passo 3 vai falhar ao derrubar objetos dele. O roles.sql concede essa associação quando não é superusuário (ADR 0044); se ela não está aqui, o passo 2 rodou com outra credencial."
fi

# 3. O dump --------------------------------------------------------------------
log "pg_restore em $TARGET_DB"
"$PG_RESTORE" --dbname="$TARGET_SUPER_URL" --clean --if-exists --exit-on-error "$WORK/dump.pgc"

# 4. O censo, sob credencial diferente da do dump -------------------------------
log "conferindo o censo (portal_system)"
RESTORED_CENSUS="$("$PSQL" "$TARGET_SYSTEM_URL" -At -v ON_ERROR_STOP=1 -f "$SCRIPT_DIR/census.sql")"
MANIFEST="$WORK/manifest.json" RESTORED="$RESTORED_CENSUS" python3 - <<'PY' \
  || die "o censo do banco restaurado não bate com o manifesto"
import json, os, sys

expected = json.loads(open(os.environ["MANIFEST"]).read())["census"]
actual = json.loads(os.environ["RESTORED"])
diff = {
    table: (expected.get(table), actual.get(table))
    for table in set(expected) | set(actual)
    if expected.get(table) != actual.get(table)
}
if diff:
    for table, (want, got) in sorted(diff.items()):
        print(f"  {table}: manifesto={want} restaurado={got}", file=sys.stderr)
    sys.exit(1)
print(f"censo confere: {len(expected)} tabelas, {sum(expected.values())} linhas")
PY

# 5. A verificação de uma linha ------------------------------------------------
# Um restore que devolve os dados mas perde a RLS devolve um portal em que todo
# cliente vê todo projeto — e nada nele parece quebrado (ADR 0010).
log "verificando os papéis e as policies"
CHECKS="$("$PSQL" "$TARGET_SUPER_URL" -At -v ON_ERROR_STOP=1 <<'SQL'
SELECT 'portal_app.rolsuper', rolsuper::text FROM pg_roles WHERE rolname = 'portal_app'
UNION ALL
SELECT 'portal_app.rolbypassrls', rolbypassrls::text FROM pg_roles WHERE rolname = 'portal_app'
UNION ALL
SELECT 'policies', count(*)::text FROM pg_policies WHERE schemaname = 'portal'
UNION ALL
SELECT 'tabelas_com_rls', count(*)::text FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'portal' AND c.relkind = 'r' AND c.relrowsecurity
SQL
)"
# Aqui e não num pipe: `die` dentro de `cmd | while` roda numa subshell, e o
# `exit` dela não é o do script.
while IFS='|' read -r label value; do
  [ -n "$label" ] || continue
  case "$label" in
    portal_app.rolsuper|portal_app.rolbypassrls)
      # `false`, e não `f`: o `::text` de um booleano no Postgres é a palavra
      # inteira — o `t`/`f` é formatação do psql, que o `-At` já dispensou.
      [ "$value" = "false" ] || die "$label = $value — a RLS voltaria como decoração"
      ;;
    policies|tabelas_com_rls)
      [ "${value:-0}" -gt 0 ] || die "$label = $value no banco restaurado"
      ;;
  esac
  log "  $label = $value"
done <<< "$CHECKS"

# 6. Os objetos ----------------------------------------------------------------
if [ "$WITH_OBJECTS" = "1" ]; then
  log "devolvendo os objetos ao storage"
  (cd "$REPO_ROOT" && PYTHONPATH="apps/api/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -m portal_api.backup restore "$WORK/objects.tar")
else
  log "objetos NÃO restaurados (--with-objects para incluí-los)"
fi

# 7. O que este restore desfaz -------------------------------------------------
# A linha do pedido sobrevive ao próprio expurgo (ADR 0017) e é o que permite
# saber, depois de um restore, quais organizações voltaram do apagamento.
log "expurgos concluídos depois de $TAKEN_AT (precisam ser reexecutados):"
# Pela entrada padrão, e não por `-c`: o psql só substitui `:'var'` no script,
# nunca no argumento de `-c`.
ERASURES="$("$PSQL" "$TARGET_SYSTEM_URL" -At -v ON_ERROR_STOP=1 -v taken_at="$TAKEN_AT" <<'SQL'
SELECT organization_id || ' concluído em ' || completed_at
  FROM portal.data_erasure_request
 WHERE state = 'completed' AND completed_at > :'taken_at'::timestamptz
 ORDER BY completed_at;
SQL
)"
if [ -n "$ERASURES" ]; then
  printf '  %s\n' $ERASURES >&2
else
  log "  nenhum"
fi

log "restore concluído em $TARGET_DB"
