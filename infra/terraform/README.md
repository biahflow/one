# Infraestrutura de HML

Terraform em **duas camadas**, e a separação não é estética: é o que torna sair da GCP um
trabalho de reescrever um diretório em vez de reescrever o produto.

```
ambientes/hml/              ← a fundação: o que é do projeto e não de um produto, mais a borda
ambientes/hml-biahflow/     ← o portal operacional: serviços, jobs, agendador
    <cada um>/servicos.tf   ← camada portátil: o que a aplicação precisa, em termos neutros
    <cada um>/main.tf       ← a costura, e os portões
modulos/fundacao/           ← como a GCP entrega rede, endereço, registro, segredo, identidade
modulos/servico-cloudrun/   ← como a GCP entrega "um serviço HTTP"
modulos/worker-pool/        ← como a GCP entrega "um processo longo sem HTTP"
modulos/job/                ← como a GCP entrega "um trabalho que começa e termina"
```

`modulos/maquina-fila/` esteve listado aqui e **nunca existiu** depois da ADR 0045: era a VM que
os worker pools substituíram, e a linha sobreviveu à remoção do diretório.

*Acrescentado em 20/08/2026 (ADR 0064): e aconteceu de novo, duas vezes, exatamente pelo motivo
que o parágrafo acima descreve — o desenho listava `ambientes/hml-portal/`, apagado em 13/08 com o
produto (ADR 0053), e `modulos/borda/`, apagado no mesmo dia quando a borda virou Cloudflare. A
correção de então foi à mão e não deixou portão, que é a forma da ADR 0034. Agora quem cobra é
`apps/api/tests/test_architecture_doc.py`: todo caminho desenhado num bloco de estrutura tem de
existir, com o corpus achado pela **forma** do bloco e não por uma lista de arquivos — e é por
morar na prosa, fora da fence, que esta linha continua aqui em vez de a guarda exigir que o
repositório apague o registro do próprio erro.*

**São dois states**, um por dono, em prefixos do mesmo bucket. A fundação não lê ninguém; cada
produto lê **só as saídas** dela, e nunca o outro produto. É o que faz um `apply` de um portal não
alcançar o outro — e o que forçou cada um a ter a própria DSN, porque dois states não podem ambos
ser donos de um segredo chamado `DATABASE_URL`.

Foram **três** entre a ADR 0051 e 13/08/2026, quando o `ambientes/hml-portal/` saiu com o produto
(ADR 0053). O desenho é o mesmo com dois: a razão dele é a fronteira entre donos, não a
quantidade.

`servicos.tf` descreve os serviços sem citar GCP: nome, imagem, porta, **quem alcança**, variáveis,
segredos, quantas instâncias. Trocar de provedor é reescrever `modulos/` e manter aquele arquivo.

"Quem alcança" é `acesso`, com quatro valores e não um booleano (ADR 0048): `publico`, `interno`,
`interno-sem-iam` e `balanceador`. O `balanceador` existe porque o `interno` não serve a um serviço
**cujo cliente é o navegador** — ver a linha da `cockpit-api` na tabela abaixo —, e o
`interno-sem-iam` porque nem todo chamador de dentro da VPC sabe apresentar identidade.

*Corrigido em 20/08/2026 (ADR 0064): este parágrafo dizia "três valores" e nomeava três, enquanto
o `validation` de `modulos/servico-cloudrun/main.tf` aceita quatro desde a ADR 0048. O quarto,
`interno-sem-iam`, é justamente o da `cockpit-api`, que é a linha para a qual o parágrafo mandava
olhar.*

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
| `cockpit-web` (SPA em nginx) | Cloud Run, **público** | é o único que o navegador alcança direto; serve o `index.html` e os assets em `app.<base>` |
| `cockpit-api` (Django) | Cloud Run, **`interno-sem-iam`** | o cliente dela é **o navegador**, e para esse cliente IAM invoker não é barreira: nginx não emite ID token e um NEG sem servidor também não. A `run.app` deixa de ser alcançável de fora, e os caminhos de `app.<base>` chegam pela nossa borda (ADR 0046, ADR 0048) |
| `cockpit-scheduler` | **Cloud Run worker pool** | a primitiva feita para carga longa sem HTTP — o container de um worker pool nem tem bloco `ports`. Uma versão anterior deste arquivo o mandava para uma VM, sobre a conclusão errada de que o Cloud Run não os aceitava (ADR 0045) |
| `cockpit-migrate`, `cockpit-check` | **Cloud Run job** | começam e terminam: a migração e o `check --deploy` do deploy |
| Redis | **Upstash**, externo | cobrado por comando, então o `polling_interval` do Celery foi afrouxado para 5s — um worker ocioso a 1s gera ~86 mil comandos/dia sem trabalho nenhum |
| documentos | Cloud Storage | S3-compatível por HMAC. Resolve de carona um ponto que o `Caddyfile` deixou em aberto: a URL assinada **cobre o host**, e o MinIO não era publicado |
| Postgres | Neon, externo | ver ADR 0044 — o `roles.sql` foi verificado lá |
| rede | VPC + **egress direto** + Cloud NAT | a VPC existe por um motivo só: fazer o ingress interno da API significar alguma coisa — é por dentro dela que o nginx da SPA alcança a `cockpit-api`. Sem conector — ele é peça paga, e worker pool nem o aceita |

