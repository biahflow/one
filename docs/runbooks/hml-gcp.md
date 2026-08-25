# Runbook — subir a homologação na GCP

> **13/08/2026 — o portal do cliente saiu.** Não existem mais `portal-web`, `portal-api`,
> `keycloak`, `portal-worker`, `portal-beat` nem `portal-migrate` na GCP, nem o state
> `ambientes/hml-portal`, nem os vinte segredos que eram deles. O que sobrou de HML é o
> CRM (`pulse-*`, que foi `biahflow-*` até 19/08/2026 e `cockpit-*` até 25/08/2026) e o relay do site de
> marketing. **Os passos 5, 8 e 9 abaixo tratam de segredos, do realm do Keycloak e do
> `roles.sql` do banco do portal — são história até alguém religar o produto**, e ficam
> porque religar é refazê-los. A ADR 0053 conta o resto, inclusive a troca do
> balanceador da GCP pela Cloudflare.

ADR 0044, 0045, 0046, 0048, 0050, 0051 e 0053. A infraestrutura é definida em `infra/terraform/`, em duas
camadas: `ambientes/hml/` diz **o quê** e `modulos/` diz **como**. O `README.md` de lá
explica a arquitetura, o `nip.io`, os três portões e as identidades — não repito nada
disso aqui. Este runbook é o que falta entre aquele Terraform e um ambiente de pé: **a
ordem, e o que é manual**.

**O que este runbook não faz.** Ele não substitui o `deploy.md`, que é a homologação em
Docker Compose num host. São dois caminhos diferentes para a mesma fase, e este é o da
GCP. Ele também não declara HML pronta: a última seção diz o que falta medir para isso.

## Pré-requisitos

- `gcloud` autenticado com **credencial de pessoa** que possa criar recursos no projeto.
  Não é preferência: o pool de WIF que o CI usaria é criado por este Terraform (ADR
  0046), então antes do primeiro apply não existe a credencial do CI.
- Essa mesma pessoa precisa de **`roles/orgpolicy.policyAdmin` na organização**, para o
  passo 2. O papel não é concedível em projeto — `gcloud` responde `Role ... is not
  supported for this resource` —, e pode ser devolvido depois: a política sobrevive.
- `terraform` ≥ 1.9 (o CI usa 1.14.3).
- Uma conta no **Neon** e uma no **Upstash**. O Postgres e o Redis não moram na GCP, e a
  razão está na ADR 0045.
- `psql` cliente 16 ou mais novo, para o passo 9.

---

## 1. As APIs, à mão

O Terraform declara onze `google_project_service`, e declará-las **não dispensa
habilitá-las antes**: é preciso a API de habilitar APIs para habilitar APIs.

```bash
# Só as três meta. As outras oito o Terraform habilita, uma vez que estas existam.
gcloud services enable serviceusage.googleapis.com \
  cloudresourcemanager.googleapis.com iam.googleapis.com --project=biahflow-hml
```

## 2. A política da organização, à mão

Uma organização criada por Workspace nasce com **Domain Restricted Sharing ligado**:
`constraints/iam.allowedPolicyMemberDomains` restrita ao customer ID da org. Com ela em
vigor, as quatro ligações `allUsers` do `servico-cloudrun` falham com *"One or more users
named in the policy do not belong to a permitted customer"*, e a HML sobe inteira
respondendo **403 a tudo**, com a aplicação de pé e nada no log dela — o modo de falha que
a ADR 0048 manda não depurar pelo Django.

Não há contorno: um NEG sem servidor **não cunha ID token**, então o serviço atrás dele
precisa aceitar chamada não autenticada, e quem barra é o ingress (ADR 0048).

```bash
cat > /tmp/drs.yaml <<'YAML'
name: projects/biahflow-hml/policies/iam.allowedPolicyMemberDomains
spec:
  rules:
    - allowAll: true
YAML
gcloud org-policies set-policy /tmp/drs.yaml
```

**Escopo de projeto, e não de organização** — a política da org fica intacta e todo projeto
novo continua nascendo restrito. `allowAll` e não o valor estreito porque a constraint
**recusa** `principalSet://goog/public:all` com `INVALID_GOOGLE_MANAGED_CONSTRAINT`, apesar
de a documentação do Google descrevê-lo; foi medido. Reverter é
`gcloud org-policies delete-policy constraints/iam.allowedPolicyMemberDomains --project=biahflow-hml`.

Isto **não** vira Terraform: a `hml-infra` não tem permissão de `orgpolicy`, e dá-la ao CI
de um projeto seria deixá-lo afrouxar a postura da organização inteira (ADR 0050).

