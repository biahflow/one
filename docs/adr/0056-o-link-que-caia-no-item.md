# ADR 0056 — O link que cai no item, e a guarda entre os dois deployables

**Status:** aceito
**Data:** 19/08/2026
**Fase:** 7 — fecha a última ponta que a ADR 0043 deixou nomeada

## Contexto

O critério de aceite (4) da FDD 021 pede uma coisa só, e em duas palavras:

> O link do aviso abre **a tela específica do assunto** — na coisa exata, nunca na home.

A ADR 0043 entregou a primeira metade e disse a segunda: o aviso passou a cair na **aba** certa,
que é a mesma resolução que a busca estabeleceu na ADR 0024, e "o link em granularidade de item"
ficou escrito como ponta aberta na própria ADR, no `ROADMAP.md` e na linha de entrega do canal.

Só que a FDD abre afirmando que "os seis critérios de aceite estão de pé e têm teste". Os dois
documentos não podiam estar certos ao mesmo tempo: o critério estava de pé **na resolução da aba**,
e ninguém tinha escrito qual das duas leituras valia. Uma promessa que dois documentos do
repositório contam de formas diferentes é a forma que as sete fatias anteriores da Fase 5
aprenderam a reconhecer.

E a diferença entre as duas leituras não é cosmética. Um aviso de "Marco concluído" cai numa aba
com todos os marcos do projeto; num projeto de porte real, "a coisa exata" e "a lista onde a coisa
exata está" são telas diferentes, e a segunda devolve ao cliente o trabalho de procurar — que é
exatamente o atrito que faz o canal de menor esforço vencer.

## Decisão

**A âncora viaja dentro do `link` que já existe, e é o rótulo da linha com espaço de nomes.**

```
/?project=<uuid>&tab=Cronograma&item=milestone%3AValida%C3%A7%C3%A3o%20de%20integra%C3%A7%C3%B5es
```

### Por que rótulo e não `id` — medido, não deduzido

A alternativa óbvia era publicar `id` nos seis esquemas de lista e ancorar por uuid. Ela foi
medida e recusada por duas razões independentes.

A primeira é que o dado não existe: em `schemas.py`, só `PendingOut` tem `id`. `MilestoneOut`,
`DashboardDocumentOut`, `MeetingOut`, `DecisionOut`, `PhaseOut` e `DeliverableOut` não têm nenhum.

A segunda é que **nem o que existe serviria**. `integrations/biahflow.py` apaga e recria essas
linhas a cada sync — inclusive as `PendingItem` de origem `biahflow` —, então o uuid de hoje não é
o de amanhã. O link do canal é assíncrono por desenho: entre a emissão da mensagem e o clique do
cliente há sync. Um link por uuid **nasceria apontando para uma linha que vai deixar de existir**,
e falharia justamente no caso que o produto mais quer — o cliente que volta dias depois.

O repositório já tinha decidido isso duas vezes, e as duas estão escritas: a busca manda o rótulo
pronto porque "um segundo mapa do lado do navegador envelheceria sozinho" (ADR 0024), e a aba
virou identificador em `tabs.py` pelo mesmo argumento (ADR 0043). `DecisionOut` chega a carregar a
frase no comentário: *"`meeting_title` é rótulo e não id, porque o uuid da reunião muda a cada
sync"*. Esta é a terceira vez, e não se cria vocabulário novo — publica-se na URL o que a tela **já
usa como identidade**: as chaves React dessas listas são exatamente `item.title`, `doc.title`,
`meeting.title`, `item.name` e `deliverable.name`.

O espaço de nomes resolve a única ambiguidade real: a "Visão geral" hospeda **duas** listas, as
fases e os entregáveis. Ele é inglês porque é identificador de código; o rótulo é o texto PT-BR do
cliente. O separador é `:` e **não há esquema de escape**, de propósito: rótulos contêm dois-pontos
("Fase 2: descoberta"), e um esquema de escape seria o segundo vocabulário que a ADR 0024 recusou.
Na prática o consumidor **compara a string inteira** e nunca divide.

