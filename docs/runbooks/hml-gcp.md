# Runbook — subir a homologação na GCP

ADR 0044, 0045, 0046, 0048 e 0050. A infraestrutura é definida em `infra/terraform/`, em duas
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

**Só a fundação, e a razão é o passo seguinte** (ADR 0050). O Terraform cria os 26 segredos
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

## 5. Os 26 segredos

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

`DATABASE_URL` e `REDIS_URL` vêm do Neon e do Upstash, e são **compartilhados** entre a
`portal-api` e a `biahflow-api`.

> **Um segredo esquecido não reprova no apply.** Os portões de `ambientes/hml/main.tf`
> pegam segredo referenciado e não criado, e segredo criado sem leitor — nenhum dos dois
> olha o *valor*. Quem pega valor vazio é o `preflight.py`, no **boot do processo**, e
> por isso o sintoma é um serviço que não sobe, não um plano vermelho. Os três motivos de
> recusa estão em `deploy.md § Quando a subida é recusada`, e valem igual aqui.

**Um segredo que este ambiente não usa ainda precisa de versão.** Os 26 servem aos dois
produtos; se você está subindo só um deles, os do outro recebem um valor de marcação. É a
existência da versão que o Cloud Run cobra, não o conteúdo — ver o passo 4.

**Acrescentar um segredo depois repete o mesmo par de passos, e pela mesma razão.** O nome
entra em `variables.tf` e na lista `segredos` do serviço **no mesmo commit** (senão um dos
portões reprova o plano), mas o `apply` vai em dois: `-target=module.fundacao` cria o
segredo, `gcloud secrets versions add` lhe dá versão, e só então o apply completo o monta.
Foi assim que o `EMAIL_HOST_PASSWORD` entrou.

## 6. O apply completo

```bash
terraform apply
```

Agora sim os serviços, os jobs, os worker pools e a borda. Eles sobem **quebrados** neste
momento, e isso é esperado: o realm não existe (passo 8) e o banco ainda não tem os papéis
(passo 9).

## 7. O `WIF_PROVIDER`, nos dois repositórios

```bash
# O que prova que o CI vai conseguir se autenticar sem chave de conta de serviço.
terraform output -raw provedor_wif
```

O valor vai na variável de repositório `WIF_PROVIDER` de **`biahflow-portal-cliente` e
`biahflow-portal`**. São dois, e esquecer o segundo faz o deploy do outro produto falhar
na primeira linha do primeiro job — com uma mensagem sobre credencial, não sobre variável
ausente.

Só o repositório que **contém** o Terraform federa a `hml-infra`; o outro recebe apenas a
`hml-deploy`. A separação é da ADR 0046 e não é cosmética: a `hml-infra` tem quase o
projeto inteiro.

## 8. O realm `portal-homolog`

O Terraform **não** cria o realm: não há provider de Keycloak neste repositório. O realm
versionado (`infra/keycloak/portal-local-realm.json`) é o **local** e não serve — ele tem
`sslRequired: none` e senhas conhecidas.

```bash
terraform output -json hosts   # o `keycloak` daqui é o issuer que a API valida
```

O passo 2 do `deploy.md` descreve o que criar, item por item, e vale inteiro: o realm, o
client confidencial `portal-web` com o `redirect_uri` e o **mapper de audiência** para
`portal-api`, e o client `portal-admin` com service account mais `manage-users` e
`view-users` em `realm-management`. Duas diferenças aqui:

- o nome do realm é `portal-homolog`, e ele mora num lugar só (`servicos.tf`), com
  `issuer` e `jwks_url` derivados — três nomes para a mesma coisa foi o defeito #6 da ADR
  0046, e o sintoma é a API recusar todo acesso com uma mensagem sobre **assinatura**;
- o `redirect_uri` usa o host de `terraform output hosts`, não `localhost`.

**O SMTP é configuração do realm, e é passo deste runbook.** `SMTP_HOST` fica vazio nos
serviços de propósito (ADR 0046) — não há SMTP de aplicação em HML —, mas o convite de
acesso continua saindo, porque quem o manda é o Keycloak. Sem o SMTP do realm, convidar
alguém falha em silêncio: ver `auth-failure.md`.

## 9. O `roles.sql` contra o Neon

Não há Cloud Run Job que faça isto, e as senhas de papel não estão entre os 26 segredos —
é passo de pessoa, uma vez, com a credencial administrativa do Neon.

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
gcloud run jobs execute biahflow-migrate --region us-east1 --wait
gcloud run jobs execute biahflow-check   --region us-east1 --wait
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

## Conferir o certificado

A primeira emissão leva **de quinze minutos a uma hora**. Nesse intervalo o HTTPS
responde **erro de certificado, e não erro de rota** — quem não souber disso vai depurar
a coisa errada, que é o motivo de esta seção existir.

Na primeira execução real (12/08/2026) os três nomes saíram `ACTIVE` em **poucos minutos**.
A faixa acima fica porque é o pior caso do Google e o engano que ela evita é caro; mas não
espere uma hora antes de olhar.

```bash
# ACTIVE é o que se espera. PROVISIONING é normal na primeira hora.
gcloud compute ssl-certificates describe hml --global \
  --format='value(managed.status, managed.domainStatus)'
```

`FAILED_NOT_VISIBLE` num domínio significa que ele não resolve para o IP de entrada. Com
`nip.io` isso é por construção — se acontecer, o nome foi montado sobre o IP errado (ver
passo 10).

