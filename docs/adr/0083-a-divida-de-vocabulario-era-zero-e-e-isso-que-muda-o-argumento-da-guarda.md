# ADR 0083 — A dívida de vocabulário era zero, e é isso que muda o argumento da guarda

**Status:** aceito
**Data:** 28/08/2026
**Fase:** 7

> Quarta fatia da adoção do [Language Map v1.1](../ontology/language-map.md) neste
> repositório (Issue #91). A [ADR 0079](0079-engagement-como-raiz-da-navegacao-e-a-conta-que-se-chamava-cliente.md)
> trouxe o documento normativo e o Engagement; a [ADR 0081](0081-o-degrau-que-a-jornada-nao-atravessava-e-o-piloto-que-o-prove-nao-e.md)
> atravessou o degrau canônico e a decisão de gate; a [ADR 0082](0082-o-que-o-one-nunca-expoe-e-a-negacao-por-omissao.md)
> publicou a lista positiva do que sai por rota de cliente. Esta é a que impede o
> vocabulário de voltar a divergir.

## Contexto

A §6 do Language Map abre com a frase que esta fatia existe para cumprir: *"Estas viram
teste automatizado no Pulse e revisão de PR nos dois repos."* Revisão de PR é o mecanismo
que a [ADR 0034](0034-a-telemetria-que-o-runbook-prometia-e-o-codigo-nao-emitia.md) já
mediu e reprovou — lá o `alerts.md` foi corrigido à mão, ficou sem portão, e **em dois
dias divergiu de novo pelo outro lado**.

Só que a varredura desta fatia achou o que ninguém esperava: **a dívida é zero**.

| o que a §5 bane | ocorrências no repositório |
| --- | --- |
| `opportunity` sem qualificador | **0** — a única no repositório inteiro está num *comentário* de `tests/api-contract.test.mjs:980` que explica a própria regra |
| `client` como organização | **0** — as 36 declarações que carregam o token são 8 React Client Components mais 28 sobrevivências decididas: o lado (as pessoas do cliente), OAuth, transporte HTTP e a família 4xx |
| `GateOutcome` | **0** — as quatro citações são **notas históricas** explicando o rename da D7 |
| nome de modelo em português | **0** |
| "Cockpit", "portal do cliente", "portal Biahflow", "o CRM" | **0** em texto visível |
| "piloto", "POC", "MVP" para o PROVE | **0** em texto visível (a #88 apagou as últimas) |

Isso não é erro de medição, é resultado das três fatias anteriores — e **muda o
argumento**. Uma guarda que nasce vermelha se justifica pelo vermelho: a ADR 0033 nasceu
com catorze campos, a ADR 0035 com cinco pares, a ADR 0054 com catorze ADRs. Esta nasce
verde, é **preventiva** e não pagadora de dívida, e por isso o peso inteiro dela cai na
**medição por mutação** ([ADR 0065](0065-medir-a-guarda-por-mutacao.md)): sem vermelho de
nascença para exibir, a única prova de que ela vale alguma coisa é a tabela de baixo.

## Decisão

### D1 — Uma guarda só, em `pytest`, sobre os dois deployables

`apps/api/tests/test_vocabulary.py`, dentro do job `api-quality` que já existe. **Sem job
de CI novo e sem regra de eslint**, e os três motivos são medidos:

1. `eslint.config.mjs:9-17` ignora `apps/**`. Uma regra de eslint **nunca alcançaria o
   lado Python** — e "guarda que para na fronteira do pacote" é literalmente o defeito que
   a [ADR 0035](0035-as-guardas-que-eram-listas-digitadas.md) consertou na varredura de
   telemetria, onde o BFF emitia quatro eventos e nenhum tinha runbook porque a guarda
   parava no pacote Python. Repetir aquele defeito ao construir a guarda que existe para
   impedi-lo seria difícil de defender.
2. O precedente que a issue invoca (`test_vocabulario.py`, do Pulse) é **um teste**, não um
   linter.
3. A allowlist com contagem, razão obrigatória e asserção de obsolescência não cabe numa
   regra de eslint sem virar um plugin — e um plugin seria um segundo mecanismo de exceção,
   que é o que o `advisories.json` da ADR 0023 existe para não ser.

**O critério de aceite da issue que diz "`npm run lint` falha" fica emendado, não fingido.**
O que ele quer é que o repositório reprove; o que ele nomeia é a ferramenta errada para
metade do repositório. Precedente [ADR 0038](0038-a-citacao-sem-data-e-o-portao-que-nasceu-cego.md),
que corrigiu o `context-contract.md` em vez de carimbar data no marco: **corrige-se o
documento, não se finge a promessa.** Quem quiser o portão no `npm run lint` está pedindo
duas guardas sobre a mesma afirmação, e duas guardas sobre a mesma afirmação divergem.

### D2 — O casamento é sobre batismo, nunca sobre referência de uso

A guarda olha declaração — `class`, `def`, campo, constante de módulo, `type`, `interface`,
`const`, `function`, `let`, chave de enum. Não olha referência.

Não é preciosismo. `app/DashboardClient.tsx:1740` e `:1910` citam `GateOutcome` em duas
notas que explicam **por que** a D7 renomeou o termo; `models/project.py:105` e a migração
`0039_journey_canonical_stage.py:69` fazem o mesmo. Uma guarda por referência cobraria que
o repositório **apagasse o registro da própria decisão** — que é exatamente o que a ADR
0034 teve de contornar ao fazer a guarda de eventos ignorar as notas históricas do
`alerts.md`.

**A assimetria entre os dois lados é deliberada e foi medida.** Em Python a guarda lê
atribuição em nível de módulo e de classe; em TypeScript lê `const`/`let` em qualquer
profundidade. A razão é que `const` é a única forma de declarar um valor em TS, então
restringir por profundidade isentaria o corpo inteiro de todo componente — e
`stuckOnClient`, o caso que carrega esta fatia, mora dentro de uma função. Do lado Python,
incluir os locais acrescentaria **20 ocorrências**, das quais **10** são o literal
`client = <cliente boto3>` de `storage.py`: vocabulário de transporte, sete linhas de
allowlist dizendo a mesma coisa sete vezes. O que se perde está nos itens abertos.

### D3 — A allowlist não nasce vazia, e só encolhe

`docs/ontology/legacy-allowlist.txt`, no formato `caminho::regra::identificador::contagem`
do precedente do Pulse, com a razão escrita no bloco de comentário acima de cada corrida de
linhas. Vinte e sete entradas, e nenhuma delas é dívida: são as **sobrevivências
decididas** — `Blame.client` e `_client_has_authenticated` são o *lado* (as pessoas do
cliente) e não a organização, `client_member` é papel de pessoa e já era sobrevivência
registrada na ADR 0079, `client_id`/`client_secret` são a RFC 6749, `CLIENT_ERRORS` é a
família 4xx da RFC 9110, `session_client` e `_jwks_client` são transporte.

Uma allowlist vazia é o defeito que a ADR 0033 nomeou (*"seguia vazia porque nada a
consultava"*) e a asserção sobre lista vazia que a ADR 0082 registrou (*"não percorre ramo
nenhum"*). Esta nasce carregando o repositório inteiro, o que também é o que a torna
**mensurável**: cada linha é um ramo que a suíte percorre a cada push.

**Sem `review_by` e sem prazo**, no precedente do `PINNED_BY_EXCEPTION`
([ADR 0063](0063-o-pino-que-a-varredura-nunca-viu.md)) e do `FOUNDATION_WITHOUT_A_LINE`
([ADR 0054](0054-o-indice-canonico-e-as-decisoes-que-ele-nao-conhecia.md)) e **não** no do
`advisories.json`: dívida de vocabulário não caduca por calendário — ela some no dia em que
o termo sai do código. O vencimento é a asserção de obsolescência, e ela tem **duas** formas
de acender, porque a contagem é campo separado: a ocorrência sumiu, ou a contagem caiu
(orçamento sobrando é a carona que o campo existe para fechar).

### D4 — O rótulo de projeção do ROI fica fora, e é item nomeado

A última linha da §5 ("ROI" como resultado → `Outcome`, depois `Value`) **não vira regra**.
É afirmação sobre **renderização**, não sobre léxico: o defeito real é
`DigitalEmployee.roi_month` sair como "ROI/mês R$ X" em `app/DashboardClient.tsx:2709` sem
o rótulo de projeção ao lado, e nenhuma varredura de fonte decide se o rótulo está lá. O
identificador está certo — o ROI deste repositório é calculado na leitura pela premissa
vigente no dia do evento (ADR 0013) e declara lacuna quando falta base. É a **Issue #89**,
e a razão está escrita no `UNLINTABLE` da guarda, não implícita na ausência.

### As seis regras saem do documento, e o documento cobra as seis

Nenhum termo é digitado. Os qualificadores de `opportunity` saem dos dois nomes canônicos
em backtick da célula "Usar" da §5; **as três exceções nomeadas** (Opportunity Score,
Opportunity Map, Improvement Opportunity Backlog) saem das frases em negrito da mesma
célula; `client`, `GateOutcome`, `Evidencia`/`Processo`/`ProcessoEtapa`, "Cockpit", "portal
do cliente", "portal Biahflow" e "o CRM" saem das linhas correspondentes; e o **MVP**, que
a §5 não tem, sai da coluna "Nunca chamar de" da linha `ProveExperiment` da §2. Lista
digitada à mão é o defeito das ADRs 0033 e 0035, e aqui teria a agravante de deixar a
guarda banir em nome de um termo que o documento normativo não conhece.

A relação é **bidirecional**, no precedente da guarda de eventos da ADR 0034: cada uma das
onze linhas da §5 é reivindicada por uma regra **ou** excluída com razão escrita em
`UNLINTABLE` (as quatro são a "Opportunity Score" de uma venda, `Lead.ai_score`,
`Project.ai_opportunity` e o ROI da D4). Linha da §5 que ninguém reivindicou reprova, e
exclusão que sobreviveu à linha reprova também.

### A ADR 0082 cedeu `opportunity` para cá de propósito

Está escrito lá: *"a proibição de `opportunity` não entrou como termo de contrato, porque
'Opportunity Score', 'Opportunity Map' e 'Improvement Opportunity Backlog' são exceções
nomeadas na §5 — rótulos de entregável, não identificadores. Onde essa palavra tem de ser
vigiada é na UI, e isso é a issue #91: se esta guarda a banisse por identificador, ela e o
lint colidiriam."* A proibição **não** foi reintroduzida no lado do contrato, e a regra
daqui reconhece as três exceções por construção — parseadas do documento, não digitadas.

## A armadilha que carrega a fatia

Oito componentes se chamam `…Client` — `DashboardClient`, `FunnelClient`, `KnowledgeClient`
e mais cinco. São **React Client Components**, e `Client` ali é vocabulário do React. A
isenção óbvia é pelo *arquivo*: `*Client.tsx` inteiro fica de fora.

Ela está errada, e o erro é mensurável: **`stuckOnClient` mora dentro de
`app/admin/funnel/FunnelClient.tsx`** (linha 111). Uma isenção por arquivo o perdoa junto,
**sem nada ficar vermelho** — é o `.priority` da ADR 0033 e o corpus único que aquela ADR
mediu.

A isenção correta é pela forma do **identificador**: o nome que é o `export default
function` do módulo *e* coincide com o basename do arquivo, num módulo que declara
`"use client"`. As três condições ao mesmo tempo, e as três medidas (mutações 9a/9b e o
par de asserções em `test_the_client_exemption_is_by_identifier_and_not_by_file`).

## Medição por mutação

Harness em Python, com asserção de que o alvo mudou e restauração no `finally` (ADR 0065).
Dezoito mutações. Como a guarda nasce verde, **as verdes provam tanto quanto as vermelhas**:
são elas que separam esta guarda de uma que banisse por substring.

| # | mutação | esperado | obtido |
| --- | --- | --- | --- |
| 1 | `class OpportunityOut` em `schemas.py` (API) | vermelha | **vermelha** |
| 2 | `const clientProjects` em `app/page.tsx` (BFF) | vermelha | **vermelha** |
| 3 | `class ImprovementOpportunityOut` (qualificado) | verde | **verde** |
| 4 | `OPPORTUNITY_SCORE_LABEL` (rótulo de entregável da §5) | verde | **verde** |
| 5 | `class GateOutcome` reintroduzida | vermelha | **vermelha** |
| 6 | `class PhaseEventOutcome` (outcome **de evento**) | verde | **verde** |
| 7 | `class Evidencia` no núcleo | vermelha | **vermelha** |
| 8 | nota histórica citando `GateOutcome` e `client` num comentário | verde | **verde** |
| 9a | `stuckOnClient` → `clientRows`, **isenção por arquivo** | verde | **verde** — a armadilha |
| 9b | `stuckOnClient` → `clientRows`, **isenção por identificador** | vermelha | **vermelha** |
| 10 | ocorrência nova sob chave já isenta (carona) | vermelha | **vermelha** |
| 11 | contagem da allowlist maior que a realidade | vermelha | **vermelha** — obsolescência |
| 12 | o termo sai do código e a linha da allowlist fica | vermelha | **vermelha** — obsolescência |
| 13 | isenção com a razão apagada | vermelha | **vermelha** |
| 14 | linha da §5 apagada do Language Map | vermelha | **vermelha** — dez asserções |
| 15 | termo novo na §5 sem regra que o cubra | vermelha | **vermelha** — bidirecional |
| 16 | arquivo nomeado no corpus que não existe | vermelha | **vermelha** — fail-closed |
| 17 | raiz do pacote Python renomeada (glob vazio) | vermelha | **vermelha** — fail-closed |
| 18 | backtick some da §5 e o casador para de casar | vermelha | **vermelha** |

As que carregam o argumento:

- **9a e 9b são o par inteiro.** Sozinha, a 9b só diria que a guarda pega `clientRows`. É a
  9a — **verde**, com a versão ingênua da guarda — que prova que a isenção por arquivo
  deixaria passar o caso real, e é por isso que ela foi rodada contra uma guarda
  deliberadamente enfraquecida em vez de argumentada.
- **A 6 é a que separa esta guarda de um banimento do token `outcome`.**
  `AgentEventOutcome` e `agent_event.outcome` existem e são legítimos: a §6.3 fala de
  `outcome` *referindo-se a decisão de gate*, e o casamento é da sequência contígua
  `gate`+`outcome`. Um banimento da palavra nasceria vermelho em cima de campo correto.
- **A 8 é a que impede a guarda de cobrar apagamento de registro.** Verde com as duas
  palavras banidas num comentário — o comentário sai por construção no autômato que separa
  código de texto, o mesmo recorte por forma que a ADR 0064 usou para a fence de estrutura.
- **A 18 é o fail-closed do documento.** Se alguém reformatar a §5 e o casador parar de
  casar, as seis regras passariam a não banir nada e a suíte ficaria **verde** — o
  `dependency-review` da ADR 0023 outra vez. Ela reprova em dez asserções.

## A colisão com `tests/rendered-html.test.mjs`, medida

A fatia da #88 deixou ali a asserção *"a tela do cliente não chama o PROVE de piloto, POC ou
MVP"*, sobre o HTML renderizado. A regra `prove-nao-e-piloto` desta fatia parece duplicá-la,
e **duas guardas sobre a mesma afirmação divergem** (ADR 0034). Medido antes de decidir:

| mutação | a guarda nova (fonte) | `rendered-html` (HTML servido) |
| --- | --- | --- |
| literal `piloto` numa constante de `DashboardClient.tsx` que a fixture não renderiza | **vermelha** | verde |
| literal `piloto` na fonte **e** renderizado (com rebuild) | **vermelha** | **vermelha** |
| `piloto` vindo da **API** (`tests/fixtures/dashboard.mjs`), fonte intocada | verde | **vermelha** |

**As duas ficam**, e os corpora são distintos **nos dois sentidos**: a guarda nova enxerga o
literal que a fixture nunca exercita (um rótulo de estado que aquele dado não alcança), e a
`rendered-html` enxerga a palavra que nunca esteve em fonte nenhuma porque chegou pela API —
que é exatamente a razão escrita no docstring daquela asserção (*"um literal numa fixture e
um literal num componente produzem a mesma linha na tela"*). Nenhuma é superconjunto da
outra, então nenhuma sai.

De quebra, a medição achou uma propriedade que ninguém tinha escrito: **`rendered-html`
serve o `.next/` construído antes da mutação**, então uma mudança de fonte sem `npm run
build` não a alcança. Sem rebuild, a linha do meio da tabela sairia "verde" e a conclusão
seria a errada — uma mutação malformada se disfarça de guarda fraca (ADR 0082).

## Consequências

- Termo fora do vocabulário canônico reprova em `api-quality`, nos **dois** deployables, em
  identificador e em texto visível ao cliente.
- Sobrevivência nova custa uma linha com razão escrita, e a razão tem piso de 40 caracteres:
  **uma isenção cuja razão ninguém consegue escrever é uma isenção que não devia existir**
  (o argumento da lista positiva da ADR 0082).
- O `language-map.md` passou a ter portão nos dois sentidos: mudar a §5 sem decidir o que a
  regra faz reprova, e é assim que a §8 (*"termo novo entra primeiro nesta página"*) deixa de
  depender de disciplina.
- O documento **não foi editado** por esta fatia. A varredura não achou divergência entre o
  mapa e o repositório, então não houve o que registrar antes de corrigir (regra de
  manutenção da §9).

## Itens abertos, nomeados

1. **Local Python não é declaração.** Uma variável local chamada `client_rows` dentro de uma
   função passa. O recorte é o da D2 e o preço está medido (20 ocorrências, 10 delas o
   `client` de transporte de `storage.py`); fechá-lo é trocar uma allowlist de 27 linhas por
   uma de 34 que diz sete vezes a mesma coisa. Parâmetro também fica de fora, pela mesma
   razão e com a agravante de que metade deles é a palavra que a biblioteca chamada fixa.
2. **Português sem acento e não nomeado na §5 não tem portão.** A regra `modelo-em-portugues`
   alcança os três nomes que o documento lista (`Evidencia`, `Processo`, `ProcessoEtapa`) e,
   estruturalmente, qualquer identificador com letra fora do ASCII (`Reunião`, `Solução`).
   Um `class Fatura` novo passa. Decidir "isto é português" sem lista digitada não é
   decidível, e uma heurística que nascesse verde seria pior que a lacuna declarada.
3. **A direção `one-visibility.json` → tabela mestra ficou de fora, e foi medida.** A
   proposta era cobrar que todo nome de esquema publicado cujo token seja vocabulário de
   domínio corresponda a um termo da §2. Medindo: os tokens da coluna "Nunca chamar de",
   tirados os que também são canônicos, são **48** — e incluem `a`, `de`, `no`, `os`,
   `solto`, `sozinho`, `campo`, `modelo` e `estimativa`, que são prosa da célula, mais
   `score`, que a própria §5 nomeia como exceção. Contra os 41 esquemas do artefato, o
   predicado acende **`MeetingOut`, `NextMeetingOut` e `RoiOut`**, os três legítimos: a
   coluna é escopada à *sua linha* ("não chame **DiscoverySession** de Meeting"), e uma
   varredura por token perde esse escopo — banindo uma palavra em nome de uma regra sobre
   outra entidade, que é o `.priority` da ADR 0033 pelo avesso. O `RoiOut` ainda arrastaria
   de volta a D4. Fica registrado como medição, e não como trabalho adiado: a metade
   decidível — todo termo que uma regra bane existe no mapa, e nenhuma regra fica sem termo —
   está implementada.
4. **Texto visível é o que a guarda consegue ver como texto.** Uma frase montada por
   concatenação em tempo de execução, ou vinda do banco, não é alcançada pela varredura de
   fonte — e é justamente para essa metade que `tests/rendered-html.test.mjs` continua
   existindo, agora com a razão medida.
5. **O `ROI` sem rótulo de projeção continua na tela** (`app/DashboardClient.tsx:2709`), e é
   a Issue #89 — junto de `KPI`, `Baseline`, `Outcome` e `ValueLedger`. `Finding`,
   `Evidence` e `PainPoint` são a #90.
