# ADR 0084 — O ROI que a manchete não dizia ser projeção, e o radical que o deixaria passar

**Status:** aceito
**Data:** 01/09/2026
**Fase:** 7

> Quinta fatia da adoção do [Language Map v1.1](../ontology/language-map.md) neste
> repositório, e a que fecha a Issue #91. A [ADR 0083](0083-a-divida-de-vocabulario-era-zero-e-e-isso-que-muda-o-argumento-da-guarda.md)
> implementou seis das sete linhas da §5 e deixou a sétima nomeada como item aberto,
> com a razão escrita no `UNLINTABLE` da guarda. Esta ADR a implementa — e refuta
> metade do argumento que a adiou.
>
> É também a metade da **Issue #89** que tem produtor. A outra metade está bloqueada
> em `biahflow/pulse#105`, e a Issue #90 inteira em `biahflow/pulse#106`.

## Contexto

### Este repositório projeta dois ROIs, e só rotulava um

São coisas diferentes, com produtores diferentes, e os dois nomes já existem no código:

- **`RoiOut`** (`schemas.py:278`) é o ROI **projetado**. Vem no snapshot do Biahflow,
  montado em `portal.py:359-364` de lá a partir de `project.actual_value` e
  `project.cost`. É a promessa da origem sobre o projeto.
- **`ResultsOut`** (`schemas.py:178`) é o ROI **apurado**. Nasce na leitura, dos eventos
  que os agentes publicam, pela premissa vigente **no dia do evento** — a decisão da
  [ADR 0013](0013-eventos-dos-agentes-e-roi-apurado.md) — e declara lacuna em
  `gaps[]` quando falta base, em vez de dividir por zero.

O docstring de `RoiOut` já dizia, desde a ADR 0020, que "os dois convivem **rotulados**
na tela". Na aba Resultados isso era verdade: dois cards lado a lado, "ROI projetado" e
"ROI apurado". Fora dela, não era.

Quatro literais de texto visível ao cliente diziam "ROI" sem dizer **qual dos dois**:

| `app/DashboardClient.tsx` | Literal | O número que rotulava |
| --- | --- | --- |
| `2021` | `ROI do projeto` | o **projetado** — e é a **manchete** da visão geral |
| `2709` | `ROI/mês` | `roi_month` do Digital Employee, **projetado da origem** |
| `2809` | `…sem ele não há ROI a calcular.` | o **apurado** |
| `2881` | `Fórmula do ROI` | o **apurado** |

A manchete é a pior das quatro. É o primeiro número que o cliente lê ao abrir o portal,
imprime `+142%` com "R$ 214.000 de retorno" embaixo, e não há nada na tela que o distinga
de um resultado medido. A §5 do Language Map bane exatamente isso: **"ROI" como resultado
→ `Outcome`, depois `Value`**.

### A guarda prendia o defeito

`tests/rendered-html.test.mjs` afirmava `/ROI do projeto/` no HTML do SSR. Não é uma
guarda distraída: ela existe para provar que a tela renderiza do servidor. Mas o efeito
colateral é que **corrigir a manchete deixaria a suíte vermelha**, e a asserção que
protegia o produto passou a proteger o defeito. É o `.priority` da
[ADR 0033](0033-a-guarda-que-parecia-cobrir-o-contrato.md) numa terceira direção: lá o
painel estava sobre campo sem escritor, na
[ADR 0043](0043-o-canal-e-o-link-que-nao-existia.md) o controle estava sobre campo sem
escritor, e aqui a **asserção** está sobre o texto errado.

### E a §5 tinha uma linha sem regra

A ADR 0083 varreu as sete linhas da §5, implementou seis e deixou a do ROI de fora, com o
argumento escrito no `UNLINTABLE`:

> É afirmação sobre **renderização**, não sobre léxico: o defeito real é um número de ROI
> aparecer na tela sem o rótulo de projeção ao lado, e **uma varredura de fonte não
> consegue decidir se o rótulo está lá**.

## Decisão

### D1 — A varredura de fonte decide, e o que a ADR 0083 errou foi o recorte da pergunta

