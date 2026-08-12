# ADR 0051 — Três states, um por dono

**Status:** aceito
**Data:** 12/08/2026
**Substitui:** a decisão de state único, escrita no cabeçalho do `deploy-hml.yml` do
`biahflow-portal`
**Fecha:** o `launch_stage = "BETA"` que a ADR 0045 deixou aberto
**Relacionadas:** ADR 0045 (worker no Cloud Run), ADR 0046 (o Terraform de HML),
ADR 0048 (a borda), ADR 0050 (o primeiro apply)

## Contexto

Havia um state para os dois produtos — 129 entradas num `terraform apply` só. A decisão
está escrita, e não aqui: mora no cabeçalho do `deploy-hml.yml` do outro repositório.

> "O Terraform dos dois portais mora num lugar só, porque a rede, o registro, os
> segredos e a identidade são compartilhados — **dois estados sobre os mesmos recursos**
> é como se cria drift que ninguém consegue explicar."

Repare na formulação: o argumento é contra *dois estados sobre os mesmos recursos*, não
contra dois estados. Ele descreve um modo de falha, e separar **por dono** é evitá-lo, não
incorrer nele. O que faltava era a divisão que ninguém tinha feito: dizer, recurso a
recurso, de quem é cada um.

O preço de não ter feito já era cobrado. Um `apply` de um produto podia derrubar recurso
do outro, e — mais concreto — `DATABASE_URL` e `REDIS_URL` eram **um segredo só, com um
valor só, montado nos dois**. Ninguém decidiu que os dois produtos dividiriam banco: era
o efeito de `segredos` ser uma lista, que impunha ao nome da variável de ambiente e ao
nome do segredo serem a mesma string. Isso passava despercebido porque a `portal-api`
nunca subiu, e é o motivo pelo qual o `WIF_PROVIDER` deste repositório ficou desligado:
com ele, um merge rodaria `alembic upgrade head` dentro do banco do Biahflow.

## Decisão

### Três states: fundação, e um por produto

| State | Prefixo | O que tem |
|---|---|---|
| fundação | `ambientes/hml` (**inalterado**) | APIs, VPC, NAT, os dois IPs, registro, os dois buckets, os 29 segredos, as três contas, WIF, e a borda |
| Biahflow | `ambientes/hml-biahflow` | `biahflow-api`, `biahflow-web`, dois jobs, o agendador |
| portal do cliente | `ambientes/hml-portal` | `portal-web`, `portal-api`, `keycloak`, um job, dois workers |

Prefixos diferentes no mesmo bucket: o backend GCS grava em
`<prefix>/<workspace>.tfstate`, então nada de bucket novo nem IAM novo.

**A fundação não se moveu, e essa é a parte que mais importa.** Das 129 entradas, 113
ficaram exatamente onde estavam — inclusive as caras de perder: os segredos (cujos
*valores* foram digitados à mão e não estão em repositório nenhum), o pool de WIF (o id
`github` fica 30 dias em soft-delete se destruído), o IP de entrada (de que todo nome
`nip.io` depende) e o certificado. Só **16** recursos atravessaram.

**Os três diretórios ficam neste repositório.** A separação é de raio de dano, não de
propriedade: assim `var.repositorio_infra` continua `string` e a ADR 0046 não é
contrariada.

### A borda fica na fundação, e continua uma só

Um NEG sem servidor referencia o serviço do Cloud Run **por nome** — uma string, não um
recurso. Então a fundação declara a borda inteira sem ler o state de produto nenhum, e
sem ciclo.

A alternativa, uma borda por produto, tinha preço em três lugares: dobraria as regras de
encaminhamento (o **único** custo fixo de HML), exigiria um segundo IP global e — como o
nome `nip.io` contém o IP — **mudaria os hostnames de um dos dois**, o que no portal do
cliente muda o `issuer` do Keycloak, que é passo de runbook e não de Terraform.

O preço da escolha feita, declarado: mexer numa rota exige `apply` na fundação.

### `segredos` vira mapa, e é o que separa os produtos de verdade

A chave é a variável de ambiente que o código lê; o valor é o nome do segredo. Para a
maioria os dois lados continuam iguais, e o mapa diz isso por extenso. Para as quatro
DSNs, o segredo ganha prefixo do dono — `BIAHFLOW_DATABASE_URL`, `PORTAL_DATABASE_URL` e
os pares de Redis. Renomear a variável não era opção: o nome é contrato com o código de
cada aplicação, não com o cofre.

