# Trecho comum de backup.sh e restore.sh (ADR 0019). Não é executável: é `source`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Os binários do Postgres são configuráveis porque a versão do cliente tem de
# bater com a do servidor: `pg_dump` recusa servidor mais novo. Quem tem cliente
# antigo na máquina aponta estas variáveis para o binário do contêiner — ver
# `docs/runbooks/backup-restore.md`.
PSQL="${PSQL:-psql}"
PG_DUMP="${PG_DUMP:-pg_dump}"
PG_RESTORE="${PG_RESTORE:-pg_restore}"

# O interpretador que roda `portal_api.backup` — precisa do boto3, então é o do
# venv do projeto quando existe. Os trechos embutidos aqui usam só a biblioteca
# padrão e continuam no `python3` do sistema.
PYTHON="${PYTHON:-${REPO_ROOT}/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="python3"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die() { log "ERRO: $*"; exit 1; }

# O `.env` do compose, quando existe. As variáveis já exportadas ganham dele:
# quem passou DATABASE_MIGRATION_URL na linha de comando quis aquele banco.
load_env() {
  local env_file="${1:-$REPO_ROOT/.env}"
  [ -f "$env_file" ] || return 0
  local key value
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"
    value="${line#*=}"
    case "$key" in *[!A-Za-z0-9_]*|'') continue ;; esac
    [ -n "${!key+x}" ] || export "$key=$value"
  done < "$env_file"
}

# SQLAlchemy escreve `postgresql+psycopg://`; libpq não conhece o driver.
libpq_url() {
  printf '%s' "${1/+psycopg/}"
}

# Uma URL sem a senha, para caber num log sem vazar.
redacted_url() {
  printf '%s' "$1" | sed -E 's#(://[^:/@]+):[^@]*@#\1:***@#'
}

# `swap_url URL [--db NOME] [--user USUÁRIO] [--password SENHA]`
#
# Restaurar num banco descartável do mesmo cluster significa manter host, porta e
# tudo o mais, trocando só uma peça. Feito em Python porque a URL pode ter senha
# com `@` ou `/`, e um `sed` sobre isso é um bug esperando data.
swap_url() {
  URL="$1" ARGS="${*:2}" python3 - <<'PY'
import os, sys
from urllib.parse import urlsplit, urlunsplit, quote

url = urlsplit(os.environ["URL"])
args = os.environ["ARGS"].split()
opts = dict(zip(args[::2], args[1::2]))

user = opts.get("--user", url.username or "")
password = opts.get("--password", url.password or "")
database = opts.get("--db", url.path.lstrip("/"))

netloc = quote(user, safe="")
if password:
    netloc += ":" + quote(password, safe="")
netloc += "@" + (url.hostname or "")
if url.port:
    netloc += f":{url.port}"

sys.stdout.write(urlunsplit((url.scheme, netloc, "/" + database, url.query, "")))
PY
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "$2"
}

# Cifra `$1` em `$1.age` e apaga o texto claro. Com --allow-plaintext, não faz
# nada — e o chamador já registrou que não fez.
#
# A ausência de chave **falha**, e não vira backup em claro: é a mesma regra do
# scanner da ADR 0017 ("skipped não é clean"). Um backup sem cifra pode ser uma
# escolha; nunca pode ser um efeito colateral de uma variável esquecida.
encrypt_file() {
  local path="$1"
  if [ "$ALLOW_PLAINTEXT" = "1" ]; then
    return 0
  fi
  age -r "$BACKUP_AGE_RECIPIENT" -o "$path.age" "$path"
  rm -f "$path"
}

# Decifra `$1.age` em `$1` quando existir; aceita o texto claro quando não.
decrypt_file() {
  local path="$1"
  if [ -f "$path.age" ]; then
    require_cmd age "o backup está cifrado e o \`age\` não está instalado"
    [ -n "${BACKUP_AGE_IDENTITY:-}" ] \
      || die "backup cifrado e BACKUP_AGE_IDENTITY não definido"
    [ -f "$BACKUP_AGE_IDENTITY" ] \
      || die "BACKUP_AGE_IDENTITY não é um arquivo: $BACKUP_AGE_IDENTITY"
    age -d -i "$BACKUP_AGE_IDENTITY" -o "$path" "$path.age"
    return 0
  fi
  [ -f "$path" ] || die "nem $path nem $path.age existem"
  log "AVISO: $(basename "$path") está em texto claro neste backup"
}