## 3. O bucket do estado, à mão

Mesmo ovo-e-galinha: o `backend.tf` aponta para um bucket que o `terraform init` precisa
alcançar antes de haver Terraform aplicado. Os dois comandos estão no cabeçalho daquele
arquivo, e o versionamento não é opcional — é a única forma de voltar de um `apply` que
corrompeu o estado.

```bash
gcloud storage buckets create gs://biahflow-hml-tfstate \
  --project=biahflow-hml --location=us-east1 --uniform-bucket-level-access
gcloud storage buckets update gs://biahflow-hml-tfstate --versioning
```

O nome tem de bater com o `bucket` do `backend.tf`, que **não aceita variável**: o `init`
acontece antes de haver valores.

## 4. O primeiro apply, local — e em dois

```bash
cd infra/terraform/ambientes/hml
cp terraform.tfvars.example terraform.tfvars   # deixe `tag_imagem` comentada
terraform init
terraform apply -target=module.fundacao
```

**Só a fundação, e a razão é o passo seguinte** (ADR 0050). O Terraform cria os **dez** segredos
**sem versão nenhuma**, de propósito — um valor passado por ele ficaria no estado —, e todo
serviço os monta com `version = "latest"`. O `latest` de um segredo sem versão não existe, e
a revisão do Cloud Run é **recusada na criação**, não no boot. Aplicar tudo de uma vez aqui
reprova, e a mensagem fala de segredo não encontrado, não de ordem.

Segredo *vazio* e segredo *inexistente* são coisas diferentes; este passo produz o segundo, e
o passo 5 o converte no primeiro.

**`tag_imagem` fica de fora, e a ausência é o conserto** (ADR 0046). O Artifact Registry
está vazio; um serviço criado apontando para tag inexistente tem a revisão recusada, e o
`ignore_changes` do módulo não salva porque ele age em *update*, nunca em *create*.
Vazia, ela significa `imagem_bootstrap` — o `hello` da Google, que existe e sobe —, e o
serviço passa a existir para o `deploy-hml.yml` poder atualizá-lo.

## 5. Os segredos

Criados **vazios** pelo Terraform, de propósito: um valor passado pelo Terraform ficaria
no estado, que é um arquivo num bucket. O nome do segredo **é** o nome da variável de
ambiente.

```bash
# Um por vez. A lista completa está em `ambientes/hml/variables.tf`.
printf '%s' "$(openssl rand -base64 32)" | \
  gcloud secrets versions add AUTH_SECRET --data-file=- --project=biahflow-hml
```

Como gerar cada um: a tabela do **`deploy.md` § 1** vale inteira aqui, inclusive a coluna
do que acontece ao rotacionar. O que muda é o destino — Secret Manager e não `.env` — e
que a HML da GCP acrescenta os do outro produto (`DJANGO_SECRET_KEY`, `PORTAL_*`, os três
`GOOGLE_OAUTH_*`) e os do Keycloak gerenciado (`KC_DB_*`, `KC_BOOTSTRAP_ADMIN_PASSWORD`).

As DSNs do Neon e do Upstash entram em **dois** segredos: `BIAHFLOW_DATABASE_URL` e
`BIAHFLOW_REDIS_URL`. Cada aplicação continua lendo `DATABASE_URL` e `REDIS_URL` no
ambiente — quem faz a ligação é o mapa `segredos` de `servicos.tf`.

*Corrigido em 20/08/2026 (ADR 0065). Este parágrafo dizia "entram em **quatro** segredos,
e não em dois", com `PORTAL_*` para o outro produto: eram quatro porque cada produto tinha
o seu, e os do portal saíram em 13/08 com ele. O pareamento que a frase existia para
explicar terminou junto — antes de 12/08/2026 havia **um** segredo para cada nome, montado
nos dois produtos, de modo que a `portal-api` e o Django do CRM recebiam a mesma DSN sem
ninguém ter decidido isso.*

> **Um segredo esquecido não reprova no apply.** Os portões de `ambientes/hml/main.tf`
> pegam segredo referenciado e não criado, e segredo criado sem leitor — nenhum dos dois
> olha o *valor*. Quem pega valor vazio é o `preflight.py`, no **boot do processo**, e
> por isso o sintoma é um serviço que não sobe, não um plano vermelho. Os três motivos de
> recusa estão em `deploy.md § Quando a subida é recusada`, e valem igual aqui.

**Um segredo que este ambiente não usa ainda precisa de versão.** Um segredo sem leitor
hoje recebe um valor de marcação. É a existência da versão que o Cloud Run cobra, não o
conteúdo — ver o passo 4.

