# ADR 0087 — A busca que não alcançava o Discovery, e o corte que zerava os trechos

**Status:** aceito
**Data:** 02/09/2026
**Fase:** 7

> Fecha o item aberto que a [ADR 0086](0086-a-superficie-de-discovery-que-o-cliente-le-e-a-marca-de-publicacao-que-nunca-atravessa.md)
> declarou em vez de deixar por dizer: *"a busca não alcança o Discovery"*. É a
> `biahflow/one#102`, e ela **não** depende de `biahflow/pulse#108` — o que aquela
> issue destrava é a aba ter dado; esta é sobre a busca alcançar o dado quando ele
> chegar.

## Contexto

A regra da busca está escrita desde a Fase 6, na §5 da
[ADR 0024](0024-busca-no-projeto.md):

> *"Só entra o que o cliente já alcança por alguma aba. A busca não é uma segunda
> porta para o read model: é um atalho para o que já está na tela."*

A ADR 0086 acrescentou **quatro listas** à tela do cliente — Process (com etapas),
Findings (com evidências), Pain Points e o Improvement Opportunity Backlog — e a
busca ficou onde estava. A própria ADR registrou o item como aberto, com o
diagnóstico correto: ligá-las pede `Hit`, espaço de nomes de âncora e `data-item`
nos quatro blocos, com as guardas de `test_item_anchor.py` junto.

Faltavam três camadas, e nenhuma delas era opcional:

1. **Nenhum repositório para o Discovery.** As seis entidades de
   `models/discovery.py` não tinham `TenantScopedRepository`; a única leitura era o
   `select()` cru de `_discovery_projection`, que é caminho de **projeção do
   snapshot** sob `portal_system`. Sem repositório, a busca teria de montar o filtro
   de tenant dentro de `search.py` — exatamente o que a ADR 0024 §2 proíbe, e pelo
   motivo que continua valendo: a divergência entre as duas barreiras não deixaria
   nada vermelho, porque a RLS continuaria certa e o teste de isolamento, verde.
2. **Nenhum espaço de nomes de âncora.** `anchors.py` tinha seis e nenhum para as
   quatro espécies novas.
3. **A aba não desenhava `data-item` e não recebia `focusedItem`.** O clique num
   resultado de Discovery cairia na aba certa e em lugar nenhum dentro dela — o
   defeito silencioso que `test_item_anchor.py` existe para pegar.

## Decisão

### 1. A âncora do Discovery sai por `id`, e a bifurcação é só na metade da direita

O mecanismo é `namespace:rótulo` desde a [ADR 0056](0056-o-link-que-caia-no-item.md),
e ali o `id` foi recusado por duas razões. **As duas são nulas aqui**, e isso foi
verificado antes de decidir:

- *"o campo não existe nos esquemas de lista"* — `ProcessOut.id`, `FindingOut.id`,
  `PainPointOut.id` e `ImprovementOpportunityOut.id` **são publicados** desde a ADR
  0086;
- *"o uuid local é recriado a cada sync"* — o que sai naqueles campos **não é** o
  uuid local. É o `external_id`, e o docstring de `_discovery_projection` diz isso
  com todas as letras: *"o que sai é o id da origem, nunca o uuid local"*.

O critério que a ADR 0056 aplicou — *publica-se na URL o que a tela já usa como
identidade* — aponta para o `id` aqui, porque as chaves de lista dos quatro blocos
**já são** `item.id`. E ancorar por texto esbarraria no `Finding`, que não tem
`title`: tem `statement`, que é uma frase e pode ser um parágrafo.

O preço é uma segunda forma de âncora no repositório, e ele foi pago da forma mais
barata que existe: um campo opcional `Hit.anchor_id`, e `Hit.anchor` usando-o quando
presente. **A forma das outras cinco espécies não muda** — ali o rótulo continua
sendo o `title`, que é o que a tela desenha como `data-item`. O separador continua
`:` sem escape e quem consome continua comparando a string inteira.

### 2. Hipótese e lacuna entram na busca, sempre rotuladas — e o rótulo vem da API

