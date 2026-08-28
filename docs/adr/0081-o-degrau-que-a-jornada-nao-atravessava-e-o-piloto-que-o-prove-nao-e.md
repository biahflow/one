# ADR 0081 — O degrau que a jornada não atravessava, e o piloto que o PROVE não é

**Status:** aceito
**Data:** 28/08/2026
**Fase:** 7

> Segunda fatia da adoção do [Language Map v1.1](../ontology/language-map.md) neste
> repositório (Issue #88). A primeira foi a [ADR 0079](0079-engagement-como-raiz-da-navegacao-e-a-conta-que-se-chamava-cliente.md),
> que trouxe o documento normativo para dentro do repositório e o Engagement para dentro
> do modelo. Esta vai atrás da linha seguinte da mesma tabela.

## Contexto

O Language Map §4 lista `journey_phase.canonical_stage` entre os enums canônicos com a
observação **"já existe no Pulse"**, e a §2 registra a decisão D7: `GateOutcome` foi
renomeado para `GateDecision` porque colidia com o `Outcome` de negócio. Deste lado,
nenhuma das duas coisas existia.

O que foi medido:

1. **A jornada real já vem do Biahflow.** `sync_snapshot` grava `project_phase` a partir
   de `snapshot["journey"]["phases"]` e `_journey_projection` a devolve — não há fase
   hard-coded no caminho do cliente. O que atravessava a fronteira era **nome, descrição,
   posição, estado e data**; `canonical_stage` e `gate_outcome` existem no modelo da
   origem e **não entravam na projeção**. O cliente lia o *rótulo* da fase sem nada que
   dissesse a qual degrau da FDE ela pertence, e a decisão que fecha um gate não existia
   em lugar nenhum aqui.
2. **As cinco fases hard-coded eram as da casca de demonstração** (`app/demo-overview.ts`),
   e elas não eram a escada da FDE: `Welcome → Discover → Prove → Scale → Optimize`,
   sem `Prioritize` e sem `Feasibility`. A casca é a documentação viva do formato — é o
   que alguém abre com `npm run dev` sem stack nenhuma —, então ela documentava uma
   jornada que a metodologia não tem.
3. **Ela chamava o PROVE de "piloto"**, que a §5 do mapa bane explicitamente, e chamava
   um entregável de **"AI Score"**. Este segundo tinha nome errado por duas vezes: no
   Biahflow, `ai_score` é derivado de `Project.ai_maturity`/`ai_opportunity` — é
   **maturidade de IA da conta** —, e a §5 proíbe aplicar o rótulo "Opportunity Score" a
   qualquer coisa que não seja `ImprovementOpportunity`.

A sessão que trabalha no Pulse confirmou por escrito, em 28/08/2026, o contrato que vai
emitir: `journey.phases[].canonical_stage` (os seis valores, e `""` quando a fase não tem
equivalente FDE), `journey.phases[].gate_decision` (os quatro valores, `""` quando ninguém
decidiu) e `journey.phases[].requires_gate` (booleano, campo do **template** da fase).
**Nada disso está implementado lá ainda**, e o `""` de `canonical_stage` é legítimo por
desenho: o exemplo que eles deram é uma fase `Activation`, operacional da Biahflow.

## Decisão

### 1. Três colunas, e duas nulidades que querem dizer coisas diferentes

`project_phase` ganha `canonical_stage` (enum de seis), `gate_decision` (enum de quatro) e
`requires_gate` (booleano `NOT NULL`, `server_default false`). Migração `0039`, puramente
aditiva, sem tocar policy, RLS ou privilégio — a tabela tem os três desde a `0003` e quem
escreve aqui é o sync sob `portal_system`, como em toda coluna dela.

**Os dois enums são nullable, e é por motivos diferentes que são duas colunas e não uma:**

- `canonical_stage` nulo quer dizer **"esta fase não tem equivalente FDE"**. É a tradução
  honesta do `""` da origem, e é afirmação — não falta de dado.
- `gate_decision` nulo quer dizer **"ninguém decidiu ainda"**.

`requires_gate` é o que separa os dois sentidos do segundo nulo. Sem ele, "fase que não
termina em gate" e "gate ainda por decidir" seriam indistinguíveis, e a tela teria de
escolher entre calar sobre as duas — perdendo o caso que importa — ou afirmar uma espera
sobre uma fase que nunca terá decisão. O default é `false` porque um Biahflow anterior a
esta fatia não manda a chave, e a leitura conservadora da ausência é a que faz a tela
calar.

### 2. Não se deriva o degrau do nome da fase — e a ausência de fallback é a decisão

`CANONICAL_STAGE_MAP` e `GATE_DECISION_MAP` seguem a forma do `PHASE_STATE_MAP`, e
devolvem `None` para o **ausente**, o **vazio** e o **desconhecido**. Os três chegam ao
mesmo lugar por razões distintas: o ausente é um Biahflow anterior à fatia, o vazio é a
fase sem equivalente, e o desconhecido **não pode virar exceção** — derrubar o sync
inteiro porque a origem acrescentou um sétimo degrau é pior do que mostrar a fase sem
degrau, que é o argumento que o `PROJECT_STATUS_MAP` já tinha escrito.

O que **não** existe é um fallback que olhe o rótulo. Um casador por nome carimbaria
`prove` numa fase chamada "Prova de conceito" que a metodologia não reconhece, e o palpite
sairia com a autoridade de um enum — a falsa precisão que `results.py` recusa ao declarar
a lacuna em vez de dividir por zero. Só a origem afirma o degrau; o One projeta.

### 3. Decisão de fase é decisão de fase, e nunca Outcome

`GateDecisionBadge` mora no `JourneyPanel`, ao lado da fase que a decisão fecha. Três
respostas:

| estado | tela |
| --- | --- |
| `requires_gate = false` | **nada**. Fase sem gate não ganha caixa vazia |
| decidida | `Decisão da fase: GO` · `CONDITIONAL GO` · `REDESIGN` · `NO-GO` |
| exige gate, sem decisão | `Decisão da fase: aguardando` |

Os rótulos são os canônicos da §2, **em inglês e em maiúsculas**: a regra de idioma do
mapa é que se traduz o texto em volta do termo, nunca o termo. O cliente lê a mesma
palavra que o time escreve no Pulse e no Executive Readout, que é o ponto inteiro de um
mapa de linguagem.

Ele é componente **distinto** de qualquer coisa que apresente resultado, e não entra na
aba Resultados: `Outcome` é `Measurement(kind=outcome)` com Baseline comparável, e foi
para os dois não disputarem a palavra que a D7 renomeou `GateOutcome`. Reintroduzir a
confusão na tela desfaria a decisão que a fatia está implementando.

`feasibility` **não** ganha tratamento especial. Ela aparece se o Biahflow mandar a fase,
que é exatamente "condicional por definição"; um placeholder seria o portal originando
jornada, que é o que a ADR 0006/0008 proíbe.

### 4. A casca de demonstração passa a ser a escada canônica — e `Welcome` sai dela

Seis fases na ordem da FDE, cada uma com seu `canonicalStage`, e **os dois ramos do gate
documentados**: `Feasibility` com `requiresGate: true` e `conditional_go`, `Prove` com
`requiresGate: true` e `null`. Sem o segundo, o caso que só existe por causa de
`requires_gate` não teria exemplo em lugar nenhum do repositório.

A descrição do PROVE deixa de dizer "piloto" e passa a dizer o que ele é — a menor
implementação real em produção controlada, com critério de sucesso definido antes de
construir. O entregável "AI Score" virou **"Diagnóstico de maturidade de IA"**, pelo que
ele mede de verdade na origem. As outras duas ocorrências de "piloto" (um título de
decisão e um de pendência) saíram da casca, da fixture do teste de SSR e do snapshot
semeado — este último com o spec de e2e atualizado junto, porque ele casa o literal.

**O One não passa a consumir `ai_score`.** O `sync_snapshot` não lê essa chave, e começar
a lê-la é outra fatia: o rename aqui é de **rótulo de entregável na nossa casca**, não de
campo do contrato.

### 5. `Welcome` sai da jornada da casca, e não vira painel de onboarding — desvio consciente

O issue #88 pede "mover `Welcome` para um bloco de onboarding, fora da jornada". A
primeira metade foi feita; **a segunda não**, e a razão é medida.

No Biahflow, `Welcome` **é** uma fase, com `canonical_stage` preenchido (`discover`, por
backfill). O One não reclassifica dado da origem — é a regra 2 da §3 do mapa, e é a mesma
regra que a ADR 0079 invocou para não mexer no slug. Então:

- **na casca de demonstração**, que é nossa e não espelha Biahflow nenhum, `Welcome`
  simplesmente deixa de ser fase da jornada: ali ela nunca foi degrau da metodologia, era
  o passo de acessos;
- **na projeção real, ela continua chegando como a origem a manda** — a fixture do teste
  de SSR a mantém, de propósito, com `canonical_stage=discover`;
- **não se construiu painel de onboarding voltado ao cliente.** Não há produtor para ele:
  o funil (`onboarding_step`, ADR 0039/0040) é superfície **interna**, classificada como
  comportamento de pessoa identificada, e não sai por rota de cliente. Um painel novo
  sobre campo sem escritor é exatamente o defeito que a ADR 0033 existe para pegar, e
  construí-lo aqui seria reintroduzi-lo pela porta da frente.

A reclassificação de `Welcome` — se ela deve ou não continuar sendo `discover` — é
pendência **do Pulse**, porque é lá que o dado nasce.

### 6. `ProjectPhase.situation` fica de fora, e isso foi escolha

A sessão do Pulse avisou que existe lá uma `situation` derivada, que colapsa status +
gate + espera num valor só. Ela **não** é imitada aqui: o valor `blocked` dela vem de
`waiting_party`, que é classificação interna de delivery e não atravessa a fronteira do
cliente. O par `requires_gate`/`gate_decision` é o mínimo suficiente para a tela, e é o
que atravessa.

### 7. A guarda nasce do documento normativo

`test_journey_stages.py` lê a tabela §4 do `language-map.md`, extrai os valores entre
crases das linhas `journey_phase.canonical_stage` e `gate_decision`, e afirma que eles
batem **exatamente** — em conteúdo e em ordem — com os enums Python e com as chaves dos
dois mapas da ingestão. O corpus sai do artefato e não de uma lista digitada, pelo
argumento da ADR 0033: uma lista digitada envelhece, e o dia em que a D7 ganhar um quinto
desfecho é o documento que muda.

**Fail-closed:** linha não encontrada **reprova**, não pula. Verde por não ter olhado é o
modo de falha do `dependency-review` da ADR 0023.

*Medida por mutação, e as três direções reprovam:* trocar o valor de um membro do enum
(`optimize = "optimisation"`) derruba a comparação com o documento **e** a da ingestão;
apagar uma linha de `GATE_DECISION_MAP` derruba a segunda sozinha — que é o caso que mais
importa, porque um mapa incompleto faz o valor combinado virar `None` **em silêncio**, com
a fase aparecendo sem degrau e nada ficando vermelho.

Do lado web, `rendered-html.test.mjs` ganhou quatro asserções sobre HTML renderizado: o
degrau aparece, o gate por decidir aparece, a fase sem gate **não** ganha caixa, e nenhuma
das três palavras banidas ("piloto", "POC", "MVP") sai na tela do cliente. A última tem
par no Python — a guarda confere que a proibição continua escrita no documento normativo,
para a asserção de HTML não ficar proibindo palavras por conta própria.

## Consequências

- O contrato cresce em três campos de `PhaseOut`, o artefato foi regerado no mesmo commit,
  e a guarda de consumo cobrou leitor para os três — o front os consome de verdade, e não
  por allowlist.
- A tela passa a mostrar **duas** coisas sobre a mesma fase: o rótulo que o projeto lhe
  deu e o degrau da FDE a que ela corresponde. Eles podem divergir sem que nenhum esteja
  errado, e é para isso que o degrau existe.
- Um valor de degrau ou de decisão que a tela não conhece vira `null` no mapeamento do BFF
  em vez de ser impresso cru. A origem pode ganhar um sétimo degrau antes desta tela saber
  dele, e imprimir a palavra bruta seria a tela afirmando o que não tem rótulo para ler.
- **Nada disso aparece até o Biahflow mandar os campos.** Toda fase sincronizada hoje
  nasce com `canonical_stage = NULL`, `gate_decision = NULL` e `requires_gate = false` —
  isto é, sem degrau e sem caixa de decisão, que é o mesmo que a tela mostra hoje. A fatia
  é o leitor chegando **antes** do escritor, ao contrário da ADR 0039; o que a torna
  segura é que a ausência já tem significado escrito.
- A FDD 006 descrevia a jornada como `Welcome → Discover → Prove → Scale → Optimize`, que
  não é a escada da FDE. A frase foi corrigida com a retificação registrada, e não apagada.
  A menção da FDD 028 **não** foi tocada: ali "Welcome→Optimize" descreve o estado da tela
  no dia em que aquele problema foi levantado, e é registro histórico.

### Fica aberto

- **No Pulse:** emitir `canonical_stage`, `gate_decision` e `requires_gate` na projeção —
  não há issue lá para isso —, e decidir se `Welcome` continua classificada como
  `discover`.
- O guard de visibilidade por campo (#87), KPI/Baseline/Outcome/Value Ledger (#89),
  Finding/PainPoint (#90) e o lint de linguagem (#91) continuam abertos. A asserção de
  vocabulário desta fatia é **pontual**, sobre a superfície que ela tocou: ela não varre
  o repositório, e é a #91 que faz isso.
- `ai_score` continua sem consumidor deste lado, e de propósito.