**Acrescentar um segredo depois repete o mesmo par de passos, e pela mesma razão.** O nome
entra em `variables.tf` e na lista `segredos` do serviço **no mesmo commit** (senão um dos
portões reprova o plano), mas o `apply` vai em dois: `-target=module.fundacao` cria o
segredo, `gcloud secrets versions add` lhe dá versão, e só então o apply completo o monta.
Foi assim que o `EMAIL_HOST_PASSWORD` entrou.

## 6. O apply completo

```bash
terraform apply                                   # a fundação: cofre, rede, registro e a borda
cd ../hml-biahflow && terraform init && terraform apply
```

**A fundação primeiro, sempre.** O produto lê as saídas dela por
`terraform_remote_state`, e um `plan` contra uma fundação não aplicada falha dizendo
que a saída não existe — mensagem que fala de output e não de ordem.

*Corrigido em 20/08/2026 (ADR 0065). Este passo se chamava "e agora são três" e mandava
`cd ../hml-portal`, diretório que o commit `9e2d61d` apagou em 13/08/2026 — um comando que
falha com `no such file or directory`, e a ADR 0064 tinha acabado de corrigir a linha
gêmea no `infra/terraform/README.md` sem alcançar esta. O cardinal saiu em vez de virar
"dois" pela razão que aquela ADR escreveu: ele era redundante com a fence logo abaixo, e
quem conta states de verdade é `São dois states`, guardado em `docs/architecture.md` e no
README daquele diretório. Enquanto houver um produto só, não há ordem entre produtos a
declarar: um produto que precise de valor do outro o deriva do número do projeto, que é
data source e não recurso nosso.*

Os serviços sobem **quebrados** neste momento, e isso é esperado: o realm não existe
(passo 8) e o banco ainda não tem os papéis (passo 9).

## 7. O `WIF_PROVIDER`, nos dois repositórios

```bash
# O que prova que o CI vai conseguir se autenticar sem chave de conta de serviço.
terraform output -raw provedor_wif
```

O valor vai na variável de repositório `WIF_PROVIDER` de **`biahflow/one` e
`biahflow/pulse`**. São dois, e esquecer o segundo faz o deploy do outro produto falhar
na primeira linha do primeiro job — com uma mensagem sobre credencial, não sobre variável
ausente.

Só o repositório que **contém** o Terraform federa a `hml-infra`; o outro recebe apenas a
`hml-deploy`. A separação é da ADR 0046 e não é cosmética: a `hml-infra` tem quase o
projeto inteiro.

### Quando um repositório muda de dono

O caminho `dono/repo` é a claim `assertion.repository` do token do GitHub, e ele aparece em
**três** lugares — dois deles fora deste repositório. Transferir sem mexer neles não quebra
o `git`: quebra o CI, com erro de credencial e não de configuração.

1. **A condição do provedor** e o binding da `hml-deploy` moram hoje em
   `biahflow/infra`, `envs/hml/wif/variables.tf` (`repos_allowlist` e `deploy_sa_repos`).
   Um PR ali aplica sozinho no merge. É onde a mudança acontece de verdade.
2. **As listas deste repositório** (`infra/terraform/ambientes/hml/variables.tf`) são
   espelho das de lá desde que o pool passou a ter dois donos — atualize junto, senão o
   próximo `apply` daqui reescreve a condição a partir da lista atrasada.
3. **A federação da `hml-infra`** só existe neste state (`repositorio_infra`). Ela é a que
   o `infra-hml.yml` usa, e a que **não** vem de graça com o PR do item 1: o token do
   caminho novo passa pela condição do provedor e falha na impersonação.

O caminho antigo **sai** da lista, nunca fica junto do novo — mantê-lo autorizaria um
repositório recriado naquele caminho. Precedentes: `biahflow/site` e `biahflow/eliseu`
(14/08/2026), `biahflow/portal` e `biahflow/portal-cliente` (17/08/2026).

## 8. O realm `portal-homolog`

O Terraform **não** cria o realm: não há provider de Keycloak neste repositório. O realm
versionado (`infra/keycloak/portal-local-realm.json`) é o **local** e não serve — ele tem
`sslRequired: none` e senhas conhecidas.

```bash
terraform output -json hosts   # o `keycloak` daqui é o issuer que a API valida
```

**Não é trabalho de console** (ADR 0052). Não haver provider de Terraform não significa
que só reste a mão: a API de administração faz tudo, e o que se ganha é reprodutibilidade.
O roteiro, na ordem, com `$KC` sendo o host do Keycloak:

