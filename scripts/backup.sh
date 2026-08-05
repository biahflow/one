#!/usr/bin/env bash
#
# Backup do Portal Labs — Postgres e objetos do storage (Fase 5, ADR 0019).
#
#   ./scripts/backup.sh [--out DIR] [--prefix org/<uuid>/] [--allow-plaintext]
#
# Produz `$BACKUP_DIR/<timestamp>/` com três arquivos cifrados por `age`:
#
#   manifest.json.age   censo de linhas por tabela + o instante do backup
#   dump.pgc.age        pg_dump -Fc do schema `portal`
#   objects.tar.age     os objetos do bucket, com SHA-256 de cada um
#
# O que este script **não** guarda, e o runbook explica por quê: o material de
# chave (AGENT_KEY_PEPPER, DRIVE_TOKEN_ENCRYPTION_KEY) e o realm do Keycloak.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

OUT_DIR=""
PREFIX=""
ALLOW_PLAINTEXT=0

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT_DIR="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --allow-plaintext) ALLOW_PLAINTEXT=1; shift ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "argumento desconhecido: $1" ;;
  esac
done

load_env

: "${DATABASE_MIGRATION_URL:?DATABASE_MIGRATION_URL não definido}"
: "${DATABASE_SYSTEM_URL:?DATABASE_SYSTEM_URL não definido}"

if [ "$ALLOW_PLAINTEXT" = "1" ]; then
  log "AVISO: --allow-plaintext — este backup NÃO será cifrado"
else
  [ -n "${BACKUP_AGE_RECIPIENT:-}" ] || die \
    "BACKUP_AGE_RECIPIENT não definido. Um backup sem cifra pode ser uma
     escolha, nunca um efeito colateral: passe --allow-plaintext para dizer que
     é escolha, ou defina a chave. Ver docs/runbooks/backup-restore.md."
  require_cmd age "instale o \`age\` (brew install age / apt install age)"
fi

require_cmd "$PG_DUMP" "\`$PG_DUMP\` não encontrado; ver PG_DUMP no runbook"
require_cmd "$PSQL" "\`$PSQL\` não encontrado; ver PSQL no runbook"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${OUT_DIR:-${BACKUP_DIR:-$REPO_ROOT/backups}/$STAMP}"
mkdir -p "$DEST"

MIGRATION_URL="$(libpq_url "$DATABASE_MIGRATION_URL")"
SYSTEM_URL="$(libpq_url "$DATABASE_SYSTEM_URL")"

# 1. O censo, sob portal_system (BYPASSRLS) --------------------------------
# Antes do dump de propósito: se o banco não responde, o backup falha aqui e não
# depois de escrever um arquivo pela metade.
log "censo (portal_system) em $(redacted_url "$SYSTEM_URL")"
CENSUS="$("$PSQL" "$SYSTEM_URL" -At -v ON_ERROR_STOP=1 -f "$SCRIPT_DIR/census.sql")"
[ -n "$CENSUS" ] || die "o censo voltou vazio"

TOTAL_ROWS="$(printf '%s' "$CENSUS" | python3 -c 'import json,sys; print(sum(json.load(sys.stdin).values()))')"
[ "$TOTAL_ROWS" -gt 0 ] || die \
  "o censo soma zero linhas. Ou o banco está vazio, ou a credencial não
   enxerga o que existe — e um backup vazio não é um backup."

# 2. O dump, sob portal_migrator (dono do schema) ---------------------------
# Não é portal_app: o Postgres recusa (`query would be affected by row-level
# security policy`) e, com --enable-row-security para calar a recusa, devolve um
# dump limpo, bem-sucedido e vazio. É o desastre que este script existe para
# impedir, e `test_backup_restore.py` o executa.
log "pg_dump do schema portal (portal_migrator)"
"$PG_DUMP" "$MIGRATION_URL" --schema=portal --format=custom --file="$DEST/dump.pgc"

# 3. Os objetos do storage ---------------------------------------------------
log "objetos do storage${PREFIX:+ sob $PREFIX}"
OBJECTS_SUMMARY="$(
  cd "$REPO_ROOT" && PYTHONPATH="apps/api/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -m portal_api.backup dump "$DEST/objects.tar" --prefix "$PREFIX"
)"

# 4. O manifesto -------------------------------------------------------------
CENSUS="$CENSUS" STAMP="$STAMP" PREFIX="$PREFIX" \
SUMMARY="$OBJECTS_SUMMARY" DEST="$DEST" python3 - <<'PY'
import hashlib, json, os, pathlib
from datetime import datetime, timezone

dest = pathlib.Path(os.environ["DEST"])
summary = dict(part.split("=", 1) for part in os.environ["SUMMARY"].split())

manifest = {
    "format_version": 1,
    # ISO-8601 e não o carimbo compacto do diretório: quem lê isto é o SQL que
    # lista os expurgos posteriores ao backup, no fim de `restore.sh`.
    "taken_at": datetime.strptime(os.environ["STAMP"], "%Y%m%dT%H%M%SZ")
    .replace(tzinfo=timezone.utc)
    .isoformat(),
    "prefix": os.environ["PREFIX"],
    "census": json.loads(os.environ["CENSUS"]),
    "objects": {k: int(v) for k, v in summary.items()},
    # O digest do dump é o que separa "o arquivo chegou inteiro" de "o arquivo
    # chegou". A cifra do `age` já autentica, mas o manifesto também vale para
    # quem restaurou --allow-plaintext.
    "dump_sha256": hashlib.sha256((dest / "dump.pgc").read_bytes()).hexdigest(),
    "objects_sha256": hashlib.sha256((dest / "objects.tar").read_bytes()).hexdigest(),
}
(dest / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
print(f"tabelas={len(manifest['census'])} linhas={sum(manifest['census'].values())}")
PY

# 5. A cifra -----------------------------------------------------------------
for file in manifest.json dump.pgc objects.tar; do
  encrypt_file "$DEST/$file"
done

log "backup concluído em $DEST"
ls -la "$DEST" >&2
