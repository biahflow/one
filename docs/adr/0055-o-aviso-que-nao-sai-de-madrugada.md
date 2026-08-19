# ADR 0055 — O aviso que não sai de madrugada, e quem volta buscá-lo

**Status:** aceito
**Data:** 19/08/2026
**Fase:** 7 — fecha a ponta que as ADRs 0042 e 0043 deixaram nomeada duas vezes

## Contexto

A mesma frase está escrita em duas ADRs, com as mesmas palavras:

> **Fica aberto, e nomeado:** teto de **horário** (não mandar às 3 da manhã). (…) é decisão do
> remetente, não do orçamento, e **entra com o canal**.

O canal entrou na ADR 0043. O teto de horário não entrou com ele. Desde então
`send_whatsapp_notices` dispara a qualquer hora, e o único freio é o teto de **frequência** da
ADR 0042 — que conta contatos e não sabe que horas são. Três mensagens por semana permitidas às
três da manhã continuam sendo três mensagens às três da manhã.

**E a fatia mediu, antes de escrever uma linha, que metade dela não era o teto.** Não existia
entrada de `beat_schedule` para `send_whatsapp_notices`: `worker.py` agendava `drive-sync-due`,
`retention-purge`, `erasure-requests` e `onboarding-stuck`, e mais nada. A task de envio só rodava
quando `queue_project_digests` a enfileirava, **no fim de um sync do Biahflow**. Num canal assim,
adiar não é adiar: um aviso que não sai agora depende de outra mudança acontecer naquele projeto
para ser tentado de novo, e num projeto quieto o "depois" não chega. Uma guarda de horário sem
varredura seria um descarte com outro nome — e um descarte que se anuncia como adiamento é pior
que o descarte honesto, porque ninguém vai procurar o aviso que o documento diz que saiu.

O buraco não era só da fatia nova. O `alerts.md` já descrevia a queda do fornecedor com otimismo:
"a próxima passagem do sync tenta de novo". Podia não vir.

## Decisão

**O teto de horário sai com a varredura que o torna verdadeiro.** Duas metades, uma fatia.

### Adiar não é descartar, e por isso esta guarda não carimba

As três guardas que já existiam no laço carimbam `whatsapp_sent_at` e seguem — consentimento
revogado, espécie sem link, teto gasto. As três estão certas: o que as motiva é definitivo. O
relógio não é. Ele não foi gasto, só ainda não chegou.

A guarda de horário é **a primeira que não carimba**, e é essa a diferença que o teste
`test_inside_the_quiet_window_nothing_is_sent_and_nothing_is_stamped` fixa. Carimbar aqui teria
sido a implementação mais parecida com as vizinhas e o oposto do que a decisão diz: um aviso
carimbado nunca mais sai pelo canal, e "não mandar às três da manhã" viraria "não mandar".

### Vem antes do `claim`, não depois

`contact_budget.claim` grava linha, e é essa linha que conta a janela de sete dias. Reservar
orçamento para uma mensagem que não vai sair agora gasta a unidade na hora errada — o aviso
voltaria de manhã já suprimido pelo teto que ele próprio consumiu de madrugada. A ordem do laço
passa a ser consentimento → link → **horário** → orçamento → envio.

### O fuso é constante, as horas são setting

Duas naturezas diferentes, e colapsá-las erraria as duas.

O **fuso** é fato sobre o produto: a ADR 0026 decidiu que fuso não é configurável aqui, sem
coluna e sem rota, e a tela já formata toda data em São Paulo. `PRODUCT_TIMEZONE` é constante de
módulo pela razão do `textfold.py` — um segundo lugar respondendo "que horas são para esta pessoa"
divergiria do primeiro no dia em que alguém editasse um só.

As **horas** não têm medição por trás, exatamente como os três contatos por semana da ADR 0042 —
e por isso são setting, pelo critério que aquela ADR escreveu. Início igual ao fim desliga a
janela, o que evita uma terceira setting booleana decidindo a mesma coisa; e a janela que
atravessa a meia-noite é o caso normal (21 → 8), não a exceção.

### A varredura, que o adiamento obrigou a existir

`send_due_whatsapp_notices` no beat, de quinze em quinze minutos, na forma de
`purge_expired_data` e `alert_stuck_onboarding`: descobre os projetos com aviso pendente e chama
o mesmo laço, um projeto por transação, com `except` por projeto para que um erro num deles não
impeça os outros de chegar à vez — em tick nenhum, se o erro for persistente.

**De quebra ela conserta o que já estava quebrado**: a retentativa depois de uma queda do
fornecedor deixou de depender de um sync que podia não vir. A linha do `alerts.md` que afirmava o
contrário foi retificada com nota datada, em vez de reescrita.

