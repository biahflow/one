# ADR 0078 — O worktree isola o git, não o estado externo

**Status:** aceito
**Data:** 27/08/2026
**Fase:** 7 — método de execução

> Decisão autorizada por Daniel Campos em 27/08/2026 (a sessão pediu para desenvolver a
> Issue #79). Descoberto ao executar `#58/#60/#61/#62` em paralelo.

## Contexto

Em 27/08/2026 quatro tarefas rodaram em paralelo (`#71`, `#72`, `#73`, `#74`), cada uma no seu
worktree e na sua branch — o modelo de
[`docs/engineering-os/workflows/worktree-execution.md`](../engineering-os/workflows/worktree-execution.md).
O isolamento de **git** funcionou: nenhuma colisão de índice, nenhuma branch atropelada, uma
`WRITE` por worktree como o documento manda.

O **estado externo** não estava isolado, e colidiu. Os quatro worktrees apontavam para o mesmo
Postgres local (`:5433`, banco `portal`), e as duas tarefas de API tinham migrações Alembic. O que
foi medido:

- a F-028 aplicou `0031_projection_freshness` ao banco compartilhado; a partir daí
  `alembic upgrade head` das outras branches falhava com
  `Can't locate revision '0031_projection_freshness'`, porque aquele arquivo não existe nelas;
- a F-027 aplicou `0034`/`0035` num banco que a F-028 tinha acabado de criar para si;
- **419 casos de teste passaram a dar erro** numa tarefa que não tocou uma linha de Python (a do
  Terraform) — o que por um instante pareceu regressão *dela*;
- o diretório de scratchpad também era compartilhado, e os agentes sobrescreveram os arquivos de
  ambiente uns dos outros.

Nada se perdeu e nenhuma migração alheia sofreu `downgrade` — os executores detectaram, criaram
bancos próprios e reportaram. Mas o custo foi real: diagnóstico duplicado, uma bateria de testes
cujo vermelho não significava o que parecia, e o banco de desenvolvimento local deixado numa
revisão à frente do `main`.

**A causa é de escopo, não de descuido.** `worktree-execution.md` garante *"um task, uma branch,
um worktree"*, e isso resolve **estado de git**. Um Postgres, um bucket, um Redis ou um diretório
temporário compartilhados continuam sendo **um recurso único com escritores concorrentes**, e o
worktree não diz nada sobre eles. O próprio documento já avisa, em uma linha, que *"worktrees
isolate Git state; they do not prove semantic parallel safety"* — mas trata a segurança semântica
como **dependência entre tarefas** (`SAFE_TO_PARALLELIZE`/`PARALLELISM_RISK`/`DEPENDENCY_BLOCKED`),
e não como **recurso externo compartilhado**. São eixos diferentes: duas tarefas podem ser
`SAFE_TO_PARALLELIZE` em dependência lógica e ainda assim colidir no mesmo banco.

O sintoma é traiçoeiro porque **não se parece com colisão**: parece defeito da tarefa. Uma migração
alheia aplicada no banco produz erro de *fixture*, não conflito de *merge* — o vermelho aparece
onde o merge nunca olharia.

Na rodada seguinte (`#75`, `#76`) cada worktree recebeu um banco dedicado (`ui027`, `ui028`),
criado e *bootstrapado* antes de o trabalho começar. **Zero colisões**, com duas features de
interface editando os mesmos arquivos de `app/`. A correção é conhecida; falta ser **dita antes**,
não descoberta.

## Decisão

**Antes de autorizar execução concorrente com capacidade `WRITE`, classificar o _estado externo_
como já se classifica a dependência entre tarefas — e isolá-lo por tarefa quando compartilhá-lo
significa escritores concorrentes sobre um recurso único.** A classificação de dependência lógica
(`SAFE_TO_PARALLELIZE`/…) **não substitui** essa; é o outro eixo.

O inventário de estado externo e a regra de cada um:

| Recurso | Quando isolar | Receita |
| --- | --- | --- |
| **Postgres** | quando a tarefa tem **migração** (ou escreve schema/dados que outra leria) | um banco por tarefa: `CREATE DATABASE` + `CREATE EXTENSION vector` + `infra/postgres/bootstrap/roles.sql`. Leva segundos. |
| **Scratchpad / diretório temporário** | sempre que houver mais de um executor | um subdiretório por tarefa, **nomeado pela branch** — nunca um arquivo de ambiente compartilhado. |
| **Objeto (MinIO/S3)** | avaliar por caso | hoje o prefixo do objeto carrega o tenant inteiro (ADR 0014), então tarefas de tenants diferentes não se veem; tarefas do **mesmo** tenant, sim — aí vale prefixo/bucket por tarefa. |
| **Cadeia Alembic** | quando duas tarefas criam migração | a colisão de **numeração** resolve-se por **faixa declarada** mais **rebase na integração**; funcionou uma vez, mas precisa ser combinada **antes**, não descoberta no `alembic upgrade` da terceira branch. |

O gatilho é **capacidade `WRITE` + recurso externo compartilhado**, e o custo de isolar (segundos
para criar e *bootstrapar* um banco; um `mkdir` por branch) é muito menor que o de diagnosticar um
vermelho que mente. Quando não há migração nem escrita de estado compartilhado, um banco só serve —
a regra não é "sempre um banco por tarefa", é "classificar e isolar o que colide".

### Onde a regra vive

1. **`AGENTS.md`** ganha a regra como aperto local da camada global — o que o próprio `AGENTS.md`
   declara poder fazer (*"onde os dois falarem do mesmo assunto, o global manda e o local só
   aperta"*). É o que a torna **vinculante já**, sem esperar o ciclo de release do repositório de
   método.

2. **A camada global (`worktree-execution.md`)** é a casa canônica, porque a regra é
   **vendor-neutra**: vale para qualquer harness, não só para este. E — medido ao ir abrir a
   emenda — **o upstream já a carrega**: `biahflow/engineeringOS` mergeou a seção
   `## Shared external state` no `main` em 27/08/2026 (PR #11, `feat/isolate-shared-external-state`,
   merge commit `2db00c6`), com os dois eixos de classificação, o banco dedicado por tarefa em
   migração, o scratch dir por branch, a faixa de migração declarada mais rebase, e o mesmo sintoma
   "erro de *fixture*, não conflito de *merge*". Ou seja, a casa canônica **já está certa**, e mais
   completa que o rascunho desta ADR — abrir outro PR upstream seria duplicar o que já existe.

   O que resta é local: [`docs/engineering-os/`](../engineering-os/PROVENANCE.md) é um **espelho
   pinado** em `v0.1.0` (commit `7bc938e`), **anterior** ao PR #11, e *"não são editados aqui"* —
   editar o arquivo vendorizado forkaria o espelho e o próximo `npm run eos:sync` desfaria a mudança
   em silêncio. A regra chega ao mirror **avançando o pino** (ato deliberado e revisado), o que
   exige uma **tag publicada** à frente de `v0.1.0` (o `sync-engineering-os.mjs` recusa referência
   que não seja tag) — hoje a seção está em `main`, sem tag nova. Até lá, a divergência é a mesma
   "o espelho envelhece em silêncio entre sincronizações" que a ADR 0074 declarou como aberto; o
   `AGENTS.md` (ponto 1) é o que faz a regra valer localmente **enquanto** o pino não avança.

### O texto que já está no upstream (referência)

A seção `## Shared external state` do `worktree-execution.md` no `main` diz, em resumo — e é a
autoridade, não este bloco:

> Um worktree dedicado isola working tree, índice e posse de branch, e **nada fora do
> repositório**. Antes de autorizar execução concorrente com escrita, a orquestração DEVE
> identificar os recursos externos que cada tarefa escreve e **isolá-los por tarefa** ou registrar
> `PARALLELISM_RISK` com a resolução — um segundo eixo, independente da dependência entre tarefas.
> Provisionar instância por tarefa costuma ser barato (um banco custa segundos) e é a resposta
> padrão quando a tarefa roda migração. O convite ao erro é o sintoma: a colisão **não** se parece
> com colisão — chega como teste falhando numa tarefa que não a causou, não como conflito de merge.

O rascunho original desta ADR (uma seção "External state isolation" a acrescentar) fica **superado**
por esse texto mergeado, e é registro do que teria sido proposto, não afirmação vigente.

## Consequências

- Autorizar execução concorrente passa a exigir **duas** classificações: dependência entre tarefas
  (já existente) e **estado externo** (esta). A segunda é barata e a primeira rodada que a ignorou
  mediu o preço de não a ter.
- `AGENTS.md` carrega a regra como aperto local, então ela vale **antes** de o upstream a absorver.
  Quem revisa isolamento — a pergunta recorrente deste repositório — agora tem onde ler "o que a
  execução paralela compartilha", além de "o que a busca alcança" e "quem escreve `membership`".
- **Esta própria fatia é a prova pequena da regra**, e foi medida: as Issues `#58`/`#62`/`#79`
  rodaram em três branches/worktrees, e **nenhuma toca migração ou Postgres** — só documentação.
  O único recurso compartilhado é o **arquivo `ROADMAP.md`**, que é estado de *git* e o worktree
  isola: `#58` e `#79` foram classificadas `PARALLELISM_RISK` sobre ele (regiões distintas do
  arquivo), a resolução é rebase na integração, e não houve banco a colidir. A classificação
  acertou de propósito o que a rodada de `#71`–`#74` acertou por acidente.
- Fica **aberto**: (1) **avançar o pino do espelho** para uma tag à frente de `v0.1.0` que inclua
  o PR #11 — a emenda upstream **já está mergeada** (não há PR a abrir), mas o mirror só a recebe
  por tag publicada mais `npm run eos:sync`, e hoje a seção está em `main` sem tag nova; enquanto
  isso, o `AGENTS.md` sustenta a regra localmente; (2) o isolamento de **objeto** do mesmo tenant
  merece análise própria (o prefixo por tenant não separa duas tarefas do mesmo cliente) e não foi
  aprofundado aqui; (3) o banco `portal` local pode estar numa revisão à frente do `main` desde a
  rodada de `#71`–`#74` — `alembic downgrade` resolve e é ato deliberado, não automático.
