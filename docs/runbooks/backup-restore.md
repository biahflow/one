# Runbook — Backup e restore

Backup cifrado do PostgreSQL e dos objetos do storage, e um restore que se prova
(ADR 0019, FDD 013). Duas metades com modos de falha opostos: o banco erra por
**privilégio** — a credencial errada devolve um backup vazio sem dizer — e o
storage erra por **completude**, então cada uma é conferida pelo que a ameaça dela
exige: o banco por um censo de linhas, os objetos por um SHA-256 cada.

## Tirar um backup

```bash
export BACKUP_AGE_RECIPIENT=age1...      # a chave pública; sem ela o script aborta
./scripts/backup.sh
```

Produz `backups/<timestamp>/` com `manifest.json.age`, `dump.pgc.age` e
`objects.tar.age`. `--out DIR` escolhe o destino, `--prefix org/<uuid>/` limita os
objetos a uma organização, `--allow-plaintext` diz **explicitamente** que este
backup não será cifrado.

A ausência da chave falha em vez de gravar texto claro. Um backup em claro pode ser
uma escolha; nunca o efeito colateral de uma variável esquecida no ambiente novo —
a mesma regra que a ADR 0017 impôs ao antivírus (`skipped` não é `clean`).

### Cliente do Postgres mais antigo que o servidor

`pg_dump` recusa um servidor mais novo que ele. Aponte os binários para os do
contêiner:

```bash
PGC=$(docker compose ps -q postgres)
cat > /tmp/pg_dump <<EOF
#!/usr/bin/env bash
exec docker run --rm -i --network "container:$PGC" -v "\$PWD:\$PWD" -w "\$PWD" \\
  pgvector/pgvector:pg16 pg_dump "\$@"
EOF
chmod +x /tmp/pg_dump   # idem para psql e pg_restore
PG_DUMP=/tmp/pg_dump PSQL=/tmp/psql PG_RESTORE=/tmp/pg_restore ./scripts/backup.sh
```

Compartilhar o *namespace de rede* do contêiner faz `localhost:5432` significar a
mesma coisa dentro e fora, o que evita duas URLs para um banco só.

## O que o backup **não** guarda

Guardar isto junto do dump anularia a cifra — a chave viajaria dentro do cofre.
Guarde em outro lugar, e saiba que sem eles o restore devolve dados inúteis:

| O quê | Sem ele, depois do restore |
|---|---|
| `AGENT_KEY_PEPPER` | todo `agent_api_key` deixa de conferir; nenhum agente publica evento |
| `DRIVE_TOKEN_ENCRYPTION_KEY` (e `_PREVIOUS`) | nenhum refresh token do Drive abre; toda pasta precisa reconsentir |
| `AUTH_SECRET`, segredos dos clients do Keycloak | as sessões em curso caem |
| O realm do Keycloak (`kc.sh export`) | `external_subject` aponta para ninguém: as contas existem no portal e não autenticam |

A identidade é do realm, não do portal (ADR 0010). Exportar o realm é parte do
backup mesmo não estando neste script.

## Restaurar

**Restaure noutro cluster, ou num banco descartável.** Nunca por cima do banco em
uso: `restore.sh` exige `--database` justamente para que o alvo seja uma decisão.

```bash
export BACKUP_AGE_IDENTITY=/caminho/para/chave.txt
./scripts/restore.sh backups/<timestamp> --database ensaio --with-objects
```

A ordem dos passos é dependência, não preferência:

1. **`CREATE DATABASE`** do alvo.
2. **`infra/postgres/bootstrap/roles.sql`.** Papéis são objetos de *cluster* e
   extensões são objetos de *banco*: **nem uns nem outras vêm num `pg_dump -n
   portal`**. Sem este passo o restore falha em `public.vector` e na classe de
   operadores do `EXCLUDE USING gist` de `project_financial_assumption` — e, se
   falhasse mais tarde, os `GRANT` e as policies apontariam para papéis
   inexistentes. É o item de restore mais fácil de esquecer.
3. **`pg_restore --clean --if-exists --exit-on-error`.** Traz tabelas, dados,
   policies e GRANTs, inclusive os de coluna.
4. **Censo conferido** contra o manifesto, sob `portal_system` — credencial
   diferente da que tirou o dump, de propósito (ver abaixo).
5. **Verificação dos papéis**, que o script faz e falha se não bater:

```sql
SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'portal_app';  -- → (f, f)
SELECT count(*) FROM pg_policies WHERE schemaname = 'portal';              -- → > 0
```

Um restore que devolve as linhas e perde as policies devolve um portal em que todo
cliente vê todo projeto — e nada na tela denuncia isso. É o pior resultado possível
desta operação e o único invisível.

> ⚠️ O passo 2 escreve papéis, que são do **cluster inteiro**. Restaurar num banco
> descartável do cluster de produção redefine a senha dos quatro papéis nele.
> Passe as senhas em vigor, ou restaure noutro cluster.

## Depois do restore: os expurgos que ele desfez

Um backup anterior a um `data_erasure_request` cumprido contém a organização
apagada, e restaurá-lo a traz de volta. O `restore.sh` termina listando os pedidos
com `completed_at` posterior ao instante do backup — possível porque a linha do
pedido **sobrevive ao próprio expurgo** (ADR 0017). Reexecute cada um antes de o
ambiente restaurado receber tráfego.

Corolário: **a retenção do backup não pode exceder a janela de retenção da
organização.** Guardar backups por dois anos com uma política de exclusão de um
ano significa ter, por um ano, um dado que se prometeu apagar.

## Por que o dump não sai com `portal_app`

Porque não sai — e porque a maneira óbvia de fazer sair é a armadilha:

```
pg_dump -U portal_app -n portal                       → exit 1
    ERROR: query would be affected by row-level security policy
pg_dump -U portal_app -n portal --enable-row-security  → exit 0, COPY com 0 linhas
```

A flag cala a recusa e produz um backup limpo, bem-sucedido, cifrável, restaurável
— e vazio. Ninguém olha duas vezes para um comando que saiu com zero. Por isso o
dump é fixado em `portal_migrator` (dono, isento por ser dono) e o **censo sai sob
`portal_system`**: com a mesma credencial nos dois, os dois errariam na mesma
direção e o manifesto confirmaria que zero linhas viraram zero linhas.
`apps/api/tests/test_backup_restore.py` executa exatamente este cenário.

## Testar o par, sem esperar o desastre

```bash
docker compose up -d postgres db-bootstrap minio
docker compose stop worker beat        # o worker no ar disputa as tasks com o pytest
PYTHONPATH=apps/api/src pytest apps/api/tests/test_backup_restore.py -v
```

Os casos de storage rodam sem rede e sem banco. Os do Postgres pulam sozinhos
quando não há banco alcançável ou quando o cliente é mais antigo que o servidor —
nesse caso use as variáveis da seção acima.

## Em produção, o storage não é este script

`scripts/backup.sh` traz os objetos pelo processo que o roda, o que é o caminho
certo para um acervo pequeno e para o CI, e o errado para um bucket grande. Em S3,
prefira **versionamento** mais **replicação entre regiões**, e mantenha este script
para o Postgres e para a verificação. O que não muda é a conferência: sem o índice
com SHA-256, "os objetos foram copiados" é uma afirmação sobre o comando, não sobre
os arquivos.
