# FDD 021 — Avisos por WhatsApp

**Feature ID:** `F-021`

**Registro histórico:** implementada em 07/08/2026 (ADR 0043). Recorte construível da
**RFC 002**. Esta FDD antecede a adoção prospectiva dos estados da Engineering OS.

> *Os seis critérios de aceite estão de pé e têm teste. O que a construção descobriu, e que
> nenhum documento previa, foi que **metade da fatia não era o canal**: o critério (4) exige
> que o link caia "na coisa exata, nunca na home", e não havia link nem URL que o suportasse.
> `Notification.link` existe desde a Fase 2, o sino o renderiza como `<a>` quando preenchido, e
> as dez ramificações do `diff` **nunca o preencheram** — a ADR 0033 outra vez, na direção que
> ninguém tinha olhado: lá um painel sobre campo sem escritor, aqui um **controle** sobre campo
> sem escritor. E a navegação por abas era estado de React, sem URL que a alcançasse, de modo
> que nem havia o que escrever. As duas coisas foram construídas antes do canal, e o sino ganhou
> links de carona.*

## Objetivo e não objetivos

**Objetivo.** Acrescentar o WhatsApp como **canal de aviso 1:1** ao lado do sino e do digest
por e-mail, com opt-in por pessoa, para que um aviso importante chegue com abertura alta e
**puxe o cliente ao portal**.

**Não é objetivo** criar grupo, sala ou qualquer superfície de conversa muitos-para-muitos.

**Não é objetivo** mover conteúdo para o canal. O aviso leva o fato e o link; o que importa
mora no portal.

**Não é objetivo** criar uma segunda régua de "o que merece aviso". O `diff` do sync já
decide isso, e um segundo decisor faria a resposta a "sobre o que o cliente é notificado"
deixar de caber num arquivo.

**Não é objetivo** usar IA. O texto é template — modelo redigindo mensagem que sai por canal
externo sem revisão é efeito colateral autônomo.

## Jornada e interface

Nas preferências, a pessoa vê o telefone e um consentimento explícito para receber avisos por
WhatsApp, ao lado da preferência de e-mail que já existe. Sem consentimento, nada é enviado —
e revogar tem efeito imediato, inclusive sobre o que já está na fila.

Quando algo muda no projeto e o `diff` produz uma notificação, quem optou pelo canal recebe
uma mensagem curta: o que aconteceu e um link. O link cai **na coisa exata** — a entrega a
aprovar, a pendência a responder — nunca na home. Todo login é um imposto que o WhatsApp não
cobra; perder no último metro é perder.

Internamente, `/admin` mostra o estado do canal (configurado, ligado, com falha) na mesma
página onde as demais integrações já se declaram.

## Dados, API e permissões

**Nenhum modelo novo de notificação.** Acrescentar um canal é acrescentar um tipo, um ramo no
`diff` com chave de deduplicação estável e uma entrada na audiência — o custo que a ADR 0012
estabeleceu. O registro do que foi enviado por qual canal pendura na notificação existente.

**Opt-in e telefone são colunas da pessoa**, ao lado de `notify_by_email`, e o papel de
aplicação recebe `UPDATE` **escopado por coluna** sobre elas e nada mais. É o que impede
"mudar minha preferência" de virar "reescrever o aviso" ou "promover-me a interno" — a mesma
razão que já governa `read_at`.

**Envio pelo worker**, na forma do digest: enfileirar é tolerante a broker morto, porque a
notificação já está gravada e aparece no sino de qualquer forma. Um envio perdido é atraso,
não silêncio.

**Adaptador de provedor**, atrás de flag, como os demais conectores — o fornecedor é peça
trocável e o produto não conhece o nome dele.

**Webhook de entrada** (recibo de entrega, ou resposta do cliente) na rota autenticada por
chave, assinado e idempotente, no precedente da ADR 0013. Resposta do cliente vira **evento
do projeto**, nunca thread no canal.

## Estados de erro e segurança

**Sem consentimento, não há envio** — por nenhum caminho, e isso é portão, não validação de
formulário. Revogação cancela o enfileirado.

