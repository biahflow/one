# ADR 0019 — Backup e restore verificáveis

**Status:** aceita — 05/08/2026
**Contexto:** Fase 5, terceira fatia. Fecha o item "backup/restore testado" de
`ROADMAP.md`.

## Contexto

Como a ADR 0018, esta fatia não implementa uma promessa adiada: implementa uma que
os documentos já davam como cumprida, e desta vez três documentos delegavam a um
quarto que não existia em forma executável.

- `docs/runbooks/backup-restore.md` tinha dezesseis linhas mandando "testar backup
  criptografado de PostgreSQL e objetos do MinIO em ambiente isolado" e "validar
  RLS, integridade de fontes e ausência de cruzamento de tenant após restore".
  Não havia `scripts/`. Não havia dump, restore nem cifra alguma.
- A ADR 0010 e a ADR 0011 **delegam** a esse runbook a responsabilidade por rodar
  `roles.sql` antes do restore; `docs/runbooks/auth-failure.md` faz o mesmo, numa
  seção chamada "Restaurar um backup".

E o modo de falha central foi medido, não deduzido. Com o schema deste
repositório, no Postgres 16:

```
pg_dump -U portal_app -n portal                       → exit 1
    ERROR: query would be affected by row-level security policy for "organization"
pg_dump -U portal_app -n portal --enable-row-security  → exit 0, COPY com 0 linhas
```

O Postgres **recusa** o dump tirado com a credencial de requisição — a RLS se
aplica às consultas que o `pg_dump` emite e ele não aceita produzir um dump que
sabe estar filtrado. A correção óbvia, acrescentar a flag que cala a recusa, é a
armadilha: produz um backup bem-sucedido, íntegro, cifrável, restaurável — e
vazio. Ninguém olha duas vezes para um comando que saiu com zero.

A tentativa de restaurar revelou ainda dois defeitos silenciosos que só apareceriam
no dia do desastre, e que esta fatia corrige:

- **`btree_gist` nunca entrou no bootstrap.** Ele foi criado pela migração 0010,
  para o `EXCLUDE USING gist` de `project_financial_assumption`. Um restore não
  roda migrações, então o dump chegava num banco sem a classe de operadores e
  falhava. Extensão é objeto de *banco*, não de *schema*, e por isso não entra num
  `pg_dump -n portal` — pela mesma razão que papel é objeto de *cluster* e também
  não entra.
- **As duas extensões nasciam no schema errado.** Sem `WITH SCHEMA public`, o
  `CREATE EXTENSION` as põe no primeiro schema do `search_path` — e foi assim que
  o `btree_gist` acabou dentro de `portal`, fazendo o `DROP SCHEMA portal` do
  restore falhar por dependência. Em `public` a extensão sobrevive ao schema.

## Decisão

### 1. O dump sai sob o papel dono, e o backup carrega um censo

`portal_migrator` é dono do schema e portanto isento da RLS (usamos `ENABLE`, não
`FORCE`), e é o único que enxerga o DDL completo. `portal_app` não serve pelo
motivo acima.

Mas fixar o papel no script é uma afirmação sobre o script, não sobre o backup.
O que torna o backup verificável é o **censo**: `scripts/census.sql` conta as
linhas de toda tabela do schema — lista tirada do catálogo, não escrita à mão,
senão toda migração futura precisaria lembrar de vir aqui — e o número vai para o
manifesto. O `restore.sh` refaz o censo contra o banco restaurado e recusa a
divergência.

**O censo sai sob credencial diferente da do dump**, e essa é a parte que faz o
manifesto valer alguma coisa: `portal_system` (BYPASSRLS) conta, `portal_migrator`
(dono) despeja. Com a mesma credencial nos dois, os dois errariam na mesma
direção — zero linhas contadas confirmando zero linhas despejadas — e o manifesto
atestaria com entusiasmo que o backup vazio está correto.

### 2. Papéis e extensões antes do dump, porque nenhum dos dois vem nele

O que era um parágrafo do runbook virou passo com código de saída. `restore.sh`
roda `infra/postgres/bootstrap/roles.sql` **antes** do `pg_restore` — o que agora
também cria as extensões no lugar certo — e depois afirma:

```
portal_app.rolsuper = false      portal_app.rolbypassrls = false
policies > 0                     tabelas_com_rls > 0
```

Um restore que devolve as linhas e perde as policies devolve um portal em que todo
cliente vê todo projeto e nada parece quebrado. É o pior resultado possível desta
operação, e é o único que não se percebe olhando a tela.

`pg_restore` roda com `--clean --if-exists --exit-on-error`: o `--clean` resolve a
colisão entre o `CREATE SCHEMA portal` do dump e o schema que o `roles.sql` acabou
de criar, e o `--exit-on-error` é o que impede um restore de "quase funcionar".

### 3. Cifra é `age`, e a ausência de chave falha

AEAD por padrão e um binário só. `BACKUP_AGE_RECIPIENT` ausente **aborta** o
backup; `--allow-plaintext` existe, é explícito e vai no log.

É a regra que a ADR 0017 impôs ao scanner — *`skipped` não é `clean`* — aplicada à
cifra. Um backup em claro pode ser uma escolha; nunca pode ser o efeito colateral
de uma variável esquecida no ambiente novo. Descartamos `openssl enc -aes-256-cbc`
justamente por não ser autenticado: um backup corrompido que decifra em lixo
silenciosamente é o modo de falha que um backup não tem o direito de ter.