Metade daquele argumento está certa e continua valendo: **nenhuma varredura decide
adjacência**. Não há como uma regra léxica afirmar que o rótulo está *ao lado do número*,
porque o número chega em tempo de execução e o rótulo mora noutro nó da árvore.

A outra metade está errada, e a diferença é a pergunta. Não é preciso decidir adjacência
para pegar o defeito — basta decidir sobre **o próprio literal**:

> Todo texto visível ao cliente que diga "ROI" diz **qual** ROI é.

`ROI do projeto` reprova. `ROI projetado` passa. E o defeito que a ADR 0083 descreveu — um
número de ROI na tela sem rótulo — não tem como existir sem que algum literal diga "ROI"
sem qualificar, porque é o literal que nomeia o card.

Isso é a forma da [ADR 0066](0066-o-drop-column-que-nenhum-portao-veria.md), que refutou
metade do argumento da ADR 0035 com medição: o `alembic check` de fato não vê um
`op.drop_column`, mas o AST vê. Aqui, a varredura de fato não vê adjacência, mas vê o
rótulo.

A regra é `R7 = "roi-sem-rotulo-de-projecao"`, e mora em `test_vocabulary.py` junto das
outras seis — não num teste ao lado, pela razão que a ADR 0035 escreveu: o `alerts.md` é
um arquivo só e duas guardas sobre ele divergem. A §5 também é.

**Ela não cabe em `find_phrases`**, e a forma é a razão: lá a presença da frase reprova, e
aqui reprova a presença **sem** o qualificador. Fundir as duas faria a mais estreita
herdar o casador da mais larga.

### D2 — O qualificador sai do documento; o segundo é local e tem data de morte escrita

O termo sai da célula do termo da §5 (`"ROI"`, entre aspas, como os de `R5` e `R6`). O
qualificador sai da **célula "Por quê" da mesma linha** — *"ROI projetado não é resultado
medido"* —, pela palavra imediatamente depois do termo. Nenhum dos dois é digitado, que é
a regra que a ADR 0033 impôs e a 0035 generalizou.

`apurado` **não** sai do mapa, e não sairia: nos termos dele o lado medido chama-se
`Outcome`. Ele entra como `LOCAL_QUALIFIERS`, com a razão escrita ao lado e, mais
importante, com a **condição em que ele morre**: `Outcome` não tem produtor neste
repositório — o Pulse tem o modelo `Measurement` e não o emite no snapshot —, e `apurado`
é o nome pré-`Outcome` que a ADR 0013 deu ao lado medido. No dia em que o `Outcome`
atravessar, esta linha sai.

Uma isenção cuja razão ninguém consegue escrever é uma isenção que não devia existir, e
o piso de tamanho da razão é afirmado como na allowlist da ADR 0083.

### D3 — A superfície interna fica fora, por decisão escrita e com vencimento

A regra é sobre a tela do **cliente**. Uma tela do time que diz "ROI" sem qualificar está
falando com quem sabe qual dos dois é. `INTERNAL_SURFACES` tem duas entradas, cada uma
com a razão em prosa:

- **`app/admin/`** — é o mesmo recorte que o
  [`one-visibility.json`](../contracts/one-visibility.json) já usa e registra
  ("`/api/v1/admin/*` é superfície interna", ADR 0082). Não é allowlist nova; é o corpus
  que aquela decisão já desenhou.
- **`apps/api/src/portal_api/onboarding.py`** — o funil, cujo aviso é `_INTERNAL_ONLY`
  desde a [ADR 0040](0040-o-alerta-de-cliente-travado.md). O leitor de "Nunca viu o ROI" é quem
  vai ligar para o cliente travado.

E o vencimento: `test_every_internal_surface_exclusion_still_exempts_an_occurrence`
reprova quando um prefixo deixa de isentar qualquer ocorrência real, no precedente do
`test_the_allowlist_does_not_keep_a_line_that_stopped_being_needed`. Exclusão que parou de
ser necessária é allowlist disfarçada esperando a próxima ocorrência passar de carona.

### D4 — O que esta fatia **não** faz, e por que isso não é omissão

A Issue #89 pede quatro coisas que esta fatia não entrega, e a Issue #90 pede cinco
superfícies novas. Nenhuma delas tem produtor:

| O que a issue pede | Estado no Pulse |
| --- | --- |
| Value Ledger no lugar da manchete `roi` | `ValueLedgerEntry` **existe** (ADR 0055 de lá) e **não é emitido** |
| `DigitalEmployee` referencia KPIs em vez de carregar medição | `KPI`/`Measurement` **existem** e **não são emitidos** |
| Todo Outcome com o Baseline comparável ao lado | `Measurement(kind=outcome)` **existe** e **não é emitido** |
| Process, Finding, PainPoint, ImprovementOpportunity, SolutionHypothesis | **existem todos** e **nenhum é emitido** |

Medido: `build_snapshot` (`portal.py:185-373`) não tem uma chave sequer de nenhum deles, e
`signals.py` não tem receiver para nenhum — os treze cobrem outros modelos. Do lado de lá
isso está escrito como **decisão consciente**, não esquecimento: a FDD 049 diz *"o
`portal.build_snapshot` não muda… mexer ali é mudar a projeção do cliente — outro gate,
outro pacote"*, e a FDD 048 devolve a decisão para cá: *"isso é decisão do repo `one`"*.

Construir tabela, esquema ou tela para qualquer um deles seria **painel sobre campo sem
escritor** — o defeito que a ADR 0033 nomeou e o precedente mais citado deste repositório.
A decisão foi *produtor primeiro*, na forma da [ADR 0039](0039-o-funil-que-carimba-sem-expor.md)
("escritor primeiro, leitor depois"), e o que sai daqui é o contrato: `biahflow/pulse#105`
e `biahflow/pulse#106`, escritas com o payload proposto, as nulidades e o que nunca
atravessa, no precedente da `#71` de lá — o contrato de snapshot negociado entre as duas
sessões.

Uma decisão de forma daquelas issues merece registro aqui porque nasceu de um critério de
aceite deste lado: **`baseline` e `outcome` vão aninhados dentro do KPI**, não como lista
solta de `Measurement`. A #89 exige que Outcome sem Baseline seja *erro, não tela vazia*;
numa lista plana o pareamento vira disciplina do leitor, e disciplina do leitor quebra em
silêncio. Aninhado, o One não consegue renderizar um Outcome sem ter o Baseline em mãos, e
"mesmo KPI, mesma unidade, mesmo método" passa a valer por construção.

## A armadilha que carrega a fatia

O casamento do qualificador é por radical, para alcançar as flexões sem lista digitada.
O corte óbvio é o sufixo inteiro do particípio: `projetado` → `projet`.

**`projet` casa com "projeto".**

Ou seja: `ROI do projeto` — a manchete, o defeito exato que esta fatia existe para
rotular — passaria **verde**, dizendo-se qualificada pela palavra "projeto". A guarda
nasceria verde em cima do seu próprio caso central, que é o `.priority` da ADR 0033 outra
vez, agora dentro do casador em vez de dentro do corpus.

O corte passou a ser só a desinência (`[oa]s?$`), dando `projetad` e `apurad`. O preço
está declarado: `projeção`, o substantivo, **não** é qualificador. Hoje isso não custa
nada — nenhum texto com o token `ROI` o usa, e "Sem projeção no Biahflow" não tem o token
—, e o dia em que custar a falha é **visível**, não silenciosa: alguém escreve "ROI em
projeção" e a suíte fica vermelha com o motivo na mensagem.

A amostra sintética que fixa isso é a primeira linha vermelha do teste, e é ela — não o
código — que prova o corte.

## Medição por mutação

O harness é o da [ADR 0065](0065-o-nome-que-a-borda-nao-soube-que-mudou.md). A regra
**nasceu vermelha** nas quatro linhas da tabela do contexto e em nenhuma outra, o que é a
primeira medição e a que dispensa argumento: a guarda pega o defeito real.