```bash
ADM=$(gcloud secrets versions access latest --secret=KC_BOOTSTRAP_ADMIN_PASSWORD --project=biahflow-hml)
T=$(curl -s -X POST "$KC/realms/master/protocol/openid-connect/token" \
      -d client_id=admin-cli -d username=admin -d "password=$ADM" -d grant_type=password \
    | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# 1. o realm            POST $KC/admin/realms
# 2. client portal-web  POST $KC/admin/realms/portal-homolog/clients
#                       confidencial, redirectUris = <portal>/api/auth/callback/keycloak
# 3. o mapper           POST .../clients/<id>/protocol-mappers/models
#                       oidc-audience-mapper com included.custom.audience = portal-api
# 4. client portal-admin  serviceAccountsEnabled, e os papéis manage-users/view-users
#                         de `realm-management` no service-account-user dele
# 5. os dois segredos   GET .../clients/<id>/client-secret  →  AUTH_KEYCLOAK_SECRET
#                                                          →  KEYCLOAK_ADMIN_CLIENT_SECRET
```

> **O `/admin` do caminho é fácil de esquecer.** `POST $KC/realms/.../users` responde
> **404** em vez de erro de método; o caminho de administração é `$KC/admin/realms/...`.

> **O admin de bootstrap só nasce com o banco vazio.** Se o Keycloak já subiu uma vez sem
> `KC_BOOTSTRAP_ADMIN_USERNAME`, ele se considera inicializado e a variável não tem mais
> efeito — a única pista é `invalid_grant`. Com o schema ainda sem dado, o caminho é
> `DROP SCHEMA keycloak CASCADE; CREATE SCHEMA keycloak;` e uma revisão nova.

O passo 2 do `deploy.md` descreve o mesmo conteúdo item por item. Duas diferenças aqui:

- o nome do realm é `portal-homolog`, e ele mora num lugar só (`servicos.tf`), com
  `issuer` e `jwks_url` derivados — três nomes para a mesma coisa foi o defeito #6 da ADR
  0046, e o sintoma é a API recusar todo acesso com uma mensagem sobre **assinatura**;
- o `redirect_uri` usa o host de `terraform output hosts`, não `localhost`.

**O SMTP é configuração do realm, e é passo deste runbook.** `SMTP_HOST` fica vazio nos
serviços de propósito (ADR 0046) — não há SMTP de aplicação em HML —, mas o convite de
acesso continua saindo, porque quem o manda é o Keycloak. Sem o SMTP do realm, convidar
alguém falha em silêncio: ver `auth-failure.md`.

## 9. O `roles.sql` contra o Neon

Não há Cloud Run Job que faça isto, e as senhas de papel não estão entre os segredos do
cofre — é passo de pessoa, uma vez, com a credencial administrativa do Neon.

```bash
# O que ele prova: os quatro papéis existem, `portal_system` tem BYPASSRLS e os outros
# três não. O script imprime essa tabela no fim — leia-a, é a verificação.
PGPASSWORD=<admin> psql "postgresql://<admin>@<endpoint>/neondb?sslmode=require" \
  -v app_password=... -v system_password=... \
  -v migrator_password=... -v admin_password=... \
  -f infra/postgres/bootstrap/roles.sql
```

Num Postgres gerenciado não existe superusuário para a aplicação, e o script já sabe
disso: o `NOSUPERUSER` mora num bloco guardado e o bootstrap concede `portal_migrator` a
si mesmo quando não é superusuário (ADR 0044). Se aparecer um `NOTICE` sobre não poder
alterar atributo de papel, é isso funcionando — não é erro.

Depois dele, as migrações. O `portal-migrate` é executado pelo `deploy-hml.yml`; os dois
do outro produto **não são invocados por workflow nenhum** deste repositório:

```bash
gcloud run jobs execute pulse-migrate --region us-east1 --wait
gcloud run jobs execute pulse-check   --region us-east1 --wait
```

## 10. As allowlists do Neon e do Upstash

```bash
# **De saída**, não de entrada. Confundir os dois foi o defeito #3 da ADR 0046.
terraform output -raw ip_saida
```

Esse é o IP do Cloud NAT, por onde o Cloud Run **fala** com o mundo, e é ele que vai na
allowlist dos dois provedores. O `ip_entrada` é outro endereço, do balanceador, e é sobre
ele que os nomes `nip.io` são montados — pôr um no lugar do outro produz um ambiente em
que o nome resolve, ninguém escuta, e o login não fecha.