Esta é a decisão que pesa. A regra 1 da §3 do Language Map é que um `Finding` com
`epistemic_status=hypothesis` aparece **rotulado** como hipótese ou não aparece,
nunca como fato. O `Hit` tinha `kind`, `title`, `detail`, `location` e `tab`, e
**nada que carregasse estado epistêmico**: um resultado com o `statement` cru é uma
afirmação sem rótulo, que é a leitura de fato por omissão — o defeito exato que a ADR
0086 existe para impedir, reaparecendo por uma porta que ela não olhou.

Excluir hipótese e lacuna foi recusado: faria a busca ser uma **segunda régua** sobre
o mesmo dado que a aba já mostra rotulado, e a lacuna aparece de propósito, porque um
levantamento que só mostrasse o que ficou sabido esconderia do cliente o que ainda
não se sabe.

O rótulo viaja no `detail`, pronto da API, pelo argumento que a ADR 0024 já tinha
escrito para o `tab`: *um segundo mapa do lado do navegador envelheceria sozinho*.

O preço é o modo de falha do `textfold.py` — o mesmo literal em dois deployables que
**têm** de ser idênticos —, e ele vem com guarda no mesmo commit:
`test_ready_made_labels.py` lê o `EPISTEMIC_LABEL` do `DashboardClient.tsx` por regex e
o compara com o mapa da API, na técnica que `test_item_anchor.py` já usa para ler o
`data-item`. Os três valores são os que a aba já desenhava: `Fato`, `Hipótese`,
`Pergunta em aberto` — nenhum vocabulário novo foi inventado.

Duas asserções acompanham, e cada uma fecha um buraco diferente: a comparação é de
**dicionário inteiro** e não de conjunto de valores, senão trocar `hypothesis` por
`unknown` de um lado só produziria os mesmos três textos com o significado invertido;
e todo membro do enum precisa de linha no mapa, o que é o que permite ao produtor
indexar direto — um `.get(..., "")` faria o esquecimento **apagar o rótulo**, que é a
falha que a decisão inteira existe para impedir.

### 3. Filho casa, pai é o hit

`ProcessStep` tem sete colunas de texto que o cliente lê e `SolutionHypothesis` tem
três, e as duas vêm **aninhadas** no pai que a aba desenha como linha. Casar nelas
produz hit **do pai**, que é o *"a âncora é do objeto, não do fato"* da ADR 0056 e o
precedente literal de `chunk`→`document` no mesmo arquivo.

Um processo cujo nome **e** cujas etapas casam produz **um** hit, não dois: sem o
dedupe a lista mostraria a mesma linha duas vezes com âncoras idênticas, e o teto por
espécie passaria a ser gasto por duplicata. O nome ganha, e ali o `detail` fica
vazio; vindo do filho, o `detail` é o nome da etapa — sem ele o cliente veria um
processo na lista sem ter como saber por que ele apareceu.

**`Evidence` fica de fora, e a razão está escrita no código.** Ela é JSONB dentro do
`Finding` e não coluna, e é o ponto cego do guard de visibilidade da ADR 0082 —
`raw_excerpt` e `content_hash` são barrados por lista branca na ingestão (ADR 0086).
Buscar dentro do blob acrescentaria uma superfície onde aquele guard não enxerga.

### 4. O `detail` mostra o que a aba mostra, e nada além

O recorte da fatia dizia `detail = pain.status` e `detail = opportunity.status`,
justificando pelo precedente do `meeting.status`. **A construção mediu, e o precedente
não se sustentou** — nas duas metades:

- os dois campos guardam o **código cru da origem** (`confirmed`, `backlog`), gravados
  por `_text(item.get("status"))` sem tradução nenhuma;
- e **nenhum bloco da aba os desenha**: a dor mostra título, impacto, descrição e os
  achados que a sustentam; a oportunidade mostra título e Opportunity Score.