Títulos homônimos: **o primeiro casamento vence**. É degradação benigna e está escrita no código —
o cliente cai numa linha com o nome exato que a mensagem citou, e o `detail` da notificação já é
esse mesmo título, de modo que mensagem e tela concordam. Trocar isso por uuid resolveria a
colisão e introduziria o link morto; é o negócio errado.

### `Change.item` × `deep_link`: cada pergunta cai de um lado

O docstring do `LINK_TAB` já dividia o argumento, e cada metade caiu onde ele mandava.

*"Que tela este aviso abre?"* é pergunta **por espécie**, cabe numa tabela legível, e continua em
`LINK_TAB`. *"Qual linha daquela tela?"* é pergunta **por evento** — só quem comparou os dois
estados sabe qual marco ficou pronto —, e não há tabela possível: o marco é o `title` daquela
iteração, o entregável é o `name` daquele par. Vai em `Change.item`, e **só o rótulo cru**.

Quem junta os dois é `deep_link`, que continua sendo o único lugar que compõe a URL — é quem
conhece o projeto, o encoding e o orçamento de tamanho. O efeito é que o espaço de nomes é escrito
uma vez por espécie (`ITEM_ANCHOR`) e não uma vez por construção; as construções de `Change` são
quatro origens diferentes em três módulos.

### Quem não ganha âncora ganha uma frase assinada

`ANCHORLESS` lista as três espécies que legitimamente não apontam para uma linha, cada uma com o
motivo escrito, na forma do `NOT_AN_ALERT` de `test_telemetry.py` e do `NOT_CONSUMED` de
`api-contract.test.mjs`.

`project_status_changed` é a única de cliente: o assunto é o projeto inteiro, a "coisa exata" da
FDD 021 **é** a Visão geral, e inventar uma linha para satisfazer uma tabela seria o defeito.
`whatsapp_reply` e `onboarding_stuck` são internas — a primeira aponta para Pendências porque é
**onde o time responde**, não porque a resposta seja uma pendência; a segunda traz `link` próprio
para `/admin/funil` e nunca passa por `deep_link`.

### Dropar em vez de truncar, e o número que esta fatia **não** mediu

`Milestone.title`, `Document.title`, `Meeting.title` e `PendingItem.title` são `String(200)`.
Duzentos caracteres acentuados, percent-encoded, passam de mil — mais longos que a mensagem que os
carrega. `deep_link` compõe, mede contra `_MAX_LINK` e devolve o link **sem âncora** se estourar.
Nunca trunca: âncora truncada não casa com nada, com a agravante de *parecer* que casou.

**Honestidade sobre a origem do número: nenhum limite de caracteres do fornecedor do canal está
documentado neste repositório, e esta fatia não o mediu.** `_MAX_LINK` é teto de sanidade, não
especificação de fornecedor, e citar um número de provedor sem conferir seria inventar precisão —
que é o oposto do que `results.py` faz com dado sem base. O argumento que sustenta a escolha é
outro, e esse é verificável: **a queda é monotônica** — sem âncora, o link é exatamente o de antes
desta fatia —, então errar o teto para baixo custa um destaque e nunca um link quebrado. O valor é
512 caracteres de URL relativa, e a queda emite `notification.anchor_dropped` com a **espécie** e
nunca o rótulo, que é texto do cliente.

### A jornada tem dois níveis, e é onde o link seria correto e inalcançável

`JourneyPanel` só renderiza os entregáveis da fase **selecionada**, e o padrão é a fase ativa. Um
`deliverable_delivered` de fase já concluída produziria uma âncora **fora do DOM** — link
tecnicamente correto e inalcançável, que é o pior desfecho possível, pior que não ter link, porque
parece que tem.

