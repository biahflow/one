# ADR 0057 — A âncora nas duas superfícies internas, e a que não morria

**Status:** aceito
**Data:** 19/08/2026
**Fase:** 7 — fecha as duas pontas que a ADR 0056 deixou nomeadas

## Contexto

Desde a ADR 0056 o link do aviso cai na **linha** e não só na aba: a URL carrega
`&item=<namespace>:<rótulo>`, a tela destaca a linha, rola até ela, e diz quando o rótulo não
existe mais. Aquela ADR fechou o critério de aceite (4) da FDD 021 — *"o link do aviso abre a tela
específica do assunto, na coisa exata, nunca na home"* — e deixou duas pontas escritas com todas as
letras, repetidas em `ROADMAP.md`, na FDD 021 e num comentário do próprio e2e:

> **O popover do sino não tem link.** `DashboardClient.tsx` renderiza a linha do popover como
> `<div>`; o `<a>` só existe na Central. […] **Âncora na busca.** `search.py` já devolve `tab`, e
> mandar junto o `item` é continuação natural e barata agora que o `data-item` existe.

As duas são a mesma frase dita de dois jeitos: **o link que vem de fora do portal cai na linha, e a
navegação de dentro do portal ainda cai na aba.** O cliente que recebe a mensagem no WhatsApp
chega melhor no assunto do que o cliente que já está com o portal aberto — o que inverte a ordem
de esforço que a FDD 021 usa para justificar o canal.

O popover é o caso que mais incomoda, e a razão é a mesma que fez a ADR 0026 existir: **ele foi
nomeado como ponta aberta duas vezes, na ADR 0043 e na ADR 0056, e sobreviveu às duas.** Um
`<div className="popover-row">` renderiza HTML byte a byte indistinguível de um `<a>` para quem só
compara strings, e o Playwright clica nele sem observar nada acontecer. Toda guarda deste
repositório sobre a âncora era sobre **dado** — o namespace publicado, a aba de destino, o rótulo
composto —, e nenhuma delas olhava a forma do controle. É o `inertButtons()` da ADR 0026 outra vez,
num controle que a guarda daquela ADR não alcança: `inertButtons` procura `<button>` sem `onClick`,
e aqui o defeito é uma linha que nunca chegou a ser um controle.

A revisão do recorte achou três defeitos vivos que não estavam nele. Todos verificados lendo o
código, e um deles entra na fatia.

### F3 — a âncora que não morre *(entra na fatia)*

O comentário do `goTo` declarava a intenção com precisão:

> *Trocar de aba **por vontade própria** encerra o destaque, como "Nova conversa" encerra o turno em
> foco: o cliente saiu do assunto que o aviso abriu, e um realce que sobrevive à navegação passa a
> apontar para uma pergunta antiga.*

Só que a **barra lateral** — que é *o* caminho de trocar de aba por vontade própria — chamava
`setActiveNav(label)` direto e não passava por `goTo`. Eram três escritores de `activeNav` (o estado
inicial, o `goTo` e a barra) e só dois apagavam a âncora. É defeito **da própria ADR 0056**, com a
promessa escrita no comentário da função que deveria cumpri-la.

A consequência não era teórica e não tinha teste nenhum cobrindo. `anchorMissing` é calculado
globalmente e renderizado **fora** do `switch (activeNav)`: quem chegasse com uma âncora obsoleta e
clicasse em "Documentos" na barra levava a frase *"O item deste aviso não está mais nesta lista."*
para todas as abas, indefinidamente, até recarregar a página. E o efeito de rolagem tem `activeNav`
nas dependências, de modo que **cada clique na barra re-destacava e re-rolava** para uma linha que o
cliente já tinha dispensado.

### F1 — o projeto que a busca e o sino ignoram *(não entra; a fatia se defende e o nomeia)*

`my_search` e `my_notifications` resolvem `access.default_project`, que devolve a membership **mais
recente**. Nenhuma das duas aceita `?project=`, e o BFF não o manda — enquanto o dashboard ao lado
vem de `/projects/{?project=}/dashboard`. Um cliente com dois projetos, vendo B por `?project=B`,
recebe os avisos e os resultados de busca de **A**.

Dois documentos afirmam o contrário por escrito: a FDD 018 diz *"**Busca entre projetos**: o topbar
é do projeto corrente"*, e o docstring de `my_notifications` diz *"Avisos do projeto **atual**"*. É
a família "dois documentos não podem estar certos ao mesmo tempo" que as últimas dez ADRs vêm
minerando, e é a mesma forma que produziu esta fatia e a anterior.

