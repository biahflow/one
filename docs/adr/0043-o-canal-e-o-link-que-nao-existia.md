# ADR 0043 — O canal, e o link que não existia

**Status:** aceito
**Data:** 07/08/2026
**Fase:** 7 — recorte construível da RFC 002, implementa a FDD 021

## Contexto

A FDD 021 pede um canal de aviso 1:1 por WhatsApp ao lado do sino e do digest, com
opt-in revogável, no ponto de extensão que a ADR 0012 já descreve. Seis critérios de
aceite, e o quarto é:

> O link abre a tela específica do assunto, autenticado, sem passar pela home.

Ao construir, esse critério não tinha como ser cumprido — por **duas** razões
independentes, e as duas eram invisíveis:

1. **`Notification.link` nunca teve escritor para aviso de cliente.** A coluna existe
   desde a Fase 2. As dez construções de `Change(...)` em `diff` não a preenchem; o
   único escritor é `onboarding.raise_alert` (ADR 0040), cuja audiência é
   `_INTERNAL_ONLY`. E o sino **consome** o campo: `DashboardClient.tsx` renderiza um
   `<a>` quando ele vem preenchido e texto puro quando não vem, de modo que o ramo do
   link é código morto desde que foi escrito.

   É a ADR 0033 outra vez, na direção que ninguém tinha olhado. Lá, um painel sobre um
   campo sem escritor. Aqui, um **controle** sobre um campo sem escritor — e a guarda
   de consumo daquela ADR não o pega, porque ela pergunta se o contrato tem
   consumidor, e este tem: o sino o lê. O que faltava era produtor.

2. **Nenhuma URL alcançava uma aba.** A navegação do portal é estado de React
   (`goTo` = `setActiveNav`); o único parâmetro de URL é `?project=`. É por isso que a
   busca "cai na aba" sem navegar — ela é da mesma página. De modo que, mesmo com
   escritor, não havia o que escrever.

Ou seja: a fatia do canal não era "acrescentar um ramo de entrega". Metade dela era
dar destino ao que já se prometia entregar.

## Decisão

### O link ganha escritor, e ele mora no `fan_out`

Um mapa `LINK_TAB` por espécie de aviso, e `deep_link(project_id, kind)` produzindo
`/?project=<id>&tab=<rótulo>`. Mora em `notifications.py` e **não** no `diff`, por
dois motivos: o `diff` compara dois estados e não conhece o projeto, que é metade da
URL; e um mapa por espécie responde "que tela este aviso abre?" numa tabela legível,
em vez de espalhar a resposta por dez construções onde ela divergiria uma a uma. Quem
passa `link` explícito continua vencendo — é o alerta do funil, que aponta para
`/admin/funil` e não é aba de cliente.

De carona, o sino passa a ter links, que é ganho visível ao cliente e não depende do
canal.

### O rótulo da aba vira identificador, então vira módulo

`portal_api/tabs.py`, folha pela razão do `textfold.py` e com o mesmo modo de falha: o
mesmo literal aparece na busca, no link do aviso e no `navItems` do front-end, e uma
divergência entre eles **não deixa nada vermelho** — o `useState` cai na visão geral e
o cliente que clicou na mensagem chega no lugar errado. `test_tabs.py` lê o TSX e
compara, incluindo a ordem.

**Rótulo e não slug**, apesar do `tab=Reuni%C3%B5es` feio na URL. A decisão é da
ADR 0024 e está escrita lá: a tela navega por rótulo desde a Fase 2, e mandar o rótulo
pronto evita um segundo mapa do lado do navegador que envelheceria sozinho. Um slug
criaria exatamente esse segundo vocabulário.

### A mensagem não tem campo livre

`send_notice` recebe **um título e uma URL** e monta o corpo sozinho: template com dois
parâmetros posicionais, e nada mais. O `detail` da notificação — o campo de texto livre
do modelo, por onde trecho de documento e valor comercial viajariam — **não entra**.