Sem esta etapa o Cloud Run sobe e falha ao abrir conexão, com timeout e não com recusa —
que é o modo de falha mais lento de diagnosticar.

## 11. O deploy

Com os segredos preenchidos, o realm de pé e o banco preparado, o `deploy-hml.yml`
publica as imagens reais e troca as revisões. Daí em diante os applies de infraestrutura
vão pelo `infra-hml.yml` (`workflow_dispatch` com `aplicar=true`).

---

## A borda é a Cloudflare (desde 13/08/2026)

O balanceador global da GCP foi apagado com a saída do portal do cliente: ele servia três
nomes de dois produtos, e com um produto só a conta da ADR 0048 não se sustentava. Quem
serve `app.biahflow.ai` agora é a Cloudflare — DNS proxied mais uma Origin Rule que
reescreve o `Host` para a `run.app` da `pulse-web`. Ver ADR 0053.

**Não há mais certificado gerenciado para conferir, nem IP de entrada, nem `url_map`.** As
seções que ensinavam isso saíram junto; se você chegou aqui procurando por elas, o
histórico do git as tem até o commit que apaga `modulos/borda/`.

### O apply da fundação virou um ato local

O `infra-hml.yml` autentica na GCP por WIF, e a borda nova precisa de uma segunda
credencial que aquele mecanismo não dá.

*Retificado em 17/08/2026.* Esta seção dizia que o workflow **não tem**
`CLOUDFLARE_API_TOKEN`, e a frase descrevia duas coisas de uma vez: a fiação ausente e o
segredo não cadastrado. Só a segunda continua verdadeira. O preço da primeira foi o
`plan` do `hml` reprovando a cada PR com `400 … Missing X-Auth-Key, X-Auth-Email or
Authorization headers` — um vermelho que fala de header e não diz que falta um segredo,
que é o pior formato para um portão que ninguém pode consertar sem saber disso. O
workflow agora passa `CLOUDFLARE_API_TOKEN` pelo ambiente, com o porquê escrito ao lado.

**O que falta é um ato humano, e é este:** cadastrar o secret `CLOUDFLARE_API_TOKEN` em
`biahflow/one`, com as **três** permissões que `ambientes/hml/cloudflare.tf`
mediu uma a uma contra a API — `Zone → DNS → Edit`, `Zone → Origin Rules → Edit` e
`Account → Access: Apps and Policies → Edit`. Não deduza permissão do nome do recurso:
duas delas falham de forma enganosa quando faltam, e a de `Origin Rules` chamada errada
responde `403 request is not authorized`, que manda procurar no lugar errado.

Enquanto o secret não existir, o `plan` do `hml` segue vermelho — agora por falta de
credencial e não por falta de fiação — e a fundação se aplica assim:

```bash
cd infra/terraform/ambientes/hml
export CLOUDFLARE_API_TOKEN=...          # não entra em variável: variável aparece em plano e em state
TOKEN=$(gcloud auth print-access-token --account=daniel@biahflow.ai)
GOOGLE_OAUTH_ACCESS_TOKEN="$TOKEN" terraform init -reconfigure -backend-config="access_token=$TOKEN"
GOOGLE_OAUTH_ACCESS_TOKEN="$TOKEN" terraform apply
```

O `GOOGLE_OAUTH_ACCESS_TOKEN` existe porque a ADC da máquina pode estar apontando para
outra conta; ele evita ter que refazer `gcloud auth application-default login` e derrubar
o login de trabalho de quem estiver na mesma máquina.

### O que conferir depois

```bash
# 1. O nome responde, e responde o SPA e não um 404 do Google.
curl -sI https://app.biahflow.ai/ | head -3

# 2. O 404 do Google, se aparecer, é a Origin Rule não tendo casado: a Cloudflare
#    entregou o Host original e o Cloud Run não reconheceu o nome.
#    Confira comparando com a origem crua, que tem de responder 200:
curl -sI https://pulse-web-209400815796.us-east1.run.app/ | head -3

# 3. A API por dentro. O caminho é Cloudflare → pulse-web → nginx → pulse-api,
#    e é o nginx quem reescreve o Host para a run.app da API.
curl -sI https://app.biahflow.ai/healthz | head -3
```

**Mudança de ingress não é instantânea** — a permissão de IAM leva até cerca de um minuto
para valer. Nesse intervalo a resposta pode ser 403 **do Google**, sem nada no log do
Django, porque o Django não foi chamado. Espere e repita antes de investigar; começar a
depuração na aplicação aqui é repetir o defeito #9 da ADR 0046.

### Medir o `NUM_PROXIES` (aberto)