**Hoje o dano é mudo — só troca de aba. Com âncora ele deixa de ser mudo**, e é por isso que a
fatia precisa se defender dele em vez de ignorá-lo: interceptar o clique de um aviso de outro
projeto trocaria a aba mantendo na tela a lista do projeto errado, com uma linha destacada que não
é a do aviso. A defesa está na recusa (2) abaixo, e o item fica **nomeado** — corrigi-lo exige
parâmetro novo em duas rotas, que é mudança de contrato de outra superfície, ou emenda escrita nos
dois documentos. Deixá-lo sem nome repetiria exatamente o que fez o `<div>` do popover sobreviver a
uma fatia inteira.

### F2 — um campo chamado `item` nasceria verde na guarda de consumo

Este foi **medido, não deduzido**, e a medição está reproduzida abaixo porque ela é o motivo de o
campo ter o nome que tem.

A guarda de consumo do `tests/api-contract.test.mjs` (ADR 0033) pergunta, para cada esquema de
resposta, se o BFF **lê** cada campo que a API entrega, e a asserção é sobre a substring `.<chave>`
— porque desreferenciar é o único lugar onde esses nomes aparecem de verdade. O corpus de
`SearchHitOut` inclui `app/DashboardClient.tsx`, que contém `notifications.items`.

`".items"` contém `".item"`. Com o campo chamado `item`, a guarda passa **verde sem consumidor
nenhum**:

```
✔ o BFF consome todo campo que SearchHitOut entrega (0.059ms)
ℹ pass 68  ℹ fail 0
```

Renomeando **só o campo**, sem tocar em mais nada:

```
✖ o BFF consome todo campo que SearchHitOut entrega
  AssertionError: o BFF recebe estes campos de SearchHitOut e não os lê: item_anchor.
```

É literalmente o achado `date`→`dated_at` da ADR 0038, na mesma guarda e pelo mesmo mecanismo: lá o
campo `date` passava verde porque `new Date` e `due_date` contêm a substring, e renomear para
`dated_at` foi o que tornou o elo verificável. **O campo se chama `item_anchor`.**

## Decisão

**A âncora passa a valer para as duas superfícies internas, com o mesmo vocabulário, e só o `goTo`
troca de aba.**

### O vocabulário mudou de casa, e nenhum valor mudou

Os seis espaços de nomes nasceram em `notifications.py` na ADR 0056, quando os consumidores eram
dois: o mapa por espécie de aviso e o `data-item` do TSX. A busca virou o terceiro, e a essa altura
o vocabulário deixou de ser do aviso — `anchors.py` é folha pela razão de `tabs.py` e `textfold.py`
serem folhas, e pelo mesmo modo de falha, que é o único argumento que importa aqui: o mesmo literal
em lugares que têm de ser idênticos diverge **sem nada ficar vermelho**.

`anchors.ALL` não é a união calculada em tempo de execução, e a diferença é o que se prova: a união
é o que o código **faz**, a tupla é o que alguém **declarou**, e a guarda compara as duas com os
`data-item` do componente.

### A âncora da busca é derivada, e aqui isso é correto

A ADR 0056 decidiu o oposto para o aviso, e a decisão continua certa lá: o rótulo do aviso é do
**evento** — só quem comparou os dois estados sabe qual marco ficou pronto —, então ele vai em
`Change.item`, escrito em cada construção, e não há tabela possível.

Na busca há. `Hit.title` **é** o rótulo nas seis espécies, sem exceção, então a âncora sai de uma
propriedade `Hit.anchor` e não pode ser esquecida numa construção nova. O que fica na tabela é a
metade que não se deriva: o namespace por espécie, em `HIT_ANCHOR`.

**Explícito por espécie, e nunca derivado do `kind`.** Derivar do `kind` parece a saída óbvia e
produziria duas âncoras erradas de uma vez: `chunk` viraria um namespace que não existe em lado
nenhum, e `decision` ganharia um que a ADR 0056 recusou de propósito. A recusa fica registrada aqui
pelo mesmo motivo que a de publicar `id` ficou registrada lá — para não ser reproposta como se
fosse a saída óbvia que ninguém tinha visto.

`chunk` recebe o namespace `document`, e é a aplicação literal do *"a âncora é do objeto, não do
fato"* daquela ADR: o trecho é do documento, e a linha que a aba de Documentos desenha é a do
documento. É a mesma razão pela qual `transcript_ready` e `meeting_scheduled` compartilham
`meeting:`.

**Sem teto de tamanho, ao contrário do `deep_link`.** O `_MAX_LINK` é orçamento da *mensagem do
canal*; aqui o valor viaja em JSON para uma tela que já recebeu o título inteiro. Não há queda a
registrar, e portanto **nenhum evento de log novo e nenhuma linha em `docs/runbooks/alerts.md`** —
o que é afirmação desta ADR, e não omissão dela: a guarda de eventos é bidirecional desde a ADR
0034, e uma linha de runbook sem emissor reprovaria.

### Quem não ancora tem frase assinada, e é uma espécie só