**Falha do provedor não perde o aviso**: a notificação já existe no portal. A falha é
registrada com evento nomeado e runbook correspondente, e a integração pausa em vez de
insistir — o mesmo tratamento que o conector de Drive dá a uma falha no Google.

**Reentrega não duplica.** Idempotência na saída pela chave de deduplicação, e na entrada
pelo identificador do evento.

**O conteúdo é mínimo por segurança, não por estilo.** Nenhum trecho de documento — o canal
não tem as garantias que sustentam a citação no portal —, nenhum dado comercial, nenhum
identificador de outro tenant. Vai o fato e o link.

**Credencial nova entra no preflight**, com os dois portões independentes contra o segredo de
exemplo (ADR 0022) valendo para ela.

## Telemetria e critérios de aceite

Eventos com runbook, guarda bidirecional (ADR 0034): aviso enfileirado, entregue, recusado
por falta de consentimento, e falha do provedor. Nenhum carrega o texto da mensagem nem o
número — o telefone é campo de segredo para efeito de redação de log.

**Aceite.** (1) Pessoa sem consentimento não recebe mensagem, mesmo com o canal ligado e o
telefone preenchido. (2) Revogar o consentimento cancela um aviso já enfileirado. (3) Uma
mudança no projeto produz exatamente uma mensagem por destinatário optante, e a reentrega do
mesmo evento de sync não produz uma segunda. (4) O link abre a tela específica do assunto,
autenticado, sem passar pela home. (5) Com o provedor fora do ar, o aviso continua no sino e
a falha aparece no estado da integração. (6) A mensagem não contém trecho de documento nem
valor comercial.

## Testes e avaliações de IA

Testes de portão de consentimento, idempotência de entrada e saída, isolamento da audiência
(o aviso alcança exatamente quem a audiência define), e redação de log do telefone. Teste de
que o corpo da mensagem não contém conteúdo de documento — asserção sobre **o que é enviado**,
que é a única forma de provar que não sai.

**Sem avaliações de IA**, porque não há IA nesta fatia. Se um dia o texto do aviso passar a
ser redigido por modelo, ele entra sob o registro de prompt versionado e as avaliações
adversariais existentes — e ainda assim com revisão, porque a mensagem sai do domínio.

**Teto de frequência por pessoa**, compartilhado com os demais avisos e com a pesquisa da FDD
022. Um canal de abertura quase total é o mais fácil de queimar: cada contato entrega algo —
informação, valor, solução — ou não acontece.

*Entregue em 07/08/2026, **antes** desta FDD e em fatia própria (ADR 0042). O combinado era
sair junto da FDD 022, e não sobreviveu ao calendário: aquela FDD está bloqueada por uma
condição que não é código — o laço de ação do funil — e esta não tem bloqueio nenhum, de modo
que manter o acordo entregaria o canal **sem teto** ou o prenderia atrás de uma condição que
não é dele. `portal_api.contact_budget.claim()` é a porta: uma chamada que decide **e**
registra, porque separar em "posso?" e "gastei" criaria a fresta em que um remetente pergunta e
esquece o segundo passo. O envio desta FDD a consome antes de falar com o provedor, e o
`dedupe_key` que ele passa é o da própria notificação — é o que faz a retentativa sobre
`whatsapp_sent_at IS NULL` não gastar uma segunda unidade e transformar um provedor fora do ar
em silêncio permanente.*

**Teto de horário**, que esta FDD não pedia. *Acrescentado em 19/08/2026 (ADR 0055). As
ADRs 0042 e 0043 o deixaram nomeado e aberto com a mesma frase — "é decisão do remetente, não do
orçamento, e entra com o canal" —, e ele não entrou com o canal: o teto de frequência conta
contatos e não sabe que horas são, de modo que três mensagens por semana permitidas continuavam
sendo três mensagens às três da manhã. A janela é lida no fuso do produto (`America/Sao_Paulo`,
constante — a ADR 0026 decidiu que fuso não é configurável), atravessa a meia-noite, e início
igual ao fim a desliga. O aviso **não se perde**: ele não é carimbado, não gasta orçamento e sai
na varredura seguinte.*