*Corrigido em 20/08/2026 (ADR 0064): esta tabela listava `web`, `portal-api`, `keycloak`, `worker`
e `beat` como peças de HML, e eles saíram em 13/08 com o produto (ADR 0053); e chamava os dois
serviços que ficaram de `biahflow-web` e `biahflow-api`, nomes que deixaram de existir em 19/08.
Nenhum dos cinco primeiros estava só errado no papel: a tabela é o que alguém abre para saber o
que a HML tem. O portão que passou a cobrar isto exige que todo nome citado aqui seja chave de
algum `servicos.tf` — e a versão ingênua dele, que perguntava se o nome aparecia em algum `.tf`,
foi **medida e recusada**, porque `portal-api` e `keycloak` sobrevivem em comentários de
histórico e ela nasceria verde sobre este defeito exato.*

## O domínio

Há um: a borda é a **Cloudflare** desde 13/08/2026 (ADR 0053), na zona que já era do site de
marketing, e o nome do produto operacional entra como registro de DNS mais rota de Worker em
`ambientes/hml/cloudflare.tf`. O TLS termina lá, e é lá que o Zero Trust Access decide quem passa.

*Corrigido em 20/08/2026 (ADR 0064): o parágrafo abaixo descrevia a borda **anterior** — o
balanceador HTTPS global da Google, com `hml-entrada`, certificado gerenciado e `nip.io` — como se
fosse a de hoje, e apontava para um `modulos/borda/` apagado junto com ela. Fica como registro do
que se aprendeu ali, e não como descrição do ambiente: as duas correções que ele narra são
verdadeiras sobre aquela borda.*

Duas coisas que esta seção afirmava e não eram verdade, e que a borda de então consertou:

- **O IP era o de saída**, do Cloud NAT — o endereço por onde o Cloud Run *fala* com o Neon e o
  Upstash, e onde serviço nenhum escuta. O nome resolvia e não respondia, então o login OIDC não
  fechava. Agora há um `hml-entrada` global, e é sobre ele que o `nip.io` é montado.
- **Não havia mapeamento nenhum.** A frase "o `terraform apply` refaz os mapeamentos" descrevia
  código que não existia: `servicos.tf` declarava uma chave `dominio` por serviço e a costura
  nunca a lia. O caminho não podia ser `google_cloud_run_domain_mapping`, que exige verificação
  de posse no Search Console e `nip.io` não é nosso; é balanceador HTTPS externo com NEGs sem
  servidor, cujo certificado gerenciado se valida por resolução DNS até o IP — o que o `nip.io`
  satisfaz por construção. O preço é uma regra de encaminhamento global, único custo fixo de HML.

O que **não** era automático na troca, enquanto havia Keycloak aqui: o realm guarda
`redirectUris` e o `issuer`, e os dois `.env` guardam `KEYCLOAK_ISSUER` e `PORTAL_WEB_URL`. Está
no runbook, e volta a valer quando o portal do cliente voltar.

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
cd ambientes/hml                                # a fundação primeiro: os produtos leem as saídas dela
cp terraform.tfvars.example terraform.tfvars    # e preencha; nenhum segredo entra aqui
terraform init && terraform plan

cd ../hml-biahflow && terraform init && terraform plan   # depois cada produto, em qualquer ordem
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

**Um plano limpo é sinal, e custou trabalho.** Até a ADR 0051 os planos nunca ficavam vazios: dois
campos de escalonamento iam e voltavam a cada apply, por assimetria entre o que declaramos e o que
a API devolve. Com dez mudanças de rotina em todo plano, ninguém distinguia "este PR não muda nada"
de "este PR muda alguma coisa". Hoje os três saem `No changes` — se um deles não sair, é porque
alguma coisa mudou de verdade.