## Depois do apply da borda

Mudar o ingress de um serviço ou as rotas do `url_map` **não é instantâneo**: a permissão
de IAM leva até cerca de um minuto para valer, e uma alteração de balanceador global leva
de segundos a alguns minutos para alcançar todos os pontos de presença. Nesse intervalo
`https://app.<base>/api/v1/...` pode responder 403 ou 404 **do Google**, sem nada no log
do Django — porque o Django não foi chamado.

Espere e repita antes de investigar. Começar a depuração na aplicação, aqui, é repetir o
defeito #9 da ADR 0046.

**A ordem importa quando as duas coisas mudam juntas** (ADR 0048). O ingress
`INTERNAL_LOAD_BALANCER` é superconjunto de `INTERNAL_ONLY`, então aplicá-lo sozinho não
muda nada observável; já o `url_map` apontando para um serviço que ainda é `INTERNAL_ONLY`
responde 404 até o outro recurso existir. Por isso, em dois:

```bash
terraform apply -target=module.servicos    # 1. ingress e IAM, reversível e invisível
terraform apply                            # 2. NEG, backend service e url_map
```

## Trocar o domínio

Enquanto `var.dominio` for `""`, tudo cai em `nip.io` sobre o IP de entrada. Com domínio
próprio:

1. `dominio = "exemplo.com"` no `terraform.tfvars` e `terraform apply`. O certificado é
   **recriado** — a lista de nomes mudou —, então conte outra vez com os 15 a 60 minutos.
2. Aponte o DNS dos três nomes para `terraform output -raw ip_entrada`.
3. **O que o Terraform não faz:** o realm guarda os `redirectUris` do client `portal-web`
   e o próprio `issuer`. Os dois têm de ser ajustados à mão no Keycloak, e enquanto não
   forem, o login para de fechar — a API recusa um token cujo `iss` não é o que ela
   valida.

## Armadilhas medidas

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
`biahflow-scheduler` do outro produto — que aponta para o mesmo Upstash sem nenhuma ADR
ter contabilizado os comandos dele. Medido contra o compose ocioso, o total saiu **da
ordem de quinze vezes** o previsto; ali há duas sondas de healthcheck que HML não tem, e
o relatório nomeia as duas justamente para ninguém dividir por um fator qualquer e citar
o resultado como se fosse HML.

Se o número do Upstash não couber no plano contratado, a ADR 0045 já nomeou o plano B: o
Memorystore, que traz o conector de VPC de volta. A decisão é de quem paga a conta, e ela
depende deste número existir.

## O que ainda não está aqui

Nomeado para não ser confundido com feito:

- **A execução completa deste runbook.** Os passos 1 a 7 foram percorridos contra a GCP em
  12/08/2026, e os três tropeços que apareceram estão em *Armadilhas medidas* e na ADR 0050.
  **Os passos 8 a 11 não foram**: o realm, o `roles.sql` e o deploy do portal do cliente
  seguem sem execução, porque aquela rodada subiu só o `biahflow-portal`. O
  `biahflow-migrate` rodou contra o Neon e passou — é a única prova de que a saída pelo
  Cloud NAT alcança o provedor gerenciado.
- **Os dois passos finais do `deploy-hml.yml` do `biahflow-portal`.** `Atualiza o agendador`
  falha por componente `beta` ausente no runner, e `Sonda as integrações` executava um job que
  o deploy nunca atualizava — logo sempre na `imagem_bootstrap`, sempre falhando, e sempre em
  silêncio, porque o passo é `continue-on-error`. Os dois têm conserto escrito lá; até ele ser
  publicado, **rode os dois à mão** depois do deploy:

  ```bash
  SHA=$(git -C ../biahflow-portal rev-parse HEAD)
  gcloud beta run worker-pools update biahflow-scheduler \
    --image "us-east1-docker.pkg.dev/biahflow-hml/hml/biahflow-api:$SHA" --region us-east1 --quiet
  gcloud run jobs update biahflow-check \
    --image "us-east1-docker.pkg.dev/biahflow-hml/hml/biahflow-api:$SHA" --region us-east1 --quiet
  gcloud run jobs execute biahflow-check --region us-east1 --wait
  ```
- **O restore contra o Neon.** O `restore.sh` sabe descrever um alvo gerenciado desde a
  ADR 0048 e **não foi exercitado** contra um. Ver `backup-restore.md § Contra um Postgres
  gerenciado`.
- **A segunda barreira da `biahflow-api`.** O que a ADR 0048 entrega é ingress mais
  roteamento — a `run.app` deixou de ser alcançável de fora e a borda é nossa. Não é IAM,
  e não é Cloud Armor; está declarado lá com essas palavras.
- **As três frentes públicas continuam com a `run.app` alcançável.** Fechá-las é uma linha
  cada, mas durante a emissão do primeiro certificado a `run.app` é a única forma de
  alcançar qualquer coisa — inclusive de depurar o `imagem_bootstrap` do passo 4.
- **Backup agendado.** O `backup.sh` é operação e não é agendado pelo `beat` (ADR 0019).
  Em HML na GCP isso ainda não tem casa: não há Cloud Scheduler declarado, e o alerta de
  `alerts.md` — ausência de backup bem-sucedido em 26 h — só é verdadeiro se houver quem
  execute.