A garantia é estrutural e não de disciplina: não existe parâmetro por onde conteúdo
pudesse passar. O teste afirma sobre o corpo enviado, semeando um `detail` com cláusula
e valor de propósito, que é a única forma de provar que algo não sai.

### O consentimento é conferido no envio

Não no formulário. É o que faz a revogação alcançar o que já está na fila sem varrer
fila nenhuma — critério (2) — e o carimbo sai mesmo sem envio, na decisão que o digest
já tinha tomado: quem religa a preferência amanhã não recebe semanas de avisos de uma
vez.

Nasce **desligado**, ao contrário do `notify_by_email`, e a assimetria é o ponto: quem
foi convidado para acompanhar um projeto quer saber quando ele anda, mas um canal que
chega no bolso da pessoa exige que ela diga sim. Um `server_default 'true'` faria toda
conta existente virar destinatária no deploy.

E ligar o canal **sem número é recusado** com 422, em vez de aceito e silenciosamente
inútil — um controle ligado sobre coisa nenhuma é o que a ADR 0033 ensinou a não fazer.

### Duas colunas de carimbo, não uma

`whatsapp_sent_at` ao lado de `emailed_at`. São duas entregas do mesmo aviso e uma pode
falhar sem a outra: num carimbo só, o SMTP fora do ar cancelaria o WhatsApp — o oposto
do que a FDD se propõe, que é o aviso sobreviver à queda de qualquer canal porque já
está no sino. Cada canal retenta sobre o próprio nulo.

### A resposta do cliente vira aviso do time, nunca thread no canal

`NotificationKind.whatsapp_reply`, audiência `_INTERNAL_ONLY`, link para as pendências
— onde o time responde **dentro do portal**. É o que impede o WhatsApp de virar o lugar
onde o projeto acontece: *spoke*, e um spoke que começa a hospedar conversa vira hub sem
ninguém decidir.

Sem tabela de entrada: a idempotência é o `dedupe_key` carregando o id do evento do
fornecedor, a mesma memória que a ADR 0040 reusou pelo mesmo argumento — uma tabela
custaria policy, purga e uma quarta exclusão à mão no apagamento, para guardar um
identificador que outra coluna já guarda.

## Consequências

**O teto de frequência é consumido aqui, e a chave de dedupe é o que o torna seguro.**
A reserva (ADR 0042) é pela chave do aviso, não pela pessoa, então a retentativa depois
de uma queda do fornecedor **reusa** a unidade em vez de debitar outra. Sem isso, uma
indisponibilidade de minutos viraria silêncio permanente naquele canal: o laço acharia
o orçamento gasto por ele mesmo, e ninguém veria — o aviso continua no sino, e o que
faltou não deixa rastro. Está em regressão.

**`phone_hint` entrou na allowlist de segredo, e foi a guarda de contrato que cobrou.**
`phone` virou dica de segredo em `telemetry.py` — o primeiro elemento daquela lista que
não é credencial, e sim dado pessoal, como a própria FDD manda. A guarda do OpenAPI
reusa a lista e reprovou o campo de resposta. A resposta certa era a allowlist e não
renomear: é o `key_prefix` outra vez — a parte pública de algo cujo nome inteiro é
segredo —, e renomear passaria pela guarda sem mudar o dado, que é a definição de
derrotá-la.

**A ausência de link agora cala o canal, e isso é nomeado.** Sem entrada no `LINK_TAB`
não há "coisa exata" a abrir, então o aviso fica só no sino e sai
`whatsapp.skipped_without_link`. `test_tabs.py` reprova antes disso acontecer: toda
espécie que chega ao cliente tem de saber que tela abre.

**Fica aberto, e nomeado:** teto de **horário** (não mandar às 3 da manhã), que a
ADR 0042 já tinha deixado em aberto e continua sendo do remetente, não do orçamento; e
o link em **granularidade de item** — hoje ele cai na aba, que é a mesma resolução que
a busca estabeleceu como a resposta do produto, e não na pendência específica.