A cadeia ficou mais longa com a troca de borda, e o valor `2` não foi corrigido porque
seria trocar um palpite por outro (ADR 0050, ADR 0053). Medir é uma requisição:

```bash
# Mande um XFF conhecido e veja o que o DRF considera ser o IP do cliente.
curl -s https://app.biahflow.ai/api/v1/... -H 'X-Forwarded-For: 203.0.113.7' | ...
```

O que se procura é `203.0.113.7` sendo lido como cliente. Se o que aparecer for um IP da
Cloudflare ou do Cloud Run, `NUM_PROXIES` está baixo demais — e o sintoma real disso não é
um erro, é todo mundo dividindo o mesmo balde de rate limit.

## Trocar o domínio

`var.dominio` é **obrigatória** desde 13/08/2026 — o `nip.io` que preenchia a lacuna era
montado sobre o IP do balanceador, e o balanceador não existe mais.

Trocar é mudar `dominio` no `terraform.tfvars` e aplicar. A zona precisa estar na
Cloudflare, e é só isso: não há certificado a reemitir (a Cloudflare já termina TLS para a
zona) e não há DNS a apontar à mão (o registro é do Terraform).

## HML dorme: o que está desligado e como acordar

Desde 13/08/2026 homologação não tem nada aceso por padrão. Duas coisas diferentes, e a
diferença é a que mais confunde:

**Serviços HTTP (`min = 0`) acordam sozinhos.** `pulse-api` e `pulse-web` sobem
quando chega requisição, em segundos. Não há o que fazer — só esperar.

**Worker pools (`instancias = 0`) NÃO acordam.** `pulse-scheduler` está desligado, e
worker pool não tem requisição que o acorde — ele só volta com um `apply`. Enquanto
estiver assim, nada agendado do CRM roda: sincronia de calendário, faturas vencidas e
frescor da base.

**Antes de testar qualquer coisa que dependa do agendador**, suba-o — senão a tarefa
simplesmente não acontece, e o sintoma não aponta para a causa:

```bash
# em ambientes/hml-biahflow/servicos.tf, pulse-scheduler: instancias = 1
cd infra/terraform/ambientes/hml-biahflow && terraform apply
```

Ele volta como **1 e nunca mais que isso** — dois agendadores emitem a mesma tarefa duas
vezes.

*Corrigido em 20/08/2026 (ADR 0065). Esta seção descrevia como acordar `portal-api`,
`portal-web`, `keycloak`, `portal-worker` e `portal-beat`, e mandava aplicar em
`ambientes/hml-portal/`, apagado em 13/08 junto com aqueles serviços — de modo que o
único comando executável dela falhava com `no such file or directory`. Também atribuía a
`ambientes/hml-portal/servicos.tf` a escolha de `min = 0` para o `keycloak`, e com ela a
frase medida "o primeiro login do dia pode levar até dois minutos" (43,6s a 115,7s de JVM,
sem `--optimized`): os números foram medidos em boots reais e ficam registrados aqui, mas
descreviam um serviço que saiu da GCP. A parte da fila do portal — scan de documento,
ingestão, sync do Drive, digest, `retention-purge`, `erasure-requests`, `onboarding-stuck`
e o aviso de backup envelhecido — volta com o produto, e o `deploy.md` é onde ela está
descrita para o compose. Em produção os pools voltam a 1 por padrão: lá, "um alerta de
backup que não roda é pior que nenhum" deixa de ser retórica.*

## A borda que dormia, e por que a seção sumiu

Existiu aqui um `var.borda_ligada` que destruía as duas regras de encaminhamento globais
para não pagá-las paradas — ~US$ 18/mês, "o único custo fixo de HML" da ADR 0046. Ele foi
aplicado em 13/08/2026 e viveu algumas horas: no mesmo dia a borda inteira saiu, e não há
mais regra de encaminhamento para desligar nem certificado gerenciado cuja renovação um
sono longo pudesse quebrar.

Fica registrado porque o raciocínio dele previu o próprio fim: "o IP de entrada permanece
reservado de propósito — isso só deixa de valer quando `var.dominio` estiver preenchida".
Foi exatamente o que aconteceu.

## Armadilhas medidas

