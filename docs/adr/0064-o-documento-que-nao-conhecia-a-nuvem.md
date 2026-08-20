# ADR 0064 — O documento que não conhecia a nuvem

**Status:** aceito
**Data:** 20/08/2026
**Fase:** 7 — e a quarta ADR aceita neste dia, depois da 0061, da 0062 e da 0063

## Contexto

Entre 07 e 13/08/2026 dez ADRs (0044–0053) puseram este repositório na GCP: Cloud Run para os
serviços, worker pools para o Celery, Postgres no Neon, Redis no Upstash, Terraform em
`infra/terraform/` e a borda migrando do balanceador global para a Cloudflare. A ADR 0054 já tinha
achado que o **índice canônico** não sabia de nenhuma delas, e deixou portão para isso.

O documento de **arquitetura** também não sabia, e ninguém tinha olhado. `docs/architecture.md`
abria a seção de topologia assim:

> O diagrama acima é lógico. Fisicamente há **dois ambientes**, e a diferença entre eles não é de
> escala, é de fronteira.

E descrevia dois: o compose local e o compose de homologação. **Medido:** o arquivo não continha as
strings `Terraform`, `Cloud Run`, `Cloudflare`, `Neon`, `Upstash` nem `0053`; foi tocado pela
última vez em 07/08/2026, antes de a maior parte daquelas dez ser aceita; e não sabia que o portal
tinha saído do ar. Um documento chamado "Arquitetura" que omite a topologia em que o produto de
fato rodou não está desatualizado — ele afirma uma coisa que é falsa, e é o primeiro arquivo que
alguém abre.

**E o `infra/terraform/README.md` tem o mesmo defeito, no parágrafo que registra tê-lo tido antes.**
A linha 20 dele diz, verbatim:

> `modulos/maquina-fila/` esteve listado aqui e **nunca existiu** depois da ADR 0045: era a VM que
> os worker pools substituíram, e a linha sobreviveu à remoção do diretório.

Conserto à mão, sem portão. É a ADR 0034 escrita por antecipação e ignorada: em 13/08 dois
diretórios foram apagados e as duas linhas sobreviveram à remoção — `ambientes/hml-portal/`
(commit `9e2d61d`, o produto saindo) e `modulos/borda/` (commit `0357be1`, a borda virando
Cloudflare). O mesmo arquivo ainda mandava, num bloco de comandos, `cd ../hml-portal`, que é uma
instrução que **falha**; dizia "São três states" contra dois `backend.tf`; dizia que `acesso` tem
"três valores" contra os quatro do `validation`; e a tabela "A forma de HML" listava como peças
vivas seis serviços dos quais **nenhum** existe hoje.

O inventário, medido antes de escrever qualquer linha de código:

| Afirmação | Onde | O que a fonte diz |
|---|---|---|
| "Fisicamente há **dois ambientes**" | `architecture.md:31` | quatro artefatos de ambiente, e uma topologia inteira sem menção |
| "treze serviços, **cada um** publicando porta" | `architecture.md:34` | treze serviços, **oito** com `ports` |
| "as **três** imagens" | `architecture.md:64` | **dois** contextos de build |
| `ambientes/hml-portal/`, `modulos/borda/` | `README.md:6-18` | apagados em 13/08 |
| "São **três** states" | `README.md:22` | **dois** `backend.tf` |
| "`acesso`, com **três** valores" | `README.md:32` | **quatro**, no `validation` |
| `web`, `portal-api`, `keycloak`, `biahflow-web`, `biahflow-api`, `worker` | tabela do `README.md` | zero deles é chave de `servicos.tf` |
| `cd ../hml-portal` | `README.md`, `## Uso` | diretório inexistente |

## Decisão

**Um documento que descreve a estrutura do repositório é conferido contra o repositório, por
portão derivado.** `apps/api/tests/test_architecture_doc.py`, sem rede e sem banco, no job
`api-quality` e sem job novo. Quatro asserções, e **cada recorte foi medido, não argumentado**.

### (a) Todo ambiente declarado é nomeado na topologia

