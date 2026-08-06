# ADR 0031 — Da pendência de volta à pergunta que a abriu

**Status:** aceita — 06/08/2026
**Contexto:** Fase 2, fechando "vínculo a conversas". O FK já existia e era lido como booleano.

## Contexto

`ROADMAP.md` listava *"vínculo a conversas"* entre os itens pendentes da Fase 2. Ele não estava
pendente pela metade que importa: `conversation_message.pending_item_id` existe desde a ADR 0015 e
é **gravado** por `conversations.append_turn`. O que faltava era alguém ler.

E o único leitor o reduzia a um booleano — `"pending_created": message.pending_item_id is not None`
em `main.py`. Na tela, o cliente via "aberta pela IA" numa pendência intitulada *"Responder dúvida
do cliente: …"* e não tinha caminho de volta à pergunta que ele mesmo havia feito.

## O que a implementação descobriu, e que mudou o desenho

A primeira versão levava só o id do **turno**: o botão abria o chat e mandava rolar até ele.
No navegador, nada era destacado.

Medindo no banco: as cinco pendências abertas pela IA no projeto local vivem em **conversas
diferentes**, e nenhuma delas é a corrente. O chat carrega
`GET /me/conversations/latest` — o histórico é de uma thread só, decisão da ADR 0015 —, então o
turno apontado quase nunca estava na tela.

Um botão que abre o painel e não faz nada visível é a classe de defeito que as ADRs 0024 e 0026
existem para ter removido. Ele não podia ser entregue assim.

## Decisão

### 1. O payload leva a thread, não só o turno

`opened_by_message_id` **e** `opened_by_conversation_id`. Sem o segundo, o primeiro é um endereço
sem cidade.

### 2. Uma rota para abrir uma thread nomeada

`GET /api/v1/me/conversations/{conversation_id}`, irmã da `…/latest` e com o mesmo corpo. A
autorização não é escrita nela: `ConversationRepository.get_for_user` filtra por `user_id` e a
policy de `conversation` exige `user_id = portal.current_user_id()`. As duas barreiras, como
sempre — e o caso negativo está em `test_authorization.py`.

`/latest` continua declarada **antes** de `/{conversation_id}`, senão a rota literal seria
capturada pelo parâmetro.

### 3. Um pedido explícito sobrepõe duas guardas do cliente, e as duas por escolha

O carregamento do histórico tinha duas proteções que, mantidas, engoliriam o clique:

- **`historyLoaded.current`**, que impedia a busca de repetir. Existia para a *abertura do painel*
  não refazer o trabalho; um clique numa segunda pendência tem de trocar de thread.
- **"só substitui a tela se a pessoa ainda não escreveu nada"**, que protege uma pergunta enviada
  enquanto o histórico chegava. É a diferença entre **chegada** e **pedido**: o histórico da
  abertura chega e não deve atropelar o que a pessoa digitou; a thread que ela clicou foi pedida,
  e não trocar seria ignorar o clique.

### 4. Destaque, e não rota com hash

O turno em foco ganha `data-message-id` e um anel de foco. Um `#hash` na URL prometeria um link
compartilhável, e a conversa de outra pessoa devolve 404 por desenho — a promessa não se
sustentaria no primeiro compartilhamento.

## Consequências

- **O cliente relê a pergunta que gerou a pendência**, mesmo que ela esteja numa conversa de
  semanas atrás. `tests/e2e/pendencias.spec.ts` afirma que o turno destacado é **um** — o
  apontado, e não o último.
- **A guarda da ADR 0029 dirigiu a fatia.** Acrescentar o campo ao contrato fez o teste reprovar
  em duas frentes (fixture desatualizada e BFF não consumindo) antes de qualquer linha de tela.
  Foi o portão da fatia anterior cobrando a seguinte.
- **`scrollIntoView` num `requestAnimationFrame`**, porque o painel acabou de montar: sem esperar
  o layout, a rolagem roda sobre altura zero e não sai do lugar.
- **Nenhuma migração e nenhuma policy nova.** O público é o cliente e as linhas são dele: era o
  que tornava esta fatia pequena, e continuou verdade mesmo depois de crescer.
- **O limite que fica declarado:** o histórico ainda é de uma thread por vez, e abrir a apontada
  substitui a que estava na tela. Multi-thread na interface é outra decisão; o que esta fatia
  garante é que o clique nunca leva a lugar nenhum.

## Alternativas recusadas

**Dizer "essa pergunta está em outra conversa".** Honesto e barato, e foi a primeira opção
considerada. Entrega um caminho que quase sempre termina num aviso em vez de na pergunta — a
medição mostrou que *nenhuma* das cinco pendências estava na thread corrente.

**Tirar o campo do contrato e ficar só com "aberta pela IA".** Voltaria ao estado anterior, e a
guarda da ADR 0029 forçaria a remoção do campo — o que é a resposta certa quando não há
consumidor, e a errada quando há um consumidor óbvio esperando.

**Carregar todas as conversas do projeto ao abrir o chat.** Resolve por força bruta e paga em toda
abertura de painel por um caso que é minoria dos cliques.
