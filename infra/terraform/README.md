# Infraestrutura de HML

Terraform em **duas camadas**, e a separação não é estética: é o que torna sair da GCP um
trabalho de reescrever um diretório em vez de reescrever o produto.

```
ambientes/hml/servicos.tf   ← camada portátil: o que a aplicação precisa, em termos neutros
ambientes/hml/main.tf       ← a costura, e os dois portões de segredo
modulos/fundacao/           ← como a GCP entrega rede, endereço, registro, segredo, identidade
modulos/servico-cloudrun/   ← como a GCP entrega "um serviço HTTP"
modulos/worker-pool/        ← como a GCP entrega "um processo longo sem HTTP"
modulos/job/                ← como a GCP entrega "um trabalho que começa e termina"
modulos/borda/              ← como a GCP entrega "este nome, com TLS, aponta para aquele
                              serviço — e estes caminhos dele, para aquele outro"
```

`modulos/maquina-fila/` esteve listado aqui e **nunca existiu** depois da ADR 0045: era a VM que
os worker pools substituíram, e a linha sobreviveu à remoção do diretório.

`servicos.tf` descreve os serviços sem citar GCP: nome, imagem, porta, **quem alcança**, variáveis,
segredos, quantas instâncias. Trocar de provedor é reescrever `modulos/` e manter aquele arquivo.

"Quem alcança" é `acesso`, com três valores e não um booleano (ADR 0048): `publico`, `interno` e
`balanceador`. O terceiro existe porque o segundo não serve a um serviço **cujo cliente é o
navegador** — ver a linha da `biahflow-api` na tabela abaixo.

## Por que as aplicações já são portáteis

Isto foi medido antes de escolher, e é o que sustenta a promessa acima:

- O Biahflow depende de `google-api-python-client`/`google-auth` **só** para o Google
  **Workspace** (Drive, Calendário) — não há SDK de plataforma GCP. E a ADR 0016 de lá tem o
  modo `oauth`, com client id, secret e refresh token, que roda em qualquer lugar.
- O portal do cliente usa `boto3` com `endpoint_url` configurável (`storage.py`). É protocolo
  S3, não produto: GCS, MinIO, R2 ou Tigris servem sem mudar código.
- Postgres e Redis entram por DSN. O banco de HML é **Neon**, que não é GCP.

## A forma de HML, e as três decisões que ela honra

| Peça | Onde | Por quê |
|---|---|---|
| `web` (BFF Next.js) | Cloud Run, **público** | é o único que o navegador alcança |
| `portal-api` (FastAPI) | Cloud Run, **ingress interno** + IAM | o `Caddyfile` diz por extenso que a API não é pública: quem fala com ela é o BFF, que sabe apresentar identidade. Publicá-la daria à internet um caminho que o produto não usa |
| `keycloak` | Cloud Run, público, `KC_PROXY=edge` | TLS termina na borda, e acreditar nisso é opt-in (ADR 0011) |
| `biahflow-web` (SPA em nginx) | Cloud Run, público | serve o `index.html` e os `assets/` do outro produto em `app.<base>` |
| `biahflow-api` (Django) | Cloud Run, **ingress de balanceador** | o cliente dela é **o navegador**, e para esse cliente IAM invoker não é barreira: nginx não emite ID token e um NEG sem servidor também não. A `run.app` deixa de ser alcançável de fora e `/api|/admin|/static|/healthz|/readyz` de `app.<base>` chegam pela nossa borda (ADR 0046, ADR 0048) |
| `worker` + `beat` | **Cloud Run worker pool** | a primitiva feita para carga longa sem HTTP — o container de um worker pool nem tem bloco `ports`. Uma versão anterior deste arquivo os mandava para uma VM, sobre a conclusão errada de que o Cloud Run não os aceitava (ADR 0045) |
| Redis | **Upstash**, externo | cobrado por comando, então o `polling_interval` do Celery foi afrouxado para 5s — um worker ocioso a 1s gera ~86 mil comandos/dia sem trabalho nenhum |
| documentos | Cloud Storage | S3-compatível por HMAC. Resolve de carona um ponto que o `Caddyfile` deixou em aberto: a URL assinada **cobre o host**, e o MinIO não era publicado |
| Postgres | Neon, externo | ver ADR 0044 — o `roles.sql` foi verificado lá |
| rede | VPC + **egress direto** + Cloud NAT | a VPC existe por um motivo só: fazer o ingress interno das APIs significar alguma coisa. Vale para as duas — o `INTERNAL_LOAD_BALANCER` da `biahflow-api` é superconjunto do `INTERNAL_ONLY` e é por dentro da VPC que a `portal-api` a alcança. Sem conector — ele é peça paga, e worker pool nem o aceita |