- **A rede corporativa bloqueia `*.biahflow.ai`, e o sintoma imita defeito de TLS.** Da
  rede da Globo, `https://app.biahflow.ai` e `https://hml.biahflow.ai` fecham a conexão
  no handshake (`Recv failure: Connection reset by peer`, sem certificado oferecido) e a
  porta 80 responde **503**. Isso parece certificado ausente ou zona quebrada, e em
  13/08/2026 custou um diagnóstico inteiro errado: "o custom domain do Pages não está
  ativo", quando o site estava no ar o tempo todo.

  **O que denuncia é o corpo do 503**, não o status:

  ```bash
  curl -sI http://app.biahflow.ai/ | grep -i p3p     # P3P: CP="CAO PSA OUR"
  curl -s  http://app.biahflow.ai/ | grep -i title   # <title>Web Page Blocked</title>
  ```

  Página de bloqueio de firewall corporativo, não da Cloudflare. Para conferir de fora
  sem trocar de rede:

  ```bash
  curl -s "https://r.jina.ai/https://app.biahflow.ai/" | head -5
  ```

  O esperado é **200 com a tela de login do Cloudflare Access**. Da rede liberada, o
  mesmo hostname responde **302** — que também é sucesso, e é o Access redirecionando.

- **`ip_saida` ≠ `ip_entrada`.** Já dito no passo 10, e repetido aqui porque foi um defeito
  real, não hipotético.
- **Segredo esquecido reprova no boot, não no apply.** Ver o aviso do passo 5.
- **Segredo *sem versão* reprova o apply, e a mensagem não fala de ordem** (ADR 0050). É o
  motivo de o primeiro apply ir em dois. Não confunda com a linha acima: lá o valor está
  vazio, aqui o `latest` não existe.
- **A política da organização recusa `allUsers` antes de qualquer outra coisa** (ADR 0050).
  Sem o passo 2, o apply completo cria tudo e falha só nas quatro ligações de IAM — o
  ambiente fica de pé e responde 403 a tudo.
- **O `check --deploy` do outro repositório reprova o boot por variável ausente.** O
  `biahflow.E002` cobra o par `TRUST_X_FORWARDED_PROTO` + `NUM_PROXIES`; faltando a segunda,
  a revisão nunca fica pronta e o `gcloud run services update` falha com *"container failed
  to start and listen on the port"* — que descreve porta e não configuração. **Quando o
  Cloud Run disser isso, leia o log da revisão antes de mexer em porta.**
- **A API de habilitar APIs propaga depois de responder.** O primeiro
  `apply -target=module.fundacao` pode falhar em `google_compute_address` com
  `SERVICE_DISABLED` para a Compute Engine, que ele mesmo acabou de habilitar. Reaplicar
  resolve, e o segundo plano vem com os dois recursos que faltaram.
- **A ordem é apply → deploy → apply.** O primeiro cria com a imagem de bootstrap, o
  deploy publica a real, e os seguintes preservam a real pelo `ignore_changes`.
- **`terraform fmt -check -recursive` reprova o CI.** O `infra-hml.yml` o roda sobre a
  árvore inteira, e o job `infra-quality` do `ci.yml` também — este sem credencial, e por isso
  é o único que dá para reproduzir localmente antes de existir `WIF_PROVIDER`.

---

## Declarar HML pronta

A ADR 0045 fixou uma condição que não é "subiu": **comando/hora do Redis com a fila
vazia**. O `polling_interval` de 5 s foi escolhido por uma conta — ~17 mil comandos/dia
por instância ociosa — e aquela ADR escreveu, com todas as letras, que era *"uma promessa
a medir, não a acreditar"*.

```bash
# 15 min é o padrão de propósito: é o período do sync do Drive, então a janela contém
# exatamente um tique daquele agendador em vez de zero ou dois por sorteio.
PYTHONPATH=apps/api/src python scripts/redis_rate.py --duration 900 --instancias 1 \
  --out hml-redis-$(date +%F).json
```

Leia primeiro o campo **`notes`**, como no `loadtest.py`: é ele que diz se o número pode
ser citado. E leia `is_upstash` — contra o Redis do compose o relatório declara que aquilo
**não é** esta medição.

**A conta da ADR 0045 está incompleta, e o instrumento existe para mostrar quanto.** Ela
supõe um comando por ciclo por instância e deixa de fora o gossip/mingle/heartbeat do
Celery, o result backend (que é o mesmo Redis), os tiques do beat, e o
`pulse-scheduler` do outro produto — que aponta para o mesmo Upstash sem nenhuma ADR
ter contabilizado os comandos dele. Medido contra o compose ocioso, o total saiu **da
ordem de quinze vezes** o previsto; ali há duas sondas de healthcheck que HML não tem, e
o relatório nomeia as duas justamente para ninguém dividir por um fator qualquer e citar
o resultado como se fosse HML.

Se o número do Upstash não couber no plano contratado, a ADR 0045 já nomeou o plano B: o
Memorystore, que traz o conector de VPC de volta. A decisão é de quem paga a conta, e ela
depende deste número existir.