A fase passa a ser **derivada da âncora** no cálculo do `initial`. Isso é também o que dispensa uma
âncora composta `fase/entregável`, e com ela o problema de escapar o separador. O preço está
escrito no código: entregáveis homônimos em fases diferentes se resolvem pela primeira fase que os
contiver.

### O seletor não interpola, e é o ponto de segurança da fatia

O efeito que rola até a linha **não** monta o seletor com o valor. O efeito irmão, o do turno em
foco (ADR 0031), faz `querySelector(`[data-message-id="${…}"]`)` e *pode*, porque ali o valor é um
uuid vindo da API. Aqui ele vem da **barra de endereço** e é um título que alguém digitou no
Biahflow: uma aspa no meio dele fecha o seletor cedo e, na melhor das hipóteses, seleciona outra
coisa. A varredura percorre `querySelectorAll("[data-item]")` e compara `getAttribute` em
JavaScript, onde aspa é um caractere e não sintaxe.

O destaque, por sua vez, é **JSX e não `classList` no efeito** — a forma que o `message--focused`
já usa —, que é o que o faz existir no HTML do SSR: sem isso haveria um piscar entre a primeira
pintura e a hidratação, e a guarda node não teria o que ver.

### E a tela diz quando não achou

Se a âncora não corresponde a nada, a aba renderiza uma nota discreta: *"O item deste aviso não
está mais nesta lista."* Sem ela a degradação seria invisível, que é o defeito que a ADR 0033
nomeou — "cliquei no aviso do marco X e o marco X não está aqui" é a pergunta que o suporte
receberia, sem nada vermelho em lugar nenhum.

**Desvio consciente do recorte planejado, e ele é sobre o servidor.** A nota era para sair da
varredura do DOM. Não pode: um `querySelectorAll` só existe depois da hidratação, e a asserção que
prova a nota é sobre **HTML renderizado**. Ela é derivada no render, de `screenAnchors(overview)`
— a mesma lista de dados que produz os `data-item`. As duas respostas coincidem porque os quatro
`FilterChips` das abas ancoráveis nascem todos em "todos" e o painel "Resolvidas" não tem filtro,
o que foi verificado e não suposto; a linha ancorada está no primeiro render em todos os casos.

## Consequências

**As guardas, e o fato de terem nascido vermelhas.** `test_item_anchor.py` tem oito asserções, e
as duas que ligam os dois deployables foram escritas **antes** do TSX e vistas falhando: a de
espaços de nomes acusou os seis "só no Python", e a de aba acusou as nove espécies nomeando o
componente certo de cada uma (`OverviewView`, `ScheduleView`, `DocumentsView`, `MeetingsView`,
`PendingView`). É o achado central da ADR 0033 aplicado antes do fato, e não depois: uma guarda que
nasce verde não mede nada — a ADR 0038 mostrou o mesmo com a sentinela do digest, que não mudou ao
acrescentar data à linha da evidência porque a amostra não percorria o ramo novo.

As duas ligações são deliberadamente diferentes. A de espaços de nomes é igualdade nos **dois**
sentidos: namespace só no Python é âncora que nunca casa; namespace só no TSX é atributo construído
antes do escritor, que é o defeito da ADR 0033 escrito ao contrário — e é por isso que Resultados e
Decisões continuam sem `data-item`. A de aba não se contenta com a existência do atributo: ela
recorta o TSX em funções, lê o `switch (activeNav)` e cobra que o `data-item` esteja **no
componente que aquela aba abre**, porque o elo frouxo já foi medido dando `POST /chat` como coberto
por um 404 de outra rota (ADR 0035). O limite está declarado no docstring, como o corpus do
`api-contract.test.mjs` declara o dele: a expansão de componente filho é de **um nível**, o
bastante para o `JourneyPanel`.

A varredura de `Change` é por AST e não por fixture, e é o que faz ela alcançar as **quatro**
origens — o `diff` do sync, as duas tasks do worker e a rota de resposta do canal. Uma guarda
dirigida por fixture veria a primeira; foi exatamente esse ponto cego que deixou dez ramificações
sem `link` até a ADR 0043.