`ANCHORLESS_HITS` traz `decision` com o motivo escrito, na forma do `ANCHORLESS` do aviso, do
`NOT_AN_ALERT` de `test_telemetry.py` e do `NOT_CONSUMED` da guarda de consumo. A aba de Decisões
**não** desenha `data-item`, e isso é decisão da ADR 0056 — publicar um namespace que só existe de
um lado é construir o atributo antes do escritor, o defeito da ADR 0033 escrito ao contrário. O
clique continua levando à aba, que é a resolução que a ADR 0024 estabeleceu e que continua correta
para uma decisão: ela é lida inteira ali, não é uma linha de lista que se procura.

Vazio é *"não há o que ancorar"*, nunca *"ancore por sua conta"* — a mesma convenção do
`document_id` ao lado, e é por isso que o campo é `str` e não `str | None`.

### O elemento é `<a href>`, e a interceptação é o caso feliz

Esta é a parte da decisão que **não** é óbvia, e ela é sobre F1.

O caminho fácil seria um `onClick` chamando `goTo(tab, item)`. Ele está errado: o `link` que
`deep_link` compõe carrega `?project=<uuid>`, e um `goTo` puro o **descartaria em silêncio** — a
tela trocaria de aba mantendo o projeto que já estava carregado. Enquanto F1 existir, isso pode
significar destacar a linha errada da lista errada.

Então a linha é um `<a href={item.link}>`, e o `onClick` intercepta **só quando pode**, recusando em
três casos e caindo no href de verdade:

1. **modificador ou botão do meio** — abrir em aba nova é do navegador, e interceptar isso quebraria
   a única coisa que uma âncora promete;
2. **o `project` do link não é o projeto na tela** — o href faz carga completa e honra o
   `?project=`. É a defesa contra F1, e não é opcional;
3. **a aba não está no `navItems`** — `onboarding_stuck` traz `/admin/funil`, que é outra rota e não
   uma aba deste componente.

**A degradação é monotônica**, e é exatamente o critério que sustentou o drop do `_MAX_LINK` na ADR
0056: recusar a interceptação devolve o comportamento anterior a esta fatia, nunca um clique morto.

Um componente só para as duas superfícies, porque *"o que o `Notification.link` faz quando
clicado"* precisa ter **uma** resposta neste repositório — é o argumento de `notifications.py`,
`conversations.py` e `search.py`, aplicado a um controle. Até aqui tinha duas respostas: a Central
abria uma aba nova, e o popover não fazia nada.

**A Central perdeu o `target="_blank"`, e isso é a fatia e não um efeito colateral.** Abrir uma
segunda aba para chegar a uma lista que já está aberta era o resto de quando o link era só uma URL
a copiar. Quem quiser a aba nova continua tendo: o `<a href>` está inteiro, e a recusa (1) existe
para isso.

### A busca só ancora no que a tela desenha

`openSearchHit` passa a âncora adiante apenas se `screenAnchors(view)` a contém. Reusa a função que
a ADR 0056 extraiu exatamente para responder *"a tela desenha esta linha?"*, e o efeito colateral é
o que a mantém honesta: a nota diz *"O item deste **aviso**…"*, e com esta guarda ela só continua
alcançável por âncora vinda de um aviso. Sem ela, um resultado de busca cujo dado saiu do projeto
entre a consulta e o clique produziria a frase errada.

`screenAnchors` passou a ser memoizado por ter ganhado o segundo leitor, e foi **declarado acima de
quem o lê** — o `openSearchHit` é uma declaração de função, que sobe, mas o `const` não, e o
compilador do React recusa preservar uma memoização usada antes de ser criada. O lint reprovou, e a
resposta certa era mover a declaração: o que ele descreve é uma ordem que só funciona porque
ninguém chama a função durante o render.

### E só o `goTo` troca de aba (F3)

A barra lateral passa a chamar `goTo(label)`, e o comentário de `goTo` deixa de ser uma promessa não
cumprida. A guarda que fixa isso é sobre o **escritor** e não sobre a barra: um quarto escritor
amanhã tem o mesmo defeito, e uma guarda que olhasse só a barra nasceria cega para ele.

## As guardas, e o fato de terem nascido vermelhas

A ADR 0056 insiste que uma guarda que nasce verde não mede nada, e a ADR 0038 mostrou o mesmo com a
sentinela do digest, que não mudou ao acrescentar data à linha da evidência porque a amostra não
percorria o ramo novo. **Cada guarda desta fatia foi vista falhando, e a mutação que a prova está
registrada.**

As duas guardas do lado node nasceram vermelhas **sobre o defeito real**, nomeando as três linhas:

```
✖ toda lista de avisos rende a linha como link, e não como um <div>
  + [ 'linha 899', 'linha 2009' ]        ← o popover e a Central
✖ só o goTo troca de aba, e é ele quem apaga a âncora
  + [ 'linha 848' ]                      ← a barra lateral (F3)
```

