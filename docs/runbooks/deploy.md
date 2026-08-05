# Runbook — subir e manter a homologação

Fase 5, ADR 0022. O ambiente é definido em código: `docker-compose.homolog.yml`,
`infra/caddy/Caddyfile` e `.env.homolog.example`. Este runbook é o que falta entre esses
arquivos e uma máquina.

**O que este runbook não faz.** Ele não provisiona a máquina, o DNS nem o backup automático. O
item do roadmap é "definir o ambiente"; provisionar é uma decisão de infraestrutura que não
pertence a este repositório, e escrevê-la aqui como se estivesse feita seria o defeito que a
Fase 5 inteira existiu para fechar.

## Pré-requisitos

- Um host com Docker e Compose ≥ 2.24 (o override usa `!reset`, que é de 2.24).
- Dois nomes de DNS apontando para ele: `portal.<domínio>` e `auth.<domínio>`. O Caddy pede o
  certificado por ACME na primeira subida, e sem DNS resolvendo isso falha.
- Portas 80 e 443 abertas. **Nenhuma outra**: nenhum outro serviço publica porta.

## 1. Os segredos

```bash
cp .env.homolog.example .env
```

O arquivo copiado **não sobe**. Todo valor traz `CHANGEME`, que é sentinela do
`portal_api/preflight.py` — um `.env` preenchido pela metade é recusado na subida do processo, e
isso é deliberado: a exigência `${VAR:?}` do compose só sabe perguntar se a variável tem valor,
nunca se o valor é seu.

Gere cada um:

| Variável | Como gerar | Ao rotacionar |
|---|---|---|
| `POSTGRES_*_PASSWORD` (5) | `openssl rand -base64 24` | `roles.sql` reescreve a senha do papel; ver `restore.sh`, que faz o mesmo |
| `DATABASE_*_URL` (4) | montadas com as senhas acima | precisam bater — quem troca uma e esquece a outra descobre no `up` |
| `AUTH_SECRET` | `openssl rand -base64 32` | **desloga todo mundo**: é a chave do cookie |
| `AUTH_KEYCLOAK_SECRET`, `KEYCLOAK_ADMIN_CLIENT_SECRET` | do próprio Keycloak, na criação dos clients (passo 2) | regenerar no realm e reimplantar |
| `AGENT_KEY_PEPPER` | `openssl rand -base64 32` | **invalida todas as chaves de agente emitidas** — que é a forma de revogar tudo de uma vez (ADR 0013) |
| `DRIVE_TOKEN_ENCRYPTION_KEY` | `openssl rand -base64 32` | a anterior vai em `DRIVE_TOKEN_ENCRYPTION_KEY_PREVIOUS`, senão **todo projeto precisa reconsentir** (ADR 0016) |
| `BIAHFLOW_READ_TOKEN`, `BIAHFLOW_WEBHOOK_SECRET` | do Biahflow | combinar com o outro lado antes |
| `STORAGE_ACCESS_KEY` / `SECRET_KEY`, `MINIO_ROOT_*` | `openssl rand -base64 24` | rotacionar no MinIO primeiro |
| `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY` | consoles dos provedores | — |
| `BACKUP_AGE_RECIPIENT` | `age-keygen` | guarde a **identidade** fora deste host; sem ela o backup é ilegível |

Nenhum destes está no backup, e isso é decisão da ADR 0019: `backup-restore.md` lista o que o
dump **não** contém, e é esta tabela. Um restore sem eles devolve um banco que ninguém abre.

## 2. O realm

O realm do repositório (`portal-local`) **não** é usado aqui: ele tem `sslRequired: none`, os
segredos de client em claro e três pessoas com senha conhecida. O override sobe o Keycloak com
`start` e sem `--import-realm`.

Suba só o Keycloak, crie o realm `portal-homolog` pelo console em `https://auth.<domínio>`, e
dentro dele:

- client **`portal-web`**, confidencial, `redirect_uri` `https://portal.<domínio>/api/auth/callback/keycloak`,
  com o mapper de audiência para `portal-api` (sem ele o token não passa na API);
- client **`portal-admin`**, confidencial, service account, com `manage-users` e `view-users` no
  `realm-management` — é ele que cria a conta no convite (ADR 0011);