### 4. A cifra do dump não protege o que não está no dump

`AGENT_KEY_PEPPER` e `DRIVE_TOKEN_ENCRYPTION_KEY` vivem no ambiente, não no banco.
Um restore sem eles devolve `agent_api_key` cujo HMAC não confere com nada e
refresh tokens do Drive que não abrem — a AES-256-GCM de `crypto.py` leva o tenant
no dado associado, mas a chave é de fora. O conjunto de backup inclui esse material,
e ele é guardado **em outro lugar** que o dump: senão cifrar o dump é teatro,
porque a chave viaja junto do cofre.

O mesmo vale para o realm do Keycloak. Um portal restaurado sem ele tem
`external_subject` apontando para ninguém — a identidade é do realm, não do
portal (ADR 0010) —, e é por isso que o runbook nomeia o `kc.sh export` mesmo sem
automatizá-lo aqui.

### 5. Restaurar desfaz um expurgo, e a ADR 0017 já deixou como consertar

Um backup anterior a um `data_erasure_request` cumprido contém a organização
apagada; restaurá-lo a traz de volta. Isso é **resolvível** só porque aquela ADR
decidiu que a linha do pedido sobrevive ao próprio expurgo: `restore.sh` termina
listando todo pedido com `completed_at` posterior ao `taken_at` do backup, que é
exatamente o conjunto a reexecutar.

Dois corolários entram no runbook em vez de virar código: a retenção do backup não
pode exceder a janela de retenção da organização (ou a política de retenção é
mentira), e restaurar num banco descartável do mesmo cluster redefine a senha dos
quatro papéis nele, porque papel é objeto de cluster.

### 6. O storage é espelhado por `portal_api.backup`, não por um `mc` no compose

O docstring de `storage.ensure_bucket` já tinha rejeitado "um serviço `mc` a mais
no compose" por a operação ser idempotente e valer igual contra um S3 vazio; o
mesmo argumento vale aqui, e reusar o cliente que já existe evita uma segunda
credencial de storage no repositório.

Duas funções e **nenhuma rota HTTP**, na mesma forma de `retention.py` e pelo mesmo
motivo: um endpoint que devolvesse o bucket inteiro seria um caminho de requisição
capaz de ler dado de todo tenant de uma vez, que é o avesso da regra 1 do
`AGENTS.md`.

O contêiner é um tar cujo nome de membro **é a chave do objeto** — a chave já
carrega o tenant inteiro desde a ADR 0014, então um backup por organização é só um
prefixo, e um objeto solto continua dizendo sozinho a quem pertencia. Nada é
extraído para o sistema de arquivos, mas o nome ainda é validado: um tar é entrada,
e não se confia numa entrada só porque nós a produzimos da última vez.

Cada objeto tem SHA-256 no índice, e um cujo hash não bate **não é gravado**.
Restaurar bytes corrompidos é pior que falhar: a citação da ADR 0017 continuaria
abrindo um link, só que para um arquivo que não é mais o que foi citado.

## Consequências

- Existe `scripts/`, com `backup.sh`, `restore.sh`, `census.sql` e `lib.sh`. É o
  primeiro código do repositório que não é nem web, nem API, nem infraestrutura
  declarativa: é operação.
- `roles.sql` passou a criar `btree_gist` e a fixar `public` nas duas extensões.
  Bancos existentes não mudam (`IF NOT EXISTS`), bancos novos e restaurados
  nascem certos.
- `storage.py` ganhou `iter_keys` e `fetch_object`. O segundo existe porque
  `get_object` descarta o content type, e um PDF restaurado como
  `application/octet-stream` faz o navegador baixar o arquivo em vez de abrir a
  página citada.
- Os binários do Postgres são configuráveis (`PSQL`, `PG_DUMP`, `PG_RESTORE`)
  porque `pg_dump` recusa servidor mais novo que ele. `test_backup_restore.py`
  **pula** quando o cliente da máquina é antigo, na mesma decisão que o
  `conftest.py` toma para a ausência de banco.
- O backup completo trafega os objetos pelo processo que o roda. Para um acervo
  grande isso é o caminho errado, e o runbook nomeia o certo — versionamento e
  replicação do provedor —, mas o portátil é o que se pode testar em CI.

## Alternativas descartadas

- **`pg_dumpall`, ou dump do banco inteiro.** Traria papéis e o schema do
  Keycloak de graça. Descartado porque acopla o backup do portal ao do Keycloak
  num arquivo só, e são coisas com donos e prazos diferentes; o runbook trata as
  duas, separadas.
- **Agendar o backup no `beat`.** Backup é trabalho de operação, não do worker de
  aplicação — e o `beat` é singleton e de propósito sem healthcheck (ADR 0018).
  Um backup que depende do processo que também indexa documentos falha junto com
  ele, no momento em que mais se precisa dele.
- **`--enable-row-security` para "resolver" a recusa do `pg_dump`.** É a
  armadilha, não a solução. `test_backup_restore.py` a executa para que ninguém a
  descubra de novo achando que descobriu uma correção.