Corpus: `docker-compose*.yml` na raiz, mais cada `infra/terraform/ambientes/*/` que tenha
`backend.tf` — o marcador é o **state**, porque é ele que faz daquele diretório algo que se aplica
sozinho.

O casamento é pelo **caminho inteiro**, e é o que separa esta guarda de um falso verde: `hml` é
substring de `hml-biahflow`, de `hml-gcp.md` e de `infra-hml.yml`, e casar pelo basename a deixaria
verde no instante em que o documento mencionasse qualquer um dos três — o `.item`/`.items` da
ADR 0057 outra vez. O token entre crases é separado por espaço em branco antes de comparar, que é o
que faz a forma que o documento de fato usa (`` `+ docker-compose.homolog.yml` ``) casar sem
nenhum teste de substring.

`DEPLOYED_WITHOUT_A_LINE` **nasce vazia**: os dois ambientes de hoje não precisam de isenção, a
correção honesta os nomeia. Allowlist que já nasce ocupada é sedimento no nascimento (ADR 0029), e
foi assim que a entrada da ADR 0009 entrou na guarda do roadmap com um motivo falso. Sem
`review_by`, no precedente do `PINNED_BY_EXCEPTION` (ADR 0063): ambiente não caduca por calendário,
e o vencimento dela é a asserção de obsolescência.

### (b) Todo caminho desenhado como estrutura existe

**O corpus é encontrado por forma, não digitado.** Um bloco cercado qualifica como fence de
estrutura quando ao menos três das suas linhas não-vazias começam por um token com forma de
caminho e esses são ao menos 60% do bloco. Medido sobre todos os `.md` do repositório: seleciona
**exatamente uma** fence, `infra/terraform/README.md:6`, e dentro dela acusa exatamente os dois
defeitos reais, com zero falso-positivo.

**A nota histórica some por construção, e esse é o ponto do recorte.** `modulos/maquina-fila/` mora
na prosa, fora da fence — sem `_HISTORICAL_NOTE`, sem allowlist e sem convenção de marcador nova. O
documento guarda o registro do próprio erro e a guarda nunca o vê. Um recorte por citação em crase
teria de escolher entre exigir que o repositório apagasse aquele parágrafo ou carregar uma isenção
permanente, que é a mesma sedimentação por outro nome.

A resolução é **relativa ao diretório do documento**, e é exata: um README descreve o diretório
onde mora. Casamento por sufixo ficaria verde se um diretório de mesmo nome existisse em qualquer
outro ponto da árvore — e a mutação prova a diferença: `terraform/ambientes/hml`, que é sufixo
legítimo de um caminho real, **reprova**.

### (c) O número escrito casa com o contado

Seis linhas de `(documento, regex de um grupo, denominador derivado)`, com fail-closed nos dois
sentidos: zero casamentos reprova ("a frase sumiu") e mais de um também ("ficou ambígua"). O mapa
de numeral por extenso é **detalhe de parser e não corpus**, no precedente da tabela de flags do
`docker run` (ADR 0063): envelhece com a língua portuguesa, não com este repositório.

**E "dois ambientes" ficou de fora — a frase foi apagada, não corrigida para três.** A contagem de
topologias *narradas* não é a cardinalidade do corpus de (a), que são quatro artefatos, porque
homologação é override sobre a base e não uma quarta coisa; guardá-la exigiria uma segunda
definição de "ambiente", divergente da primeira, e duas definições derivam. A regra que fica:
**guarde o número cujo denominador é artefato contável; apague o número cujo denominador é escolha
narrativa.** As topologias passaram a ser nomeadas, e quem as guarda é (a).

*A revisão do próprio diff cobrou a regra duas vezes, e as duas correções estão neste commit.* A
primeira versão do texto dizia "Fisicamente há **três** topologias — Local, Homologação e Nuvem":
o cardinal tinha só mudado de valor, redundante com a lista ao lado e sem nada que o guardasse,
que é exatamente o defeito do parágrafo acima. Foi apagado. E o parágrafo novo da nuvem escrevia
"dois states" solto — número de denominador **contável**, portanto do tipo que a regra manda
guardar e não apagar: virou a sexta linha da tabela, medida por mutação como as outras.

### (d) Todo serviço que a tabela nomeia existe no Terraform

