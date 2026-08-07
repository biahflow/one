# FDD 021 — Avisos por WhatsApp

**Status:** proposta — 07/08/2026. Nada aqui está implementado. Recorte construível da
**RFC 002**.

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