***E a fatia mediu uma coisa que esta FDD não sabia, e que era metade do trabalho:** não havia
entrada de `beat_schedule` para a task de envio. Ela só rodava no fim de um sync do Biahflow, de
modo que **adiar não tinha quem voltasse buscar** — num projeto quieto, o "depois" não chegava. A
mesma lacuna já tornava otimista o que o `alerts.md` dizia sobre a queda do provedor ("a próxima
passagem do sync tenta de novo"). `send_due_whatsapp_notices` fecha as duas, de quinze em quinze
minutos, e com ela o critério (5) desta FDD — "com o provedor fora do ar, o aviso continua no sino
e a falha aparece no estado da integração" — passou a ter retentativa com prazo em vez de
retentativa condicionada a outra mudança acontecer.*

*Fica aberto: **feriado e fim de semana**, que são calendário e não horário, e o teto de horário
do **e-mail** do digest, deliberadamente fora — o argumento das duas ADRs é sobre o canal que
chega no bolso da pessoa.*

**Critério (4) na resolução do item.** *Emenda de 19/08/2026 (ADR 0056), e ela fecha uma
divergência que estava dentro deste documento.* O registro histórico acima afirma que "os seis
critérios de aceite estão de pé e têm teste", enquanto o critério (4) pede "a tela específica do
assunto" e a jornada desta FDD diz "na coisa exata, nunca na home" — e o `ROADMAP.md` listava o
link em granularidade de item como ponta aberta. As duas leituras não podiam valer ao mesmo tempo,
e nenhum documento dizia qual era a boa.

A partir desta data vale a leitura forte, e ela está entregue: **o critério (4) esteve de pé na
resolução da aba desde 07/08/2026, e na do item desde 19/08/2026.** O link carrega
`&item=<namespace>:<rótulo>`, a tela destaca a linha e rola até ela, e quando a linha não existe
mais a aba diz isso em vez de calar. A âncora é o **rótulo** e não o `id`, porque o sync do
Biahflow apaga e recria essas linhas — um link por uuid nasceria apontando para uma linha que vai
deixar de existir, e o link deste canal é assíncrono por desenho.

*Duas coisas que esta FDD não sabia e a construção mediu.* A primeira: a fixture do SSR trazia
`link: null` nas duas notificações, contradizendo em silêncio a garantia que a ADR 0043
estabeleceu — toda espécie de cliente tem link —, e o único controle que consome o campo era código
morto nos testes. A segunda: o e2e desta FDD provava que o aviso **existe**, não que ele leva a
algum lugar; o critério (4) só passou a ter prova ponta a ponta agora.

~~*Fica aberto: o **popover do sino** renderiza a linha como `<div>` e não como `<a>`, então o
caminho de menor atrito para quem já está no portal continua sem link — o percurso provado passa
por "Ver todas".*~~ **Fechado em 19/08/2026 (ADR 0057).** As duas superfícies internas passaram a
usar o mesmo componente, e "o que o `Notification.link` faz quando clicado" voltou a ter uma
resposta só no repositório. A linha é `<a href>` e o clique é interceptado **só quando pode** —
modificador, projeto diferente do que está na tela e aba fora do `navItems` caem no href de
verdade —, o que mantém a degradação monotônica. A Central perdeu o `target="_blank"` na mesma
fatia: abrir uma segunda aba para chegar a uma lista já aberta era resto de quando o link era só
uma URL a copiar.

*A causa de aquela linha ter sobrevivido a duas ADRs que a nomearam virou guarda, e é a mesma da
ADR 0026: todas as asserções sobre a âncora eram sobre **dado**, e um `<div className="popover-row">`
renderiza HTML indistinguível de um `<a>`. A guarda nova olha a **forma do controle** — toda
renderização de `notifications.items` passa por `NotificationLink` —, e nasceu vermelha nomeando as
duas listas.*