**A sétima asserção veio da revisão, e ela nasceu do buraco que as seis deixavam.** As seis
primeiras cobriam o `item=` ausente, a isenção morta, o namespace divergente e a aba errada — e
deixavam passar o caso do meio: **uma espécie que passa `item=` e não tem linha no `ITEM_ANCHOR`**.
Ali o `deep_link` descarta o rótulo que recebeu, o link volta para a aba, e o autor *escreveu* a
âncora achando que a tinha entregado.

Foi medido em vez de argumentado, tirando `transcript_ready` do `ITEM_ANCHOR` — a espécie escolhida
de propósito, porque ela **compartilha** o espaço de nomes `meeting:` com a `meeting_scheduled`. As
seis asserções ficaram **todas verdes**: a primeira aceita a construção porque ela tem `item=`; a de
espaços de nomes compara conjuntos, e `meeting` continua publicado pela irmã; a de aba só percorre o
que está no `ITEM_ANCHOR`, e o que saiu dele não é percorrido. Com a asserção nova, a mesma mutação
reprova nomeando a espécie. É o achado da ADR 0034 na mesma forma — lá o evento sem limiar era irmão
exato de um que já tinha — e a razão de a cobertura de um portão ser a dos ramos que a amostra
percorre, e não a das linhas que ele lê. A oitava, de quebra, proíbe uma espécie de estar nas duas
tabelas: estando, a isenção passaria a cobrir justamente quem não precisava dela.

**O que a fatia mediu e não deduziu:**

- **A fixture do SSR mentia sem que nada pegasse.** `tests/fixtures/dashboard.mjs` trazia
  `link: null` nas duas notificações — o que contradiz a garantia que a ADR 0043 estabeleceu (toda
  espécie de cliente tem link) e ninguém pegava, porque o esquema declara `string | null`. O ramo
  `<a>` da Central era **código morto nos testes**: a mesma classe de defeito que a ADR 0043
  encontrou no próprio campo, um nível acima.
- **A Central não é alcançável por URL.** `"Notificações"` não está no `navItems`, então `?tab=` não
  a abre e o HTML do SSR não tem como carregar aquele `href`. Quem prova o `<a>` ponta a ponta é o
  e2e; o teste node prova o elo anterior, que também não tinha asserção nenhuma — o link com âncora
  atravessando `toNotifications` até as props do componente.
- **O e2e provava que o aviso existe, não que ele leva a algum lugar.** O caso novo é o critério (4)
  provado ponta a ponta pela primeira vez: clica no aviso do documento sincronizado no
  `beforeEach`, captura a aba que abre e afirma a URL **e** o destaque na linha daquele documento.

**Fica aberto, e nomeado:**

- **O popover do sino não tem link.** `DashboardClient.tsx` renderiza a linha do popover como
  `<div>`; o `<a>` só existe na Central. É achado real desta varredura e vale fatia — o popover é o
  caminho de menor atrito para quem já está no portal —, mas é mudança de comportamento de outra
  superfície e não entrou aqui. O e2e passa por "Ver todas".
- **Âncora na busca.** `search.py` já devolve `tab`, e mandar junto o `item` é continuação natural e
  barata agora que o `data-item` existe. Não entrou porque é seleção humana, não porque seja
  difícil.
- **Publicar `id` nos seis esquemas** foi medido e recusado acima; fica registrado para não ser
  reproposto como se fosse a saída óbvia.
- **Slug ou `textfold` na âncora** seria um terceiro vocabulário entre três deployables, que é
  exatamente o que `tabs.py` existe para impedir.

**E o que esta fatia não é.** O portal do cliente está fora do ar desde 13/08/2026 (ADR 0053). Isto
fecha uma ponta de código com portão verde; nada aqui foi observado servindo cliente, e a primeira
ocorrência real de `notification.anchor_dropped` — como o primeiro número do teto de frequência —
só existe quando houver portal de pé.