## O domínio

Ainda não há um. `var.dominio` vazio faz tudo cair em **`nip.io`** sobre o IP de **entrada** do
balanceador, que dá nome estável o bastante para o OIDC funcionar. Quando o domínio existir, é
**uma variável**: o `terraform apply` reemite o certificado e refaz as regras de host.

Duas coisas que esta seção afirmava e não eram verdade, e que o `modulos/borda/` conserta:

- **O IP era o de saída**, do Cloud NAT — o endereço por onde o Cloud Run *fala* com o Neon e o
  Upstash, e onde serviço nenhum escuta. O nome resolvia e não respondia, então o login OIDC não
  fechava. Agora há um `hml-entrada` global, e é sobre ele que o `nip.io` é montado.
- **Não havia mapeamento nenhum.** A frase "o `terraform apply` refaz os mapeamentos" descrevia
  código que não existia: `servicos.tf` declarava uma chave `dominio` por serviço e a costura
  nunca a lia. O caminho não podia ser `google_cloud_run_domain_mapping`, que exige verificação
  de posse no Search Console e `nip.io` não é nosso; é balanceador HTTPS externo com NEGs sem
  servidor, cujo certificado gerenciado se valida por resolução DNS até o IP — o que o `nip.io`
  satisfaz por construção. O preço é uma regra de encaminhamento global, único custo fixo de HML.

O que **não** é automático na troca: o realm do Keycloak guarda `redirectUris` e o `issuer`, e
os dois `.env` guardam `KEYCLOAK_ISSUER` e `PORTAL_WEB_URL`. Está no runbook.

## Os dois portões

`ambientes/hml/main.tf` reprova o plano quando um segredo é referenciado por um serviço e não é
criado, **e** quando um segredo é criado e nenhum serviço o lê. As duas direções já falharam:
`ANTHROPIC_API_KEY` e `VOYAGE_API_KEY` existiam no cofre sem chegar a ninguém — o respondedor
ficava offline em silêncio, que é o que a ADR 0022 existe para impedir — e o segredo do BFF era
entregue com um nome que o `auth.ts` não lê. São `precondition` e não `check`: `check` só emite
warning, e um portão que não reprova é decoração.

## As identidades

Duas contas, e a divisão é a dos dois workflows: `hml-deploy` publica imagem e troca revisão,
`hml-infra` roda o `terraform apply`. Antes havia só a primeira, e era ela que o `infra-hml.yml`
usava — com as quatro permissões de deploy, que não criam sub-rede, conta de serviço nem pool de
WIF. Só o repositório que **contém** o Terraform federa a `hml-infra`.

## Estado

Bucket GCS com versionamento. O bucket **não** é criado por este Terraform — ovo e galinha; ele
é criado uma vez à mão e o comando está no `ambientes/hml/backend.tf`.

## Uso

```bash
cd ambientes/hml
cp terraform.tfvars.example terraform.tfvars   # e preencha; nenhum segredo entra aqui
terraform init
terraform plan
```

Os segredos vão para o Secret Manager por fora (`gcloud secrets versions add`), e o Terraform só
os **referencia**. O `preflight.py` recusa subir com segredo de exemplo (ADR 0022), então um
segredo esquecido vira falha de boot e não vazamento.

## O primeiro apply é local, e não é preferência

O `infra-hml.yml` se autentica por Workload Identity Federation — e **o pool de WIF é criado por
este Terraform**. Antes do primeiro apply não existe a credencial que o CI usaria para aplicar,
então o primeiro apply sai de uma máquina, com credencial de pessoa. Só depois o `provedor_wif`
existe para ir na variável `WIF_PROVIDER` dos dois repositórios, e o CI passa a se sustentar.

Na mesma linha, `tag_imagem` vazia é o caso do primeiro apply: o Artifact Registry ainda está
vazio, e um serviço criado apontando para tag inexistente tem a revisão recusada pelo Cloud Run.
Vazio significa `imagem_bootstrap` (o `hello` da Google), e o `ignore_changes` de cada módulo
garante que nenhum apply posterior a traga de volta por cima da imagem que o deploy publicou.

A ordem inteira, com o que é manual e por quê, está em `docs/runbooks/hml-gcp.md`.