### Os portões: o que a divisão custou, escrito

Os dois portões de segredo eram uma afirmação **global** — "todo segredo tem leitor" só é
verificável por quem enxerga todos os serviços. Nenhum state enxerga mais os dois
produtos, então eles foram divididos, e a divisão **custa alcance**:

- **Na fundação** fica a metade que ela ainda pode afirmar: todo segredo declara de que
  produto é. Sem esse dono, os portões dos produtos não teriam contra o que comparar.
- **Em cada produto** ficam os dois de sempre, sobre a lista dele: segredo lido e
  inexistente, e segredo dele que ninguém lê.
- **Um terceiro nasceu com a separação**, e é ganho e não perda: *segredo de outro
  produto lido aqui*. Antes, com um mapa só, ler o segredo do vizinho era invisível — era
  exatamente o que acontecia com o `DATABASE_URL`. Agora é erro de plano.

O que se perdeu: um segredo cujo `dono` esteja errado é lido pelo produto errado sem que
nada reprove, porque os dois lados concordam. Antes isso também não era pego, mas por
outro motivo — e vale a pena a honestidade de escrever que o portão novo não é
estritamente mais forte, é mais estreito e mais específico.

### A travessia foi `removed` + `import`, e nunca `state mv`

`removed` com `destroy = false` de um lado, `import` do outro. Os dois funcionam com
backend remoto, aparecem no `plan` e são revisáveis em PR. `terraform state mv` com
backend GCS exige `state pull`/`push`, e um `push` com `serial` errado corrompe o arquivo
de que tudo depende.

**O que se lê num plano desses é uma coisa só: `must be replaced`.** Um
`google_cloud_run_v2_service` recriado nasce com a `imagem_bootstrap` e desfaz o último
deploy, porque o `ignore_changes` da imagem só age em *update*. Nenhum dos três planos
mostrou uma.

## Consequências

- **Dois desvios perpétuos apareceram, e não eram da separação.** O `plan` de
  `ambientes/hml` nunca ficava limpo: propunha remover um bloco `scaling` de serviço que
  a API devolve preenchido com zeros e que nós nunca declaramos, e acrescentar um
  `scaling_mode` que nós declaramos e a API não devolve. Todo `apply` "resolvia" e o
  `plan` seguinte propunha de novo. Isso existia desde o primeiro apply e passou meses
  como ruído, porque um plano com dez mudanças de rotina se lê como normal. Com três
  states o custo ficou visível: **um plano que nunca fica limpo apaga a diferença entre
  "este PR não muda nada" e "este PR muda alguma coisa"**, que é o sinal inteiro do
  `infra-hml.yml`. Os dois viraram `ignore_changes` com o motivo escrito, e os campos que
  importam — `template[0].scaling` e `manual_instance_count` — continuam comparados.
- **`launch_stage = "BETA"` saiu do worker pool.** A API passou a responder `GA`, e a
  linha virou uma afirmação falsa que todo plano tentava reimpor. Era o "fica aberto" da
  ADR 0045, e quem o fechou foi a separação: o primeiro `plan` de um diretório novo lê o
  recurso vivo em vez de comparar com o que o state já dizia.
- **O CI passou a rodar em três.** O `infra-hml.yml` ganhou matriz com `max-parallel: 1`
  (os três compartilham o bucket, e a fundação é lida pelos produtos) e `fail-fast:
  false` (um plano vermelho num produto não torna menos útil ver o do outro). O
  `infra-quality` do `ci.yml` valida os três sem credencial — e o preço está declarado
  lá: sem backend não há `terraform_remote_state`, então ele prova que os módulos
  resolvem e **não** prova que as saídas lidas da fundação existem.
- **Fica aberto: o `WIF_PROVIDER` deste repositório.** O impedimento que o segurava —
  `portal-migrate` contra o banco do Biahflow — deixou de existir. Ligá-lo é o próximo
  passo, e agora é decisão e não risco.
- **Fica aberto: a `portal-api` continua na `imagem_bootstrap`.** A separação não mudou
  isso e não pretendia; o que ela mudou é que subir aquele produto passou a ser um
  `apply` que não pode alcançar este.
