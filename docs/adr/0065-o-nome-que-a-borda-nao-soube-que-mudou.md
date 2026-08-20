# ADR 0065 — O nome que a borda não soube que mudou

**Status:** aceito
**Data:** 20/08/2026
**Fase:** 7 — e a quinta ADR aceita neste dia, depois da 0061, da 0062, da 0063 e da 0064

## Contexto

A ADR 0064 foi aceita hoje. Ela deixou portão para "documento que descreve a estrutura é
conferido contra o repositório", e nomeou como defeito, com todas as letras, a linha
`cd ../hml-portal` do `infra/terraform/README.md` — *"uma instrução que **falha**"*. A
mesma linha continuava em `docs/runbooks/hml-gcp.md:162`, porque o corpus da asserção (b)
daquela guarda são as fences de **estrutura**, e um runbook não desenha diretório: ele
navega até ele. Aquela ADR escreveu a ponta antes de alguém a cobrar — *"fica aberto o
alcance de (b)"*.

**Perseguindo isso apareceu um defeito que não é de documento.** Em 19/08/2026 os serviços
do CRM foram renomeados de `biahflow-*` para `cockpit-*` (commit `b4e0471`, cuja mensagem
diz *"registra o que já está na nuvem"*), e o rename tocou **um arquivo só**:
`ambientes/hml-biahflow/servicos.tf`. A borda ficou para trás.
`ambientes/hml/cloudflare.tf:47` montava a origem da Cloudflare como
`biahflow-web-<número>.<região>.run.app` — nome que nenhum `servicos.tf` declara desde
então —, e daquela `local` saem o registro DNS (`:54`) e o template do worker da borda
(`:80`).