| Mutação | Efeito | O que prova |
| --- | --- | --- |
| `_stem` corta o sufixo inteiro (`projet`) | **reprova** a amostra da manchete | o par que carrega a fatia: um radical curto demais nasce verde no caso central |
| a manchete volta a `ROI do projeto` | **reprova** `test_no_banned_term…` em `2021` | a regra alcança o defeito que a motivou |
| `app/admin/` deixa de casar | **reprova** com `MembersClient.tsx` e `FunnelClient.tsx` | a exclusão é sustentadora, não decorativa |
| prefixo ocioso em `INTERNAL_SURFACES` | **reprova** a obsolescência | o vencimento existe e funciona |
| casador do termo neutralizado | **reprova** os três testes novos, inclusive o fail-closed | a guarda não fica verde por parar de olhar |

O **par de superfície** é o que separa esta regra de uma allowlist: o **mesmo literal**
(`"premissas de ROI"`) passa em `app/admin/MembersClient.tsx` e reprova em
`app/DashboardClient.tsx`. A isenção não é sobre o texto, é sobre quem o lê. O mesmo par
existe do lado Python, onde a exclusão é um arquivo e não um diretório.

## Consequências

- A manchete da visão geral diz **"ROI projetado"**. O primeiro número que o cliente lê
  deixou de ter a cara de resultado medido.
- `tests/rendered-html.test.mjs` deixou de afirmar o defeito. É uma linha, e é a
  corroboração renderizada da regra léxica — o único dos quatro literais que o SSR
  alcança, porque a aba Resultados não é renderizada no servidor (só a ativa é), o que o
  próprio arquivo já registrava.
- A §5 do Language Map ficou **sem nenhuma linha órfã**: as sete têm regra, e o
  `UNLINTABLE` da guarda ficou com três entradas, todas sobre campos que não existem
  neste repositório. A relação bidirecional que a ADR 0083 montou continua valendo por
  construção, não por remendo.
- A razão de `RoiOut.net` no `one-visibility.json` — "rotulado como tal na tela" —
  **passou a ser verdade**. Ela descrevia a aba Resultados e era falsa sobre a manchete.
- A `legacy-allowlist.txt` **não** ganhou linha: nenhuma sobrevivência de ROI ficou. A
  dívida desta regra também é zero, pelo mesmo argumento da ADR 0083 — o peso cai todo na
  medição.
- Custo declarado: um texto novo que qualifique o ROI pela palavra "projeção" reprova. É
  falha visível com o motivo na mensagem, e não silêncio.

## Itens abertos, nomeados

- **A metade grande da #89 e a #90 inteira**, bloqueadas em `biahflow/pulse#105` e
  `biahflow/pulse#106`. Enquanto o produtor não sai, a manchete continua sendo o `roi`
  projetado — agora rotulado — em vez do Value Ledger.
- **`hoursSavedMonth` / "Horas/mês"** também é projetado da origem e continua sem rótulo,
  ao lado de um "ROI projetado/mês" que agora o tem. Não entrou porque a regra é sobre o
  termo que a §5 bane, e corrigir o texto sem guarda é conserto que regride em silêncio —
  o defeito que a [ADR 0034](0034-o-evento-nomeado-e-o-runbook-que-o-conhece.md) mediu. Ele sai
  junto do `kpi_ids` da `#105`, quando o Digital Employee deixar de carregar medição.
- **A regra é sobre o literal, não sobre adjacência**, e isso é limite e não descuido: um
  número de ROI renderizado sob um rótulo que não diga "ROI" não é alcançado. A ADR 0083
  estava certa nessa metade.
- **O qualificador só precisa estar no mesmo literal.** Uma frase longa que diga
  "projetado" sobre outra coisa e "ROI" sobre o apurado passaria. Não há ocorrência assim
  hoje, e o recorte por literal é o que mantém a regra decidível.
- **A §3 do Language Map promete um campo que não existe**, e isso vale registro porque
  bloqueia a #90: ela manda mostrar "Evidence marcada como revisada e **publicável**", e
  `Evidence` não tem campo de revisão nem de publicabilidade no Pulse; `Finding` tem
  `reviewed_by`/`reviewed_at`, mas só obrigatórios para `fact`. Um `hypothesis` — que é o
  default e o que a extração por IA produz (D6) — nasce sem revisor, de modo que
  publicá-lo violaria a regra 1 da mesma §3. São **duas perguntas diferentes** ("quão
  certos estamos" × "o cliente pode ver") e precisam de dois campos. Está levantado em
  `biahflow/pulse#106`; a decisão é de lá.