O cliente leria `Retrabalho na conferência • confirmed`: código em inglês na tela de
um produto cujo texto visível é PT-BR, para um valor que a aba não mostra. É a fatia
quebrando, no mesmo campo que ela veio preencher, a regra que ela veio impor — a ADR
0024 §5 ao contrário, porque a busca passaria a mostrar **mais** do que a aba.

As duas espécies saem com `detail=""`, com a razão no docstring de cada função. É o
mesmo argumento que já barrava o `impact_estimate` (ADR 0086: o número sem a frase que
a aba escreve em volta dele), estendido ao campo vizinho.

**A regra não é "não mande detalhe"**, e o par que a define está no processo: lá o
`detail` existe porque a etapa que casou tem **nome** e a aba o desenha na tabela. A
regra é *não mande o que a aba não mostra* — a §5 da ADR 0024 dita pelo lado do
conteúdo, e não pelo lado da espécie.

### 5. O irmão mais velho do mesmo defeito, achado e fechado aqui

`search.py` mandava `detail=meeting.status` desde a Fase 6 — `held`, `scheduled` —
enquanto a aba Reuniões desenha **"Realizada"** e **"Agendada"**, traduzidas pelo BFF
em `app/page.tsx`. **O mesmo valor com dois nomes**, conforme a porta por onde o
cliente chega na mesma reunião, e nada ficava vermelho.

É a ADR 0033 numa direção que ninguém tinha olhado. Lá era um painel sobre campo **sem
escritor**; na ADR 0043, um controle sobre campo sem escritor. Aqui o campo tem
escritor dos **dois** lados, e os dois discordam — o que a guarda de consumo não pega,
porque ela pergunta se há consumidor, e há.

Fechado nesta fatia e não numa issue própria, porque ela construiu o mecanismo exato de
que ele precisava e o mecanismo é caro de montar duas vezes: rótulo pronto saindo da
API (decisão 2) mais guarda comparando os dois deployables. Deixá-lo aberto seria
publicar o remédio ao lado da doença.

`MEETING_STATUS_LABEL` mora ao lado do `EPISTEMIC_LABEL`, com os valores **idênticos**
aos do BFF — que não mudou. A guarda ganhou a comparação e o arquivo mudou de nome
(`test_ready_made_labels.py`), porque ele deixou de guardar uma promessa e passou a
guardar a família: *o rótulo que a API manda pronto é o que a tela desenha*.