Só a direção pendurada, que dispensa completude e parser de HCL: os nomes em crase da primeira
coluna da tabela contra as chaves lidas por indentação de `ambientes/*/servicos.tf`. A primeira
coluna se autosseleciona — as linhas de serviço citam o nome entre crases e as de infraestrutura
(Redis, documentos, Postgres, rede) são texto puro, então não há allowlist para elas.

**A versão ingênua foi medida e recusada.** Perguntar se o nome aparece em algum `.tf` passa verde:
`portal-api` aparece **cinco vezes** no `servicos.tf` de hoje, todas em comentário de histórico, e
`keycloak` outras tantas. Ler as chaves por indentação é o que faz um comentário não poder casar —
ele começa com `#`.

## Medição

**A guarda nasceu vermelha nas quatro asserções**, contra o `HEAD` desta branch:

```text
estes ambientes de implantação são declarados no repositório e a seção `## Topologia de
implantação` não os conhece: infra/terraform/ambientes/hml (um state do Terraform);
infra/terraform/ambientes/hml-biahflow (um state do Terraform).

estes caminhos são desenhados como a estrutura de um diretório e não existem:
infra/terraform/README.md:6 desenha `ambientes/hml-portal`; infra/terraform/README.md:6 desenha
`modulos/borda`.

estes números escritos não casam com o que a fonte conta: docs/architecture.md: a prosa diz `três`
e contextos de build distintos são 2; infra/terraform/README.md: a prosa diz `três` e states do
Terraform são 2; infra/terraform/README.md: a prosa diz `três` e valores de `acesso` são 4.

a tabela de `infra/terraform/README.md` nomeia como peças de HML serviços que nenhum `servicos.tf`
declara: `biahflow-api`, `biahflow-web`, `keycloak`, `portal-api`, `web`, `worker`.
```

A última linha é **seis** e não cinco: `web` também saiu em 13/08, e o levantamento à mão desta
fatia não tinha visto — a máquina pergunta por todos, e não pelos que alguém lembrou, que é o que a
ADR 0034 já tinha observado.

**Catorze mutações, e duas delas mudaram o desenho.** As que confirmam:

| Mutação | Resultado |
|---|---|
| tirar `ambientes/hml-biahflow` da topologia | acusa aquele ambiente |
| citar só `` `hml` `` em vez do caminho | **continua vermelha** — é o teste que a separa do `.item`/`.items` |
| renomear a heading da topologia | acusa "não achei a seção", não passa vazia |
| desenhar `modulos/borda/` na fence de novo | acusa aquele caminho |
| desenhar `terraform/ambientes/hml`, sufixo de um caminho real | **vermelha** — não é sufixo frouxo |
| desfazer a fence (virar prosa) | acusa "nenhum bloco de estrutura foi encontrado" |
| `modulos/maquina-fila/` na prosa | **verde** — a guarda não vê a nota histórica |
| somar um serviço ao `docker-compose.yml` | acusa "diz `treze`, são 14" |
| reescrever a frase-contador | acusa que ela sumiu |
| a nota de correção citando "três imagens" | **verde**, sem "ficou ambígua" |
| devolver `` `portal-api` `` à tabela | acusa, com as cinco ocorrências dele em comentário no `.tf` |
| pôr um ambiente já nomeado na allowlist | acusa "passou a ser nomeado na topologia" |

**E as duas que a mutação corrigiu, porque a guarda tinha os defeitos que ela existe para achar:**

- **O casador de crases atravessava a cerca.** A seção de topologia tem um diagrama ASCII, e as
  crases triplas dele desalinhavam todo o pareamento adiante:
  `infra/terraform/ambientes/hml/` chegava à comparação como `ambientes"`, de modo que (a)
  reprovaria um documento que **já nomeava** o ambiente. Os blocos cercados passaram a sair antes.
- **`hml/` nu na fence deixava a guarda verde.** O filtro de forma exigia separador **interno**, e
  um token de um segmento não era reprovado — era ignorado. Um diretório de nome simples podia
  sumir da árvore sem nada ficar vermelho. O ramo da barra final fechou isso, e foi medido antes de
  entrar: não acrescenta fence nem falso-positivo nenhum ao repositório de hoje.