A do parâmetro de URL também, e por ausência do leitor:

```
✖ test_the_query_parameters_the_link_writes_are_the_ones_the_screen_reads
  AssertionError: o `deep_link` escreve ['item', 'project', 'tab'] na URL e o outro
  lado não os lê pelo mesmo nome.
```

As do lado Python foram provadas por mutação, uma a uma:

| Guarda | Mutação | Resultado |
|---|---|---|
| todo `Hit` tem namespace ou isenção | tirar `"pending"` do `HIT_ANCHOR` | vermelha aqui, e **verde** na de espaços de nomes |
| a isenção não guarda linha morta nem se sobrepõe | pôr `"milestone"` na isenção / isentar espécie inexistente | vermelha nas duas direções |
| espaços de nomes = `data-item` = `anchors.ALL` | `HIT_ANCHOR["milestone"] = "marco"` | vermelha — e a **versão antiga passa verde** |
| a âncora cai na aba que o clique abre | `HIT_ANCHOR["meeting"] = ANCHOR_PENDING` | vermelha **só aqui** |
| os nomes de parâmetro são os mesmos dos dois lados | `&item=` → `&row=` só no Python | vermelha — hoje só o e2e pegaria |

**Três dessas medições merecem o parágrafo que a tabela não comporta.**

A primeira é o **buraco da igualdade**, e é o motivo de ela ter virado união e não subconjunto. Com
a versão anterior da guarda — que olhava só o `ITEM_ANCHOR` —, a mutação `HIT_ANCHOR["milestone"] =
"marco"` passa **verde**, medido:

```
published == ['deliverable', 'document', 'meeting', 'milestone', 'pending', 'phase']
rendered  == ['deliverable', 'document', 'meeting', 'milestone', 'pending', 'phase']
VERDE
```

O conjunto do aviso continua idêntico ao do TSX, e a busca publica em silêncio um namespace que a
tela não desenha. Aceitar subconjunto — *"a busca só pode usar o que o aviso já usa"* — seria a
frouxidão que a ADR 0035 mediu ao dar `POST /chat` como coberto por um 404 que era de outra rota.

A segunda é o **método `transcript_ready`** repetido: tirando `"pending"` do `HIT_ANCHOR`, a guarda
de espaços de nomes fica verde porque `pending` continua publicado pelas três espécies de pendência
do aviso. A espécie foi escolhida pelo mesmo critério de lá — a que compartilha o namespace com
outra —, e é a razão de a cobertura de um portão ser a dos ramos que a amostra percorre.

A terceira é o **elo entre a espécie e a aba**, e é o que a existência do atributo não basta para
provar. `HIT_ANCHOR["meeting"] = ANCHOR_PENDING` passa por todas as outras guardas: os conjuntos
não mudam, a espécie continua mapeada, a isenção não é tocada. Só a guarda de aba diz o que
importa, e ela diz nomeando:

```
busca meeting: `pending:` abriria a aba 'Reuniões' (MeetingsView),
e o `data-item` está em ['PendingItem']
```

## Consequências

**O que fica aberto, e nomeado.**

- **F1 — o sino e a busca não são do projeto na tela.** Está descrito acima com os arquivos e o
  mecanismo. A fatia se defende dele (recusa 2 da interceptação, e `screenAnchors` filtrando a
  âncora da busca) e não o corrige.
- **`FilterChip` fora de "todos"** na aba de destino: a linha existe nos dados e não no DOM, então
  não há realce e não há nota. Limite declarado, na mesma forma como a ADR 0056 declarou o do
  primeiro render — lá foi verificado que os quatro filtros nascem em "todos", o que é verdade na
  chegada e deixa de ser depois de um clique.
- **A URL não muda na navegação in-app**, e é deliberado: a barra lateral também não a muda desde a
  Fase 2, e o `useState(initialTab)` ignoraria props novas — a URL viraria enfeite. O caminho
  compartilhável continua sendo o `<a href>`, intacto.
- **Homônimos**: o primeiro casamento vence, como a ADR 0056 registrou. A recusa (2) impede que isso
  vire homônimo **entre projetos**, que seria pior.

**O que esta fatia mediu e não deduziu**, além de F2 e do buraco da igualdade: o defeito F3 não
tinha teste nenhum, em nenhum nível, e não teria como ter — as asserções de HTML renderizado veem o
resultado de um render, e o defeito só aparece no **segundo**, depois de um clique. A guarda que o
fixa é sobre a forma do código pela mesma razão que o `inertButtons()` da ADR 0026 é: é a única
forma de vê-lo.

**E o que esta fatia não é.** O portal do cliente está fora do ar desde 13/08/2026 (ADR 0053). Isto
fecha pontas de código com portão verde; nada aqui foi observado servindo cliente.