- SMTP do realm apontando para o mesmo provedor de `SMTP_HOST`: quem manda o e-mail de definir
  senha é o Keycloak, não o portal.

Copie os dois segredos para o `.env`.

## 3. Subir

```bash
docker compose -f docker-compose.yml -f docker-compose.homolog.yml up -d --build
```

Ordem esperada: `postgres` → `db-bootstrap` (cria os quatro papéis) → `api-migrate` →
`api-seed` (**neutralizado**, roda `true`) → `api`/`worker`/`beat` → `web` → `caddy`.

O seed não roda de propósito: ele semeia três pessoas com senha conhecida e um projeto de
demonstração, que é o dado fabricado que o portal inteiro foi construído para não mostrar.

## 4. Conferir que subiu, e que subiu seguro

```bash
docker compose -f docker-compose.yml -f docker-compose.homolog.yml ps
curl -sf https://portal.<domínio>/login >/dev/null && echo "web ok"

# Prontidão de verdade: fala com Postgres e Redis (ADR 0018).
docker compose -f docker-compose.yml -f docker-compose.homolog.yml exec api \
  python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/health/ready').status)"

# O que prova que a segunda barreira está de pé. Um restore que traz as linhas e
# perde a RLS devolve um portal onde todo cliente vê todo projeto, e nada na tela
# denuncia (ADR 0019).
docker compose -f docker-compose.yml -f docker-compose.homolog.yml exec postgres \
  psql -U portal -d portal -tAc \
  "select rolbypassrls or rolsuper from pg_roles where rolname='portal_app';"   # espera-se f
```

E o que o log deve dizer uma vez por processo:

```bash
docker compose -f docker-compose.yml -f docker-compose.homolog.yml logs api | grep '"event":"preflight.ok"'
```

## Quando a subida é recusada

`UnsafeEnvironment` na saída do `api` ou do `worker` não é um defeito — é o controle. A mensagem
lista **todos** os problemas de uma vez, porque quem configura um ambiente novo erra em cinco
variáveis e não em uma. Leia a lista, corrija o `.env`, suba de novo.

Os três motivos, e o que cada um significa:

- **"ainda carrega o valor de exemplo"** — a variável não foi fornecida e o default do
  `docker-compose.yml` entrou no lugar, ou o `CHANGEME` do template ficou. É o caso que este
  controle existe para pegar.
- **"está vazio"** — o segredo falta. O controle que ele sustenta já falha fechado (sem
  `AGENT_KEY_PEPPER` nenhuma chave de agente autentica), e é justamente por ser silencioso que
  vale recusar aqui.
- **"não é https"** — o cookie de sessão perde o prefixo `__Secure-`.

**Não desligue com `ENVIRONMENT=local`.** Isso não conserta nada: desliga a checagem e mantém o
ambiente exposto com a senha do exemplo, que é a única situação pior do que não subir.

## Backup

`scripts/backup.sh` continua sendo a operação, e ela **não** é agendada pelo `beat` (ADR 0019:
backup é operação, não aplicação). Em homologação isso significa um cron no host:

```cron
17 3 * * *  cd /srv/portal && ./scripts/backup.sh >> /var/log/portal-backup.log 2>&1
```

O `alerts.md` já traz o alerta que dá sentido a isso — **ausência de um backup bem-sucedido em
26 h acorda alguém** —, e ele só é verdadeiro se houver quem execute. O realm sai à parte, pelo
`kc.sh export`, como o `backup-restore.md` registra.

## O que ainda não está aqui

Nomeado para não ser confundido com feito:

- **Métrica e coletor.** O substrato é o log JSON no stdout, que qualquer coletor ingere sem
  código nosso (`docs/observability.md`). Não há exporter, e `alerts.md` diz isso desde a ADR
  0018.
- **PITR e réplica.** O backup é o dump diário; a janela de recuperação declarada é dele.
- **Storage publicado.** `STORAGE_PUBLIC_ENDPOINT_URL` precisa de um endereço que o navegador
  alcance para a citação abrir (ADR 0017), e a assinatura cobre o host. Enquanto o storage for o
  MinIO deste compose, publique um terceiro nome no `Caddyfile` apontando para `minio:9000` e use
  esse endereço na variável.