A condição da entrada no beat é `settings.whatsapp_enabled`, e **não** `whatsapp.is_enabled` — que
seria a pergunta mais completa e exigiria montar o token do fornecedor no contêiner do **beat**, um
processo que não fala com fornecedor nenhum. O portal já recusou esse negócio duas vezes (o refresh
token do Drive fora do caminho de requisição, a chave de agente irrecuperável depois de emitida), e
o que se compraria pagando com o segredo é pouco: sem credencial a task devolve zero antes de tocar
o banco, e a metade que importa — "configurado?" — continua conferida onde a mensagem sai.

### Duas passagens não mandam a mesma mensagem duas vezes

Com a varredura são **dois produtores**, e duas passagens podem ler o mesmo aviso pendente. O
`claim` do orçamento não protege disso — ele é idempotente pela chave do aviso e responde `True`
para as duas, de propósito, para a retentativa não custar uma segunda unidade do teto. O risco já
existia com dois syncs simultâneos; a varredura o torna provável em vez de raro.

A resposta é `FOR UPDATE SKIP LOCKED` no próprio `select`, dentro do banco e não em Redis, pelo
precedente da guarda de sobreposição do sync do Drive: a linha que decide já está sendo lida ali,
e um lock noutro sistema seria uma segunda verdade sobre ela. Quem chega depois **pula** em vez de
esperar — esperar apenas faria a segunda passagem reenviar quando a primeira soltasse. E o carimbo
continua **depois** do envio: carimbar antes mataria a retentativa que a ADR 0043 desenhou.

### A checagem é do lote — e o lote tem dois níveis

Dentro de uma passagem, o relógio é o mesmo para todos os avisos: uma linha de log e um retorno,
não uma linha por aviso. Essa decisão estava tomada desde o começo.

O que só apareceu na revisão foi que ela vale um nível acima. Com a guarda apenas dentro da
passagem, o tick da madrugada abriria uma transação e travaria uma linha **por projeto** para
descobrir em cada um a mesma coisa, e gravaria a mesma linha de log a cada quinze minutos pela
noite inteira. A varredura pergunta uma vez por tick; a guarda de dentro fica onde está, porque é
ela que cobre o caminho do sync, que não passa pela varredura.

## Consequências

**O que a fatia mediu e não deduziu:**

- **`zoneinfo` funciona na imagem de runtime.** `python:3.13-slim` traz `tzdata` — conferido
  executando a conversão dentro da imagem. Não trazer teria sido `ZoneInfoNotFoundError` no
  *import* do módulo, derrubando API, worker e beat de uma vez, e a constante está no topo de um
  módulo que a API importa.
- **Sem `skip_locked` a regressão não fica vermelha, fica pendurada**: a passagem bloqueia na linha
  até a outra soltar. Por isso o teste de concorrência tem `join` com prazo e uma asserção sobre
  *ter terminado* — um teste que trava é o modo de falha que já segurou o `web-quality` pelas seis
  horas do runner e escondeu por que os outros jobs falharam.
- **O runbook quase criou um evento fantasma.** A primeira redação citava a task como
  `` `portal_api.send_due_whatsapp_notices` ``, e o casador da guarda de telemetria não distingue
  nome de task de nome de evento: teria reprovado cobrando emissor para um evento que não existe.
  É o `.priority` da ADR 0033 na direção do documento.
- **A varredura é global, e nenhum teste pode afirmar sobre totais.** A primeira versão do teste
  dela reprovou com `2` onde esperava `1`: havia aviso pendente de outro tenant no banco
  compartilhado. A asserção passou a ser sobre o link **deste** projeto dentro do corpo enviado.

**Fica aberto, e nomeado:**

- **Feriado e fim de semana.** Teto de horário não é calendário, e misturar os dois aqui seria
  escopo que ninguém pediu.
- **O e-mail do digest continua sem teto de horário**, de propósito: o argumento das ADRs 0042 e
  0043 é sobre o canal que chega no bolso da pessoa.
- **A homologação não declara as três variáveis novas.** Elas caem no default do compose base, e o
  `docker-compose.homolog.yml` só exige com `${VAR:?}` o que é segredo. Se um dia o teto de horário
  tiver de ser explícito por ambiente, é uma linha lá.
- **O intervalo mínimo por espécie** (ADR 0042) segue aberto e entra junto de `survey_invite`.

**E o que esta fatia não é.** O portal do cliente está fora do ar desde 13/08/2026 (ADR 0053).
Isto fecha uma ponta de código, com portão verde no CI; nada aqui foi observado servindo cliente,
e o primeiro número real sobre a janela — como o do teto de frequência — só existe quando houver
portal de pé emitindo `whatsapp.deferred_quiet_hours`.
