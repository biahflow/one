# ADR 0070 — O rename que a guarda atravessou

**Status:** aceito
**Data:** 25/08/2026
**Fase:** 7 — infraestrutura de HML do CRM
**Completa:** ADR 0065 · **Contexto:** ADR 0030 e ADR 0035 do `biahflow/pulse`

## Contexto

Os cinco recursos de HML do CRM se chamavam `cockpit-api`, `cockpit-web`,
`cockpit-scheduler`, `cockpit-migrate` e `cockpit-check`. O nome vinha do repositório, que a
ADR 0030 daquele produto rebatizou de `portal` para `cockpit` em 19/08/2026 — e que em
24/08/2026 virou `pulse`, junto com o nome do produto (ADR 0035 de lá). Os recursos ficaram
com o nome do meio.

A pergunta chegou de fora, em `biahflow/pulse#34`, e a primeira resposta que ela recebeu
estava errada: que estes recursos não estavam em Terraform. Estão, aqui, desde sempre — em
`ambientes/hml-biahflow/`. O que confundiu foi o repositório: quem procura a infraestrutura do
portal **operacional** procura no repositório dele, depois no que se chama `infra`, e não no do
portal **do cliente**. A ADR 0044 de lá registra essa fronteira; esta registra o rename.

**O que torna este movimento diferente do de 19/08 é que agora existe uma guarda.** Naquele,
o rename tocou um arquivo só — o `servicos.tf` — e `ambientes/hml/cloudflare.tf` ficou
montando a origem da borda com `biahflow-web-<número>.run.app`, nome que nenhum `servicos.tf`
declarava. Ninguém viu, porque uma string não é referência e nada fica vermelho quando ela
deriva. A ADR 0065 diagnosticou aquilo e deixou o portão:
`test_every_service_name_the_repository_builds_or_invokes_is_declared`, que exige que o
primeiro segmento de um hostname `run.app` e o argumento posicional de
`gcloud run <espécie> <verbo> <nome>` sejam chave de algum `servicos.tf`.

**O custo daquele silêncio foi medido, e não foi barato.** A correção da ADR 0065 entrou no
código em 20/08 e o `apply` nunca rodou — a credencial pedia reauth, e autenticar é ato de
pessoa. Em 25/08/2026 a borda ainda apontava para `biahflow-web`: o `plan` de
`ambientes/hml` mostrava o registro DNS e o `const ORIGEM` do worker com o nome morto. Seis
dias. O que escondeu foi o Cloudflare Access, que responde 302 antes de a origem ser
exercida — nenhuma sonda anônima chega a falhar.

## Decisão

### 1. Os cinco recursos passam a se chamar `pulse-*`

`servicos.tf` renomeia as chaves de `local.servicos_http`, `local.processos_longos` e
`local.trabalhos`. Os derivados acompanham sozinhos, e isso não é sorte: `url_interna`,
`host_interno`, `DJANGO_ALLOWED_HOSTS` e `API_UPSTREAM` saem da chave por interpolação, que é
a razão de a camada portátil descrever o serviço por nome e não por literal.

O nome do serviço **não é superfície de usuário**: quem o navegador digita é
`app.biahflow.ai`, que a fundação define e a Cloudflare serve. O que muda de endereço é a
`run.app`, que só a borda e o nginx da SPA conhecem.

### 2. A borda muda no mesmo lote, e a guarda é quem garante

`ambientes/hml/cloudflare.tf` é outro state, e é exatamente o arquivo que ficou para trás da
outra vez. Ele muda no mesmo PR. **E o que garante que mudou não é lembrança de ninguém:** a
mutação foi exercida antes de escrever esta ADR — devolver `cockpit-web` àquela linha reprova
o `api-quality` com o sítio, o arquivo e a linha na mensagem. Da primeira vez o defeito
atravessou seis dias em silêncio; da segunda ele não passou do CI.

### 3. Serviço novo nasce com a imagem de bootstrap, e é o outro repositório que o preenche

Renomear em Cloud Run é `destroy` mais `create`. Os `pulse-*` nascem com `imagem_bootstrap`,
porque `infra-hml.yml` roda **sem** `-var tag_imagem` — a mesma ausência que permite o
primeiro apply de qualquer serviço. Quem publica a imagem real é o `deploy-hml.yml` do
`biahflow/pulse`, e é por isso que a ordem importa e está escrita abaixo.

**Há janela de indisponibilidade em HML**, entre o `apply` e o deploy seguinte daquele
repositório. Ela é inerente ao `destroy`/`create`, não um efeito colateral a consertar.

### 4. A narrativa histórica não é reescrita

`cloudflare.tf:23`, `ROADMAP.md`, as docstrings de `test_architecture_doc.py` e o cabeçalho do
runbook continuam dizendo que os serviços já se chamaram `biahflow-*` e `cockpit-*`. Renomear
o registro do próprio erro é o que a ADR 0034 recusa, e é o mesmo critério que a ADR 0065
aplicou aos comentários de HCL: corrige-se a afirmação **viva**, preserva-se a **nota
histórica**.

## Ordem de execução

```text
1. merge deste PR
2. apply de ambientes/hml-biahflow   → destrói cockpit-*, cria pulse-* com bootstrap
3. apply de ambientes/hml            → borda passa a apontar para pulse-web
4. merge do PR de biahflow/pulse     → deploy-hml publica as imagens reais em pulse-*
```

Entre 2 e 4, `app.biahflow.ai` serve o container de bootstrap. Entre 2 e 4 também, qualquer
merge na `main` do `biahflow/pulse` que dispare o `deploy-hml` **antes** do PR de lá falha,
porque o workflow ainda nomeia `cockpit-api`. Os dois PRs são preparados juntos por isso.

`apply` continua Human Gate: `infra-hml.yml` com `aplicar: true`, humano com o plano na frente.

## Consequências

- A `run.app` do CRM muda de endereço. Quem tiver a antiga em favorito, script ou
  `curl` de runbook precisa da nova — e o runbook já vem corrigido neste PR, porque a guarda
  não deixaria passar de outro jeito.
- O registro de imagens passa a receber `pulse-api` e `pulse-web`. Os digests publicados sob
  o caminho antigo continuam endereçáveis; a evidência de release já emitida não é reescrita.
- **A guarda da ADR 0065 deixou de ser hipótese.** Ela foi escrita depois de um defeito e
  agora atravessou o movimento que o teria recriado. É a diferença entre um portão que existe
  e um portão que se sabe que funciona.
- Fica aberto o que aquela ADR já nomeava e continua valendo: **o outro lado do rename mora em
  `biahflow/pulse` e nenhum portão daqui o vê.** Que os dois repositórios concordem continua
  sendo conferido a olho — e desta vez o que os manteve juntos foi um par de PRs escrito na
  mesma sessão, que não é mecanismo.

## Verificação

- `apps/api/tests/test_architecture_doc.py` e `test_roadmap_index.py` — 12/12.
- **Mutação exercida:** `origem_do_crm` devolvido a `cockpit-web` reprova com
  *"estes sítios nomeiam um serviço do Cloud Run que nenhum `servicos.tf` declara:
  infra/terraform/ambientes/hml/cloudflare.tf:62 constrói `cockpit-web`"*. Restaurado em
  seguida.
- `terraform fmt -check -recursive` — sem deriva.
- Os dois `plan` publicados no PR. **Nenhum `apply` foi executado.**