O commit de acerto seguinte (`6a0e45f`, *"O espelho que ficou para trás: biahflow/cockpit
também na fundação"*) alinhou **outro** espelho — `repositorios_deploy` em `variables.tf` —
e não passou por `cloudflare.tf`. A mensagem dele nomeia este modo de falha por extenso:
*"divergir faz os dois states se desfazerem em turnos"*.

**E o acoplamento por string é deliberado, o que torna a guarda o preço dele.** O
comentário de `cloudflare.tf:16` explica a escolha: um hostname de borda referencia o
serviço **por nome**, que é uma string e não um recurso, e é isso que permite declarar a
borda sem ler state de produto nenhum e sem ciclo. A decisão continua certa. O que faltava
era o mecanismo que impede a string de derivar — e é ele que esta fatia entrega.

**O limite do diagnóstico, dito antes de qualquer conclusão.** Não foi possível afirmar
daqui que o CRM esteve fora do ar: não se sabe o que sobreviveu ao `deletion_protection`
que aquele commit menciona, nem o que a zona responde hoje, e o `plan` não pôde ser gerado
(a credencial do backend GCS pede reauth). O que é verificável sem rede, e é o que a fatia
afirma: **o Terraform estava internamente inconsistente**, e um `apply` em `ambientes/hml/`
(re)criaria um CNAME apontando para um nome que o repositório não declara em lugar nenhum.

O inventário, medido antes de escrever qualquer linha de código:

| Afirmação | Onde | O que a fonte diz |
|---|---|---|
| `origem_do_crm = "biahflow-web-…"` | `hml/cloudflare.tf:47` | `servicos.tf:171` declara `cockpit-web` desde `b4e0471` |
| `cd ../hml-portal` | `hml-gcp.md:162`, passo 6 | `ambientes/` só tem `hml/` e `hml-biahflow/` |
| `cd …/ambientes/hml-portal` | `hml-gcp.md:436` | idem |
| "a escolha registrada em `ambientes/hml-portal/servicos.tf`" | `hml-gcp.md:417` | idem |
| "os **29** segredos" (mais `:118`, `:147`, `:264`) | `hml-gcp.md:103` | `hml/variables.tf` declara **10** |
| "as DSNs entram em **quatro** segredos" | `hml-gcp.md:135` | **2**; `PORTAL_*` saiu com os vinte |
| `gcloud run jobs execute biahflow-migrate` / `-check` | `hml-gcp.md:285-286` | `cockpit-migrate`, `cockpit-check` |
| `worker-pools update biahflow-scheduler` | `hml-gcp.md:580` | `cockpit-scheduler` |
| `curl …biahflow-web-…run.app` | `hml-gcp.md:367` | idem |

**Nada disto estava isento.** O cabeçalho do runbook declara história apenas os **passos
5, 8 e 9**; o passo 6 e a seção "HML dorme" são apresentados como procedimento corrente. E
o cabeçalho diz que o state `ambientes/hml-portal` não existe mais — o documento se
contradizia sessenta linhas adiante.

## Decisão

**Duas asserções novas em `apps/api/tests/test_architecture_doc.py`**, sem rede e sem
banco, no job `api-quality` e sem job novo. O arquivo **não** foi renomeado: seis
documentos o nomeiam (`AGENTS.md`, `CLAUDE.md`, `ROADMAP.md`, `docs/architecture.md`,
`infra/terraform/README.md` e a ADR 0064), e renomeá-lo criaria de uma vez seis referências
obsoletas — exatamente a classe de defeito que esta fatia fecha.

### (e) Um comando não manda entrar num ambiente que não existe

Corpus: todo `.md` nosso. O predicado pergunta uma coisa só — o nome de um ambiente do
Terraform —, sobre as duas formas em que ele aparece: qualificado por `ambientes/`, que não
precisa de escopo porque só significa uma coisa aqui, e como irmão (`../<nome>`), que
precisa e o tem — só vale em fence que fale de `terraform`.

**Não é o braço que a ADR 0064 recusou.** Aquele lia *toda* crase inline, rendia zero
achados únicos e 32 falso-positivos das classes `try/except` e `application/octet-stream`.
Este foi medido em 9 referências e acusa 3, com zero ruído.

### (f) O nome que o repositório constrói ou invoca é o que o Terraform declara

**O sinal de "isto é um nome de serviço" é estrutural, e é o que dispensa allowlist.** O
primeiro segmento de um hostname `run.app` é um serviço por construção da própria URL, e o
argumento de `gcloud run <espécie> <verbo> <nome>` é posicional. Uma regra, duas espécies de
arquivo: pega o HCL que monta a URL por interpolação e o `curl` que a escreve com o número
literal.

Direção pendurada, como (d): um serviço declarado que ninguém nomeia passa despercebido, e
continua sendo julgamento e não contagem. Cobra-se o inverso — quem nomeia, nomeia o que
existe. **Medido: 7 referências no repositório inteiro, e as 7 estavam erradas.** Nenhuma
referência cruzada a serviço sobreviveu ao rename.

### (c) ganhou dois denominadores

`COUNTED_IN_PROSE` é diretamente extensível, e as duas linhas novas saem de
`hml/variables.tf`: `len(segredos)` e as chaves terminadas em `_URL`. O `_secret_keys` é
fail-closed como o `_access_values` — bloco não encontrado reprova em vez de contar zero e
concluir que a prosa mente.

## Medição

**As três asserções nasceram vermelhas**, contra o `HEAD` desta branch:

```text
estes números escritos não casam com o que a fonte conta: docs/runbooks/hml-gcp.md: a
prosa diz `29` e segredos do Terraform são 10; docs/runbooks/hml-gcp.md: a prosa diz
`quatro` e segredos que carregam DSN são 2.

estes comandos nomeiam um ambiente do Terraform que este repositório não declara:
docs/runbooks/hml-gcp.md:162 manda usar `hml-portal`; docs/runbooks/hml-gcp.md:435 manda
usar `hml-portal`; docs/runbooks/hml-gcp.md:436 manda usar `hml-portal`.

estes sítios nomeiam um serviço do Cloud Run que nenhum `servicos.tf` declara:
infra/terraform/ambientes/hml/cloudflare.tf:47 constrói `biahflow-web`;
docs/runbooks/hml-gcp.md:285 invoca `biahflow-migrate`; docs/runbooks/hml-gcp.md:286
invoca `biahflow-check`; docs/runbooks/hml-gcp.md:367 invoca `biahflow-web`;
docs/runbooks/hml-gcp.md:580 invoca `biahflow-scheduler`; docs/runbooks/hml-gcp.md:582
invoca `biahflow-check`; docs/runbooks/hml-gcp.md:584 invoca `biahflow-check`.
```

**Doze achados, zero falso-positivo.** E o primeiro deles é o único que não é documento.

### As mutações

| Mutação | Resultado |
|---|---|
| devolver `biahflow-web` ao `cloudflare.tf` | acusa |
| devolver `cd ../hml-portal` ao runbook | acusa |
| trocar o número de segredos por "onze" | acusa |
| apagar a frase-contador | acusa "a frase sumiu" |
| duplicar a frase-contador | acusa "casou 2 vezes" |
| `gcloud` invocando serviço inexistente | acusa |
| trocar `hml-biahflow` por ambiente inventado | acusa |
| **nome antigo só em comentário de HCL** | **verde** — separa da versão ingênua |
| **ambiente inexistente citado em prosa** | **verde** — a nota histórica sobrevive |
| **`cd` para repo irmão em fence sem `terraform`** | **verde** — o escopo é a fence |
| **nome antigo dentro de fence ```text** | **verde** — saída citada não é comando |

**E três defeitos da própria guarda, que só apareceram por rodá-la.** Os três são a mesma
lição da ADR 0038 — a cobertura de um portão é a dos ramos que a amostra percorre:

- **O escopo era o arquivo, e tinha de ser a fence.** A primeira versão juntava as linhas
  `bash` do documento inteiro antes de perguntar se ali se falava de `terraform`, e com
  isso o `git -C ../biahflow-portal` de uma fence de `gcloud` **herdava o escopo de outra
  fence** e entrava como falso-vermelho. O corpus de um predicado é o bloco em que ele
  vale.
- **O casador de `../` disparava em reticência.** `POST .../clients/<id>/…` casa
  `\.\./clients` — as reticências da prosa viravam um caminho relativo. Duas linhas
  acusadas por um `...`.
- **A etiqueta da fence não estava lá, e sem ela a guarda cobrava que a ADR 0064 fosse
  apagada.** A seção Medição daquela ADR cita a saída literal do próprio vermelho, que
  nomeia `ambientes/hml-portal`; e três frases de prosa que citam `gcloud run services
  update` faziam o casador posicional tomar a palavra seguinte (`falha`, `que`) por nome de
  serviço. Exigir ```` ```bash ```` fecha as duas por construção — sem allowlist, e sem
  cobrar que o repositório apague o registro do próprio erro (ADR 0034).

**E um ramo foi acrescentado e depois retirado, de propósito.** A frase escrita dizia "os
**29** segredos" em algarismo, e o parser de (c) só conhecia numeral por extenso. A saída
foi corrigir a **prosa** para "dez" e deixar o parser como estava: um algarismo continua
reprovando com *"não é um numeral que a guarda conheça"*, que é fail-closed, e um ramo que
nenhuma frase do repositório percorre é ramo que ninguém testa.

**Portões:** 655 testes de API (**0 pulados**, sem `test_backup_restore.py`, com Postgres e
MinIO de pé) — 653 antes desta fatia e os 2 novos. `npm test` 139/139, `npm run lint` 0
erros (os 4 avisos são de `coverage_html.js` dentro do `.venv`, anteriores a esta fatia e
já registrados na ADR 0063). `terraform fmt -check -recursive` sem deriva e
`terraform validate` verde nos **dois** ambientes. `alembic check`,
`python -m portal_api.openapi --write` e `npm run audit` **não se aplicam**: a fatia não
toca modelo, migração, rota nem dependência. `node scripts/pins.mjs` também não — o
`ci.yml` não foi tocado.

## Consequências

- **A borda deixou de nomear um serviço morto, e o `apply` não foi rodado.** O `plan` não
  pôde sequer ser gerado: o backend GCS recusa com `invalid_grant` pedindo reauth, e
  autenticar é ato de pessoa. A fatia entrega o código; quem aplica é um humano, com o
  `plan` na frente — guardrail de infraestrutura, e não formalidade: a mudança reescreve um
  registro DNS.
- **O acoplamento por string continua, agora com o preço pago.** Trocar a `local` por um
  `terraform_remote_state` do produto inverteria a direção fundação → produto e criaria o
  ciclo que `cloudflare.tf:16` recusa por escrito. A guarda é o que torna a string
  defensável.
- **Quatro comentários de HCL foram corrigidos à mão, e a guarda não os vê.** Ela retira
  comentário antes de casar, pela razão medida na ADR 0064 (`portal-api` sobrevive cinco
  vezes em comentário e faria a versão ingênua passar verde). O critério aplicado: corrigi
  a afirmação **viva** (`cockpit-api` é quem lê aquele segredo, hoje) e deixei a **nota
  histórica** (as quatro que citam `portal-api`, serviço que não existe mais). É o mesmo
  limite de (b), e fica declarado em vez de fingido.
- **A prosa fica fora de (e), e isso foi medido, não suposto.** `hml-portal` aparece
  corretamente em sete lugares de prosa — `ROADMAP.md`, `docs/architecture.md`, o cabeçalho
  deste runbook —, todos registrando que o ambiente **saiu** em 13/08/2026. Alargar para a
  prosa cobraria que o repositório apagasse o próprio registro.
- **Um cardinal foi apagado outra vez, e pela regra da ADR 0064.** O passo 6 se chamava "e
  agora são três": redundante com a fence logo abaixo, e quem conta states de verdade é
  `São dois states`, guardado em dois documentos.
- **A seção "HML dorme" foi reescrita, e é a maior mudança de prosa da fatia.** Ela ensinava
  a acordar `portal-api`, `portal-web`, `keycloak`, `portal-worker` e `portal-beat`, e o
  único comando executável dela apontava para um diretório apagado. Os números medidos do
  boot do Keycloak (43,6s a 115,7s de JVM) ficaram registrados na nota de correção em vez
  de apagados: foram medidos em boot real, e descrevem um serviço que saiu da GCP.
- **Fica aberto, e nomeado:** (f) não sabe se um serviço declarado deixou de ser nomeado
  por quem devia nomeá-lo, e (e) não alcança um ambiente citado só em prosa viva — o
  `:417` desta fatia foi corrigido à mão pelo mesmo motivo. As duas assimetrias são a de
  (d), declaradas em vez de fingidas.
- **E fica aberto o que nenhum portão deste repositório vê:** o outro lado do rename mora
  em `biahflow/cockpit`, e a correspondência entre os dois repositórios continua sendo
  conferida a olho. Esta guarda prova que o **nosso** Terraform e os **nossos** documentos
  concordam entre si; que eles concordem com a nuvem, só um `apply` diz.

## O que esta fatia não é

O portal do cliente está fora do ar desde 13/08/2026 (ADR 0053). Isto corrige um runbook e
uma linha de infraestrutura do **outro** produto e deixa portão; nada aqui foi observado
servindo cliente, nenhum comportamento de produto mudou, e nenhum `apply` foi executado.