**A indexação é indireta aqui e direta lá, e a assimetria é consciente.** O estado
epistêmico é um `enum` de três membros, então a completude é enumerável e tem guarda —
daí indexar direto, com o argumento de que um `.get(..., "")` apagaria o rótulo.
`Meeting.status` é `String` **por decisão escrita no próprio modelo** (*"para que uma
nova opção lá não exija migração de enum aqui"*): não há domínio fechado a enumerar e
nenhuma guarda de completude é possível. A queda é para o **código cru**, que é
exatamente o que o `?? meeting.status` do BFF já faz — duas portas caindo de formas
diferentes recriaria o defeito que a tabela conserta, trocando "dois nomes para o mesmo
valor" por "um nome e um vazio". E é código cru e nunca vazio, porque sumir com o valor
esconderia do cliente que a origem passou a dizer algo que este lado ainda não sabe
ler. A asserção da queda lê **a linha do BFF** além da da API: é o que a torna uma
afirmação sobre as duas portas, e não sobre uma.

### 6. Sem índice e sem migração

As cinco espécies de read model casam por `ILIKE` sobre a expressão dobrada, sem
índice; o único GIN do repositório é o `ix_document_chunk_text_fts` da migração
`0019`. A consistência diz que o Discovery entra igual, e **esta fatia não tem
migração**. Criar índice para quatro tabelas seria decisão própria, com o argumento
do custo de escrita no fan-out da ADR 0086 — que substitui os quatro blocos inteiros
a cada sync de **qualquer** projeto da conta.

### 7. O corte por `TOTAL_LIMIT` passa a ser rodízio, e isso conserta um defeito anterior

`search_project()` cortava `hits[:TOTAL_LIMIT]` **em ordem de inserção**, e os trechos
de documento entram por último. Com `PER_KIND_LIMIT=5` e cinco espécies de read model
antes deles, **25 candidatos já disputavam 20 vagas**: um projeto com vinte linhas
casando derrubava os trechos inteiros, antes de qualquer Discovery. Com nove espécies
são 45 candidatos, e o silêncio dos trechos viraria o caso comum.

E os trechos são precisamente o que a ADR 0024 §4 diz fazer a promessa valer:

> *"Sem os trechos, 'buscar no contexto do projeto' entregaria uma lista de títulos:
> a versão do controle que parece funcionar e não responde à pergunta que alguém
> realmente faz, que é onde está a cláusula de rescisão."*

`_fit()` reparte as vinte vagas **em rodízio** entre as espécies que casaram: cada
rodada dá uma vaga a cada uma que ainda tem candidato, e a sobra volta para quem tem.
Rodízio e não fatia igual, porque fatia igual desperdiça — com duas vagas por espécie,
uma espécie com um hit só devolveria a vaga a ninguém. A **saída continua agrupada por
espécie** e não intercalada: o rodízio decide *quantos* de cada um entram, não em que
ordem eles saem.

Aumentar o `TOTAL_LIMIT` foi recusado: adia o problema sem consertá-lo, e a disputa
volta no primeiro projeto grande.

`_fit` é pura e tem teste **sem Postgres** (`test_search_quota.py`), porque o defeito
é aritmético e um teste que precisasse do banco para exercitá-lo seria um teste que
**pula** na máquina de quem não subiu o banco — que é como as três asserções do backup
passaram semanas sem rodar (ADR 0019). O par com o mundo real está em `test_search.py`.

## Consequências

- **A regra da ADR 0024 §5 volta a valer.** As quatro listas que a aba mostra são
  alcançáveis pela busca, e o clique cai **na linha**: `data-item` nos quatro blocos,
  `focusedItem` chegando ao `DiscoveryView` e `screenAnchors()` enxergando as quatro
  listas — sem esta última o `openSearchHit` descartaria a âncora, porque ele só
  navega com âncora que o conjunto da tela conhece.
- **Uma reunião deixou de ter dois nomes.** O `detail` de `meeting` passou a sair
  traduzido da API, com os valores do BFF e sem tocá-lo. As quatro mutações foram
  medidas e as quatro reprovam: `detail=meeting.status` cru, um rótulo divergente entre
  os dois mapas, a queda para vazio em vez do código cru, e `detail=pain.status` de
  volta.
- **A guarda do `data-item` estava cega para `snake_case`, e isso foi medido.** O
  casador de `test_item_anchor.py` era `data-item=\{`([a-z]+):`, e `pain_point` e
  `improvement_opportunity` têm `_`: a expressão **não casava de todo**, de modo que o
  namespace sumia do conjunto do TSX e a guarda de igualdade acusaria "só no Python"
  um atributo que está escrito ali. Uma letra a mais na classe de caracteres, e a
  razão fica escrita ao lado dela.
- **A guarda de vocabulário cobrou duas vezes durante a construção, e as duas estavam
  certas** (ADR 0083): `const opportunity of …` no `screenAnchors()` e
  `_opportunity_hit` no `search.py` são `opportunity` sem qualificador, que é a regra
  R1. Os dois viraram `improvementOpportunity`/`_improvement_opportunity_hit` — a
  saída é o termo canônico, não uma linha de allowlist.
- **Os quatro rótulos de espécie ficam em inglês na lista de resultados**, e é o
  vocabulário que a própria aba já desenha nos quatro blocos: `Process`, `Finding`,
  `Pain Point`, `Improvement Opportunity`. A §1 do Language Map é explícita — o termo
  canônico não se traduz, traduz-se o texto em volta dele —, e inventar "Processo" e
  "Achado" criaria um segundo vocabulário para a mesma lista.
- **Nenhum campo novo no contrato.** `anchor_id` é campo do `Hit` e não do
  `SearchHitOut`: a âncora continua viajando no `item_anchor` que já existia, e
  `docs/api/openapi.json` foi regerado sem diferença — o que o gate confirma sozinho.
  Nenhuma linha nova em `docs/contracts/one-visibility.json`, pela mesma razão.
- **Nenhum evento novo de telemetria**, e nenhuma linha em `docs/runbooks/alerts.md`.
  O `search.performed` continua levando `hits`, `kinds`, `term_length` e
  `duration_ms`; as espécies novas aparecem em `kinds`, que é o campo que já existia
  para isso. O termo digitado continua não saindo do processo (ADR 0024 §7).
- **O isolamento é provado nas duas camadas para o escopo de conta**, que é novo: as
  seis tabelas do Discovery não têm `project_id`, e as duas de ligação não têm chave
  de tenant nenhuma — a policy as alcança pelo pai. `TenantScopedRepository`
  já trata a ausência de `project_id` sozinho, e a asserção sob `rls_session` com
  `TenantContext` forjado vale por si: a de projeto não a cobre, porque o predicado é
  outro.
- **O que continua faltando, declarado:** enquanto `biahflow/pulse#108` não entregar a
  tela de publicação, as quatro listas chegam vazias e esta fatia não devolve resultado
  nenhum ao cliente — mesma posição em que a `#90` foi construída e mergeada. A busca
  segue **lexical**, então "o que trava o fechamento?" não acha um `PainPoint` cujo
  texto não contenha as palavras digitadas; quem responde essa pergunta é o chat. E o
  casamento do `Finding` é só sobre o `statement`: a evidência que o sustenta fica
  fora, com a razão escrita acima.

## Alternativas recusadas

**Ancorar o Discovery por texto, como as outras cinco espécies.** Manteria uma forma
só de âncora, e é o que a ADR 0056 decidiu — mas ali o rótulo *era* a identidade da
linha. Aqui a identidade publicada é o `id`, a tela já casa as quatro listas por ele,
e o `Finding` não tem rótulo curto a usar. Ancorar por um parágrafo é a âncora bem
formada que não casa com nada, que é o defeito silencioso desta família.

**Deixar hipótese e lacuna fora da busca.** Resolve a regra 1 da §3 por omissão, e é
pior: a aba as mostra rotuladas, e escondê-las na busca faria as duas superfícies
discordarem sobre o que o cliente pode ver — sem que nada explicasse a diferença.

**Um rótulo epistêmico derivado no navegador.** Evitaria o literal duplicado e
recriaria o problema que a ADR 0024 já resolveu para o `tab`: um segundo mapa que
envelhece sozinho. A escolha foi manter o literal nos dois lados **com portão**, que é
o que o `tabs.py` e o `anchors.py` já fazem.

**`detail = status` nas duas espécies do Discovery.** Era o recorte da fatia, e a
medição o derrubou: ver decisão 4. A alternativa fica registrada porque o precedente
que a sustentava — `meeting.status` — existia mesmo, e a saída não foi imitá-lo: foi
consertá-lo (decisão 5).

**Traduzir o `status` de dor e oportunidade, em vez de omiti-lo.** Resolveria o
inglês na tela e deixaria o outro erro de pé: a busca continuaria mostrando um campo
que a aba não desenha. Quando algum bloco passar a desenhá-lo, o rótulo pronto sai da
API pelo mecanismo da decisão 5, com a guarda junto.

**Hit da etapa e da hipótese, em vez do pai.** Daria um resultado por linha da tabela
interna, e nenhuma delas tem `data-item` — o clique cairia na aba e em lugar nenhum
dentro dela, que é literalmente o defeito que esta fatia veio corrigir.

**Índice GIN para as quatro tabelas.** Ver decisão 6. O fan-out da ADR 0086 substitui
os quatro blocos a cada sync de qualquer projeto da conta, e o custo de escrita seria
pago por uma busca que hoje varre listas de dezenas de linhas.

**Aumentar o `TOTAL_LIMIT`.** Ver decisão 7.
