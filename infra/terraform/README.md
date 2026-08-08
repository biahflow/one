# Infraestrutura de HML

Terraform em **duas camadas**, e a separação não é estética: é o que torna sair da GCP um
trabalho de reescrever um diretório em vez de reescrever o produto.

```
ambientes/hml/servicos.tf   ← camada portátil: o que a aplicação precisa, em termos neutros
ambientes/hml/main.tf       ← a costura
modulos/fundacao/           ← como a GCP entrega rede, registro, segredo, identidade
modulos/servico-cloudrun/   ← como a GCP entrega "um serviço HTTP"
modulos/maquina-fila/       ← como a GCP entrega "um processo longo + Redis"
```

`servicos.tf` descreve os serviços sem citar GCP: nome, imagem, porta, se é público, variáveis,
segredos, quantas instâncias. Trocar de provedor é reescrever `modulos/` e manter aquele arquivo.

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
| `api` (FastAPI) | Cloud Run, **ingress interno** | o `Caddyfile` diz por extenso que a API não é pública: quem fala com ela é o BFF. Publicá-la daria à internet um caminho que o produto não usa |
| `keycloak` | Cloud Run, público, `KC_PROXY=edge` | TLS termina na borda, e acreditar nisso é opt-in (ADR 0011) |
| `worker` + `beat` | **Cloud Run worker pool** | a primitiva feita para carga longa sem HTTP — o container de um worker pool nem tem bloco `ports`. Uma versão anterior deste arquivo os mandava para uma VM, sobre a conclusão errada de que o Cloud Run não os aceitava (ADR 0045) |
| Redis | **Upstash**, externo | cobrado por comando, então o `polling_interval` do Celery foi afrouxado para 5s — um worker ocioso a 1s gera ~86 mil comandos/dia sem trabalho nenhum |
| documentos | Cloud Storage | S3-compatível por HMAC. Resolve de carona um ponto que o `Caddyfile` deixou em aberto: a URL assinada **cobre o host**, e o MinIO não era publicado |
| Postgres | Neon, externo | ver ADR 0044 — o `roles.sql` foi verificado lá |
| rede | VPC + **egress direto** + Cloud NAT | a VPC existe por um motivo só: fazer o `INGRESS_TRAFFIC_INTERNAL_ONLY` das APIs significar alguma coisa. Sem conector — ele é peça paga, e worker pool nem o aceita |

## O domínio

Ainda não há um. `var.dominio` vazio faz tudo cair em **`nip.io`** sobre o IP de saída, que dá
nome estável o bastante para o OIDC funcionar. Quando o domínio existir, é **uma variável**: o
`terraform apply` refaz os mapeamentos e as URLs.

O que **não** é automático na troca: o realm do Keycloak guarda `redirectUris` e o `issuer`, e
os dois `.env` guardam `KEYCLOAK_ISSUER` e `PORTAL_WEB_URL`. Está no runbook.

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