## O que ainda não está aqui

Nomeado para não ser confundido com feito:

- **A guarda que compara o que o compose declara com o que a infraestrutura entrega
  continua sem dono, e já são oito ocorrências.** É uma família inteira de defeito, não
  um caso: uma variável de ambiente existe no `docker-compose` e não no Terraform, e
  **nada fica vermelho** — porque o código quase sempre a lê com default vazio e desliga
  o recurso que ela habilita. O sintoma é silêncio, e silêncio é indistinguível de
  "está tudo funcionando".

  O caso que fechou a contagem foi `PORTAL_WEBHOOK_URL`, na branch
  `a-url-que-o-webhook-nao-tinha` (commit `01834d9`, 12/08/2026): a flag `portal` do CRM
  liga pela **presença** da variável, então sem ela `portal.emit` retornava na primeira
  linha e nenhum webhook saía. A branch morreu em 13/08 com o produto — `portal-api` não
  existe mais —, mas o modo de falha não morreu junto: ele vale para qualquer variável
  nova dos dois lados.

  O que resolveria é um portão comparando as duas listas, no estilo dos três que a ADR
  0051 já tem. Enquanto ele não existir, **variável nova é conferida a olho**, nos dois
  arquivos.

- **A execução completa deste runbook aconteceu em 12/08/2026**, os onze passos, e os
  tropeços entraram em *Armadilhas medidas*, na ADR 0050 e na ADR 0052. O que ela prova:
  o login do portal do cliente fecha ponta a ponta — navegador, BFF, Keycloak, troca de
  código no servidor, cookie do Auth.js, `portal-api` por dentro da VPC e Neon com RLS.
  O que ela **não** prova está logo abaixo.
- **O SMTP do realm**, que é o passo 8 e ficou por fazer. Sem ele o convite de acesso
  falha em silêncio — quem manda aquele e-mail é o Keycloak, não a aplicação.
- **O `sync_snapshot` do Biahflow.** Sem ele o portal entra e mostra "nenhum projeto
  atribuído", que é o comportamento certo e não um defeito: o portal não origina projeto.
- **O primeiro login de um usuário desconhecido é uma corrida** (ADR 0052, defeito 7). O
  BFF busca `/me` e o dashboard em paralelo e o `resolve_user` não trata inserção
  concorrente: a primeira tela dá 500 e recarregar resolve. Acerta todo usuário novo.
- **Os dois passos finais do `deploy-hml.yml` do `biahflow-portal`.** `Atualiza o agendador`
  falha por componente `beta` ausente no runner, e `Sonda as integrações` executava um job que
  o deploy nunca atualizava — logo sempre na `imagem_bootstrap`, sempre falhando, e sempre em
  silêncio, porque o passo é `continue-on-error`. Os dois têm conserto escrito lá; até ele ser
  publicado, **rode os dois à mão** depois do deploy:

  ```bash
  SHA=$(git -C ../biahflow-portal rev-parse HEAD)
  gcloud beta run worker-pools update pulse-scheduler \
    --image "us-east1-docker.pkg.dev/biahflow-hml/hml/pulse-api:$SHA" --region us-east1 --quiet
  gcloud run jobs update pulse-check \
    --image "us-east1-docker.pkg.dev/biahflow-hml/hml/pulse-api:$SHA" --region us-east1 --quiet
  gcloud run jobs execute pulse-check --region us-east1 --wait
  ```
- **O restore contra o Neon.** O `restore.sh` sabe descrever um alvo gerenciado desde a
  ADR 0048 e **não foi exercitado** contra um. Ver `backup-restore.md § Contra um Postgres
  gerenciado`.
- **A segunda barreira da `pulse-api`.** O que a ADR 0048 entrega é ingress mais
  roteamento — a `run.app` deixou de ser alcançável de fora e a borda é nossa. Não é IAM,
  e não é Cloud Armor; está declarado lá com essas palavras.
- **As três frentes públicas continuam com a `run.app` alcançável.** Fechá-las é uma linha
  cada, mas durante a emissão do primeiro certificado a `run.app` é a única forma de
  alcançar qualquer coisa — inclusive de depurar o `imagem_bootstrap` do passo 4.
- **Backup agendado.** O `backup.sh` é operação e não é agendado pelo `beat` (ADR 0019).
  Em HML na GCP isso ainda não tem casa: não há Cloud Scheduler declarado, e o alerta de
  `alerts.md` — ausência de backup bem-sucedido em 26 h — só é verdadeiro se houver quem
  execute.
