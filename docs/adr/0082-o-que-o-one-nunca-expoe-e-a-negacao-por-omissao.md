# ADR 0082 — O que o One nunca expõe, e a negação por omissão

**Status:** aceito
**Data:** 28/08/2026
**Fase:** 7

> Terceira fatia da adoção do [Language Map v1.1](../ontology/language-map.md) neste
> repositório (Issue #87). A primeira foi a [ADR 0079](0079-engagement-como-raiz-da-navegacao-e-a-conta-que-se-chamava-cliente.md),
> que trouxe o documento normativo e o Engagement; a segunda foi a
> [ADR 0081](0081-o-degrau-que-a-jornada-nao-atravessava-e-o-piloto-que-o-prove-nao-e.md),
> que atravessou o degrau canônico e a decisão de gate. Esta vai atrás da §3, que é a
> única seção daquele documento escrita como **proibição**.

## Contexto

A §3 do Language Map tem duas colunas. A da esquerda diz o que o One mostra; a da direita
diz o que ele **nunca** mostra, em nove linhas: `Lead`; `Qualification` e seu resultado;
`CommercialOpportunity`, `PipelineStage`, valor e probabilidade; Evidence não revisada e
transcrição bruta; `PriorityAssessment.rationale` interno; preço de tabela, margem e
`Service.price`; Case de outros clientes; qualquer dado de outra Account; e nada com
`epistemic_status=hypothesis` apresentado como fato.

O que existia aqui para sustentar essa coluna:

1. **O `extra="forbid"` da ADR 0020**, que fecha o contrato **por construção**: um campo
   que o modelo não declara estoura na resposta em vez de sumir em silêncio. É uma
   propriedade forte e não é esta: ela não diz nada sobre um campo que alguém *declarou*.
   Um campo novo do Pulse que atravesse o snapshot, entre na projeção e ganhe linha no
   `schemas.py` chega à tela do cliente sem que nada pergunte se ele podia chegar.
2. **A prosa do `one-projection-contract.md`**, que listava o recorte e terminava
   admitindo, por escrito, que "o guard de visibilidade por campo — a lista positiva do
   que pode sair — ainda não existe".
3. **O isolamento por tenant**, que já tem duas guardas — e isso foi verificado antes de
   escrever qualquer linha, porque construir uma terceira teria sido o desperdício mais
   provável desta fatia. `test_authorization.py::test_every_route_that_promises_a_404_proves_it`
   deriva **do contrato publicado** toda rota que promete 404 e cobra de cada uma um teste
   que troque de ator (ADR 0035); a única isenção escrita é `GET /api/v1/admin/organizations`,
   que responde 200 com lista vazia por desenho. `test_rls_isolation.py` prova a segunda
   barreira no banco. Nenhuma rota de cliente ficou sem prova, então **o critério (8) da
   §3 já estava coberto** e esta fatia não construiu guarda de tenant nenhuma.

O que não existia era o mecanismo do meio: **revisão humana de cada campo que sai**. E a
ausência dele tem forma conhecida neste repositório — é a mesma da ADR 0033, em que uma
guarda percorria oito nomes escritos à mão num contrato com 56 esquemas de resposta e a
allowlist seguia vazia porque nada a consultava.

## Decisão

### Negação por omissão

`docs/contracts/one-visibility.json` classifica, campo a campo, **os 223 campos dos 41
esquemas** que hoje saem por uma rota de cliente, cada um com prosa curta que diz o que o
campo é e de onde vem. Campo que ninguém classificou **não passa**: a guarda nasce vermelha
sobre ele.

A regra é a omissão, e não uma lista de proibidos, porque a lista de proibidos só alcança o
que alguém já imaginou. O caminho pelo qual um dado comercial chegaria à tela do cliente
não é alguém escrever `deal_value` — é o Pulse acrescentar uma chave ao snapshot, a
projeção repassá-la e o `schemas.py` declará-la, com todo mundo agindo de boa-fé. Contra
isso, o único portão que funciona é o que exige uma frase escrita por uma pessoa.

A razão de cada campo é o portão de verdade, e é por isso que ela tem piso: **um campo cuja
razão ninguém consegue escrever é um campo que não devia estar saindo.**

### Duas guardas, um artefato

- `apps/api/tests/test_visibility.py` afirma **cobertura**: todo campo de toda resposta de
  rota de cliente está classificado, e o artefato não guarda linha que saiu do contrato.
- `tests/api-contract.test.mjs` afirma as **nove proibições**, sobre o contrato **e** sobre
  as fixtures do BFF — que é onde uma resposta forjada é livre para mentir, e é a razão de
  aquele arquivo existir desde a ADR 0020.

Não é o defeito que a ADR 0034 nomeou. Lá havia duas guardas afirmando **a mesma coisa**
sobre o `alerts.md`, e duas guardas sobre a mesma afirmação divergem. Aqui são duas
afirmações **distintas** sobre um dado só — e o recorte do corpus mora no artefato
justamente para as duas metades não o reimplementarem cada uma do seu jeito.

### A cobertura vive na API, não no BFF

Medido: as seis rotas de `app/api/**` são **passagem crua** — `Response.json(await
response.json())`, nenhuma filtra campo. Isso é por desenho (a API é quem decide
autorização e conteúdo, e o frontend não decide autorização é convenção do `AGENTS.md`), e
é o que torna o BFF o lugar errado para esta guarda: filtrar lá criaria uma **segunda
autoridade** sobre a mesma pergunta, e no dia em que as duas discordassem o cliente veria o
resultado da mais permissiva. Filtrar campo no BFF ficou registrado como decisão contrária,
e não como trabalho adiado.

### A proibição é por recurso, nunca por palavra

`DecisionOut.rationale` **existe hoje e é legítimo**: é o racional da decisão publicada
(FDD 032 do Pulse, ADR 0037/0049), e é ele que justifica a aba de decisões existir — sem o
porquê, uma decisão é um título. O proibido é o `rationale` do `PriorityAssessment`, que é
avaliação interna. Um banimento por substring de `rationale` nasceria **vermelho em cima de
campo correto**: é o `.priority` da ADR 0033 outra vez.

Daí três mecanismos, e nenhum deles é substring:

| mecanismo | casa | exemplo |
| --- | --- | --- |
| `forbidden_resources` | **token** do identificador, contíguo, `CamelCase` e `snake_case` na mesma moeda | `LeadOut` reprova; `ShowcaseOut` não é `case` |
| `forbidden_pairs` | (recurso, campo): o recurso pode sair, aquele campo dele não | `PriorityAssessment.rationale`, `Service.price` |
| `forbidden_field_names` | **nome inteiro** do campo | `deal_value` reprova; `kpi_value` não |

Duas armadilhas medidas ficaram registradas no próprio artefato: `MeetingOut.has_transcript`
é booleano — é o campo que permite dizer que a transcrição *existe* sem expô-la —, e
`recording_url` é a gravação da reunião **do próprio cliente**; nenhum dos dois é
"transcrição bruta", e um banimento do token `transcript` teria pegado o primeiro. E a
proibição de `opportunity` **não** entrou como termo de contrato, porque "Opportunity
Score", "Opportunity Map" e "Improvement Opportunity Backlog" são exceções nomeadas na §5 —
rótulos de entregável, não identificadores. Onde essa palavra tem de ser vigiada é na UI, e
isso é a issue #91: se esta guarda a banisse por identificador, ela e o lint colidiriam.

### O que ficou fora do corpus, e por quê

Toda exclusão tem razão escrita no artefato, porque **exclusão sem razão escrita é allowlist
disfarçada** — e uma asserção reprova a exclusão que sobrou depois de a rota sumir.

- `/api/v1/admin/*`: superfície interna. Não é "o que o cliente vê"; quem a protege é o
  papel `portal_admin` no banco (ADR 0011) e o caso negativo derivado do contrato. Misturar
  os campos de admin aqui juntaria duas perguntas diferentes e afrouxaria a primeira para
  caber a segunda.
- `/health` e `/health/ready`: sondas, sem autenticação e sem dado de tenant.
- `/api/v1/agent-events` e os dois webhooks (Biahflow e WhatsApp): são **entrada**, não
  leitura de cliente. O que entra por eles é escrito; a projeção que alimentam é que vira
  resposta, e essa está no corpus.

E o corpus é **fail-closed** nos dois sentidos: rota do contrato que não está nele nem numa
exclusão escrita reprova, e corpus vazio reprova. Verde por não ter olhado é o defeito do
`dependency-review` (ADR 0023) e do `for` sobre oito nomes (ADR 0033).

### A regra que só morde amanhã, escrita hoje

`epistemic_status` **não existe** neste repositório: `Finding` é a issue #90. A regra
honesta que dá para escrever agora é a positiva — esquema listado em `epistemic_resources`
**tem** de declarar o campo —, de modo que, quando a #90 criar `FindingOut`, tirar o campo
da resposta reprove. `Evidence` ganhou a mesma forma em `reviewed_resources`, e por um
motivo próprio: a evidência revisada e a não revisada são a **mesma** entidade, e o que as
separa é uma marca — um banimento baniria a revisada junto.

As duas listas estão vazias hoje, e uma asserção sobre lista vazia não percorre ramo nenhum.
É a lição do `_TEMPLATE_SAMPLE` (ADR 0038): **a cobertura de um portão é a dos ramos que a
amostra percorre**. Daí as duas amostras sintéticas em memória, que fazem a regra morder
antes de haver recurso — e a mutação 3 abaixo, que a mede.

### A guarda lê o artefato publicado

`test_visibility.py` lê `docs/api/openapi.json`, e não `openapi.schema()` como o vizinho
`test_openapi_contract.py`. O gate de deriva daquele arquivo já prova que publicado ==
código, então não se perde nada; o que se ganha é que **as duas metades enxergam o mesmo
corpus**, e que a guarda é mensurável mutando um arquivo só.

## Medição por mutação

Toda guarda deste repositório nasce medida (ADR 0065). Harness em Python, com asserção de
que o alvo mudou e restauração dos dois artefatos no `finally`. Dez mutações; as **verdes
provam mais que as vermelhas**, porque são elas que separam esta guarda de uma versão
ingênua.

| # | mutação | esperado | obtido |
| --- | --- | --- | --- |
| 1 | campo `commercial_value` num esquema de cliente | vermelha | **vermelha** — cobertura *e* proibição |
| 2 | esquema de resposta `LeadOut`, classificado no artefato | vermelha | **vermelha** — só a proibição (recurso) |
| 3a | `FindingOut` **com** `epistemic_status`, listado e classificado | verde | **verde** |
| 3b | `epistemic_status` removido do esquema listado | vermelha | **vermelha** — a marca |
| 4 | `DecisionOut.rationale` renomeado | verde na proibição, vermelha na obsolescência | **exatamente isso** |
| 5 | campo novo num esquema de rota de **admin** | verde | **verde** |
| 6 | campo de nome neutro num esquema de cliente | vermelha, só cobertura | **vermelha, só cobertura** |
| 7 | `PriorityAssessmentOut.rationale` numa rota de cliente | vermelha, só o par | **vermelha, só o par** |
| 8 | `organization_id` como query de rota de cliente | vermelha | **vermelha** |
| 9 | prefixo de exclusão largo demais (corpus vazio) | vermelha | **vermelha** — fail-closed |

As três que carregam o argumento:

- **A 5** é a que separa esta guarda de uma que classificasse o contrato inteiro. O corpus é
  recortado por decisão escrita, e a decisão é executável.
- **A 4** é a prova de que a proibição não é substring: renomear `DecisionOut.rationale`
  deixou as oito asserções de proibição **verdes** e acendeu a obsolescência do artefato,
  que é a linha órfã sendo cobrada. O que também ficou vermelho ali foi a sentinela que
  declara a premissa do par (`o par proibido não alcança um campo de mesmo nome em outro
  recurso`), e isso é o mecanismo funcionando: a linha some quando o motivo some.
- **A 2** só acendeu a proibição, e não a cobertura, porque a mutação classificou os campos
  de propósito. Sem isso o vermelho teria vindo do outro lado e não provaria nada — uma
  mutação malformada se disfarça de guarda fraca.

A saída literal do vermelho da mutação 1, dos dois lados:

```
E   AssertionError: estes campos saem para o cliente e ninguém os classificou:
    ['MeProjectOut.commercial_value']. Negação por omissão: classifique-os no
    artefato, ou tire-os do contrato.
```

```
✖ nenhum campo de cliente é preço, margem, valor de negócio ou transcrição bruta
  AssertionError [ERR_ASSERTION]: estes campos saem para o cliente e a §3 do
  Language Map os proíbe.
  + [ 'MeProjectOut.commercial_value' ]
  - []
```

## Consequências

- **Campo novo de resposta de cliente custa uma frase.** Quem acrescentar um campo escreve o
  que ele é e de onde vem, no mesmo commit. É o mesmo preço do `response_model`, do
  `openapi.json` regenerado e da linha no `alerts.md` — e é deliberado que o preço seja
  pago por quem acrescenta, não por quem revisa seis meses depois.
- **O artefato não é append-only** (não é o `prompt-registry.json`) e **não tem prazo** (não
  é o `advisories.json`): quando o campo sai do contrato, a linha sai daqui, e quem a vence
  é a asserção de obsolescência — o precedente do `PINNED_BY_EXCEPTION` (ADR 0063).
- **Filtrar campo no BFF fica decidido contra**, com o motivo escrito. Não é trabalho
  adiado.
- **Não há terceira guarda de tenant.** O critério (8) da §3 já tinha duas, e esta fatia
  acrescentou só a metade que um contrato consegue afirmar: nenhuma rota de cliente aceita o
  cliente **nomear** uma Account.
- **A §3 do Language Map passa a ter portão dos dois lados.** A coluna da esquerda continua
  sendo prosa; a da direita é executável.

**Fica aberto:**

- `epistemic_resources` e `reviewed_resources` estão **vazias**, e a regra que elas carregam
  só morde depois da issue #90. Até lá, o que as sustenta é a amostra sintética.
- A guarda é sobre **nome** de esquema e de campo, e não sobre **valor**. Um campo
  legitimamente classificado que passe a carregar conteúdo proibido — uma `description` que
  receba a transcrição bruta — não é alcançado por ela, e não há como um esquema OpenAPI
  dizê-lo. Quem cobre isso é a revisão da fatia que mudar o produtor.
- `Case` está proibido por inteiro, o que é **mais estrito** que a §3: lá o proibido é o Case
  de *outros* clientes, e o §2 admite o do próprio "só com autorização". Como não há Case
  nenhum aqui, a proibição nasce total e publicá-lo passa a ser decisão de pessoa — tira-se a
  linha do artefato, com razão escrita e ADR. Está registrado como escolha, não como leitura.
- O lint de linguagem no front (`opportunity` sem qualificador, rótulos de UI) continua fora:
  é a issue #91, e esta guarda foi escrita para não colidir com ela.