- **O `_HISTORICAL_NOTE` do precedente trunca no negrito.** `\*(?!\*)` termina no segundo asterisco
  de `**dois ambientes**`, deixando o resto da nota — com o número velho — dentro do texto que (c)
  lê. O fechamento passou a ser asterisco em fim de linha, com `(?<!\*)`.

**Um braço inteiro foi recusado com o número, e isso vale mais que entregá-lo.** A versão original
de (b) lia também as citações em crase inline. Medida sobre os dois documentos, ela rende **zero**
achados únicos e **um falso-vermelho** — `/api|/admin|/static|/healthz|/readyz`, que passa qualquer
filtro de contagem de separadores. Alargada para todo `.md` do repositório são **32** tokens
pendurados, das classes `INSERT/UPDATE/DELETE`, `try/except`, `America/Sao_Paulo`,
`application/octet-stream`, `hashicorp/google` e `actions/checkout` — uma linha de allowlist cada,
que é o defeito `.priority` da ADR 0033 comprado de propósito.

**Portões:** 653 testes de API (**0 pulados**, sem `test_backup_restore.py`, com Postgres e MinIO
de pé) — 647 antes desta fatia e os 6 novos. `npm test` e `npm run lint` sem mudança, e rodados
para confirmar exatamente isso. `alembic check`, `python -m portal_api.openapi --write`,
`npm run audit` e `node scripts/pins.mjs` **não se aplicam**: a fatia não toca modelo, migração,
rota, dependência nem pino. Ficam declarados em vez de rodados por ritual, que é a disciplina da
ADR 0023 sobre o que um portão verde afirma.

## Consequências

- **`docs/architecture.md` passou a nomear um ambiente de outro produto**, e a oração que torna
  isso honesto é a que fecha a seção: a terceira topologia existe, é aplicável, e **hoje não
  hospeda este produto**. `infra/terraform/ambientes/hml-biahflow/` está lá porque um `apply`
  naquele diretório é um `apply` deste repositório, sobre a fundação que os dois compartilham.
- **Um cardinal foi apagado em vez de corrigido**, e a regra ficou escrita: guarde o número cujo
  denominador é artefato contável, apague o número cujo denominador é escolha narrativa. Corrigir
  "dois ambientes" para "três" teria criado uma segunda definição de ambiente, divergente da do
  corpus de (a), e duas definições derivam — que é o defeito que esta ADR inteira persegue.
- **A guarda cobra um documento, e portanto pode reprovar quem só escreve prosa.** É deliberado, e
  o preço está nas mensagens: cada uma diz o que fazer e oferece a saída legítima. Quem reformatar
  a fence de estrutura tem de ajustar `_FENCE_MIN_PATHS`/`_FENCE_MIN_RATIO` no mesmo commit, e o
  fail-closed do corpus é o que impede que aquilo passe verde.
- **Não há guarda sobre o `CLAUDE.md`**, e continua sendo de propósito, pelo mesmo argumento da
  ADR 0054: o índice canônico é o `ROADMAP.md`, e cobrar de um segundo arquivo o faria crescer sem
  limite.
- **Fica aberto, e nomeado:** a asserção (d) é a direção pendurada só. Um serviço que existe no
  Terraform e que a tabela **não** nomeia passa despercebido — a direção inversa exigiria decidir o
  que é peça de HML digna de linha, que é julgamento e não contagem. É a assimetria que a ADR 0034
  fechou para eventos e que aqui fica declarada em vez de fingida.
- **E fica aberto o alcance de (b):** hoje o repositório tem **uma** fence de estrutura, então o
  corpus derivado tem um membro. Isso é menos frágil que uma lista digitada — a regra é computada e
  cresce sozinha quando alguém desenhar outra —, mas não é o mesmo que cobertura ampla, e o número
  está aqui para não ser confundido com ela.

## O que esta fatia não é

O portal está fora do ar desde 13/08/2026 (ADR 0053). Isto corrige dois documentos de arquitetura e
deixa portão; nada aqui foi observado servindo cliente, e nenhum comportamento de produto mudou.
