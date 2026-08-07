# FDD 022 — Pesquisa de satisfação por evento

**Status:** proposta — 07/08/2026. Nada aqui está implementado. **Segundo sinal**: só começa
depois que o laço de ação do funil (FDD 020) estiver fechado de verdade.

## Objetivo e não objetivos

**Objetivo.** Perguntar ao cliente como foi, **no momento em que algo terminou**, e
transformar nota baixa em **alerta ao time na hora**. O funil mede se ele usa; a satisfação
mede se ele gosta — a outra metade da retenção, e a que nenhum dado de uso conta. Um cliente
pode logar, aprovar e ver ROI e ainda assim estar frustrado com algo que nenhum evento
captura.

**Não é objetivo** produzir NPS de calendário. Pesquisa trimestral cuja média vira número em
slide é teatro de métrica: consome esforço e dá a ilusão de estar ouvindo. O princípio é
**medir para agir, não para reportar** — se a nota não dispara ação, a pergunta não é feita.

**Não é objetivo** construir painel antes do escritor. Este repositório já exibiu "O que os
clientes disseram" sobre um campo que **nunca teve escritor** e era sempre nulo (ADR 0033). A
ordem aqui é a inversa, e é regressão crítica.

**Não é objetivo** conversar. A pergunta é uma, a resposta mora no portal, e não há bot.

## Jornada e interface

Terminado um momento com significado — uma fase da jornada concluída, um entregável aceito,
o fim de um ciclo de reunião —, o cliente recebe **uma pergunta, dois toques**, com o
contexto embutido: "como foi o Assessment?", não um NPS genérico que se responde no
automático. Nota, e um campo de texto opcional.

O aviso pode sair pelo WhatsApp (FDD 021) — é o melhor caso de uso do canal, abertura quase
certa e atrito baixo —, desde que o link caia na pergunta e **a resposta seja registrada no
portal**. Notificação puxa; portal registra.

Do lado interno, a nota baixa aparece imediatamente na fila de ação, com o comentário e o
contexto do evento. Detração recente é a janela mais barata para salvar um cliente, e ela
fecha em dias.

## Dados, API e permissões

**A forma já existe e é copiada, não inventada.** `conversations.record_feedback` grava nota
e comentário com `UPDATE` **escopado por coluna** (ADR 0015), e a ADR 0030 — "o sinal do
assistente, **sem a pergunta do cliente**" — monta a leitura interna com o GRANT garantindo
que o time leia a avaliação sem ler o conteúdo perguntado. A pesquisa herda exatamente isso:
escrita uma vez pela pessoa, nunca reescrita, time lendo o sinal.

**Modelo.** Convite de pesquisa (a quem, sobre qual evento, quando enviado) e resposta (nota,
comentário, instante), sob `TenantMixin`, com policy na mesma migração — o meta-teste de
isolamento reprova o CI caso contrário. Onde a linha pertence a uma pessoa, as policies somam
o predicado do usuário ao do tenant, na forma de `notification`.

**Grants.** O papel de aplicação recebe `INSERT` da resposta — é a pessoa que a origina, a
mesma inversão que a conversa já fez — e **nenhum `UPDATE`** sobre nota e comentário depois
de gravados. Ninguém reescreve o que o cliente disse, pela mesma razão pela qual ninguém
reescreve as citações que uma resposta mostrou.

**Teto de frequência por pessoa**, compartilhado com os demais avisos. Gatilho por evento
vira spam se todo micro-evento pedir nota, e pesquisa demais derruba a taxa de resposta até
sobrar só quem estava com raiva o bastante para clicar — o pior viés possível. A régua está
no próprio repositório: a ADR 0030 contou **143 respostas do assistente e 6 avaliadas**.

*O teto foi entregue em 07/08/2026, em fatia própria e antes desta FDD (ADR 0042) — o
combinado era sair junto daqui, e não sobrevivia ao fato de esta FDD estar bloqueada e a
FDD 021 não. Ele mora em `portal_api.contact_budget`, e quando o convite existir bastará
acrescentar `survey_invite` ao `ContactKind` — que hoje tem uma espécie só, pela regra de não
declarar espécie sem produtor.*

***E a fatia mediu uma coisa que esta FDD não sabia, que muda o critério (2) abaixo:** o teto
global **não** o satisfaz sozinho. "Um segundo evento na mesma semana não gera segundo convite"
é uma afirmação sobre **a espécie**, e o orçamento é sobre o volume total — com teto de três
por semana e nenhum outro contato, dois convites passam. Falta um **intervalo mínimo por
espécie**, e ele entra junto de `survey_invite`, no mesmo módulo. Fica escrito aqui em vez de
virar dívida que alguém redescobre no meio da implementação.*

**Poucos momentos, escolhidos.** Fase concluída e entregável aceito bastam para começar.

## Estados de erro e segurança

**Resposta é dado pessoal.** Entra na `data-classification.md`, é alcançada pela retenção por
organização e pelo apagamento por decisão (ADR 0017).

**Convite sem resposta não é nota zero.** É ausência, e a leitura declara a lacuna — pelo
mesmo princípio com que a apuração de resultado declara base ausente em vez de dividir por
zero. Taxa de resposta é informação, não ruído a esconder.

**A pergunta não vaza contexto de terceiro.** O convite carrega o evento daquele projeto e
nada mais.

**Nenhum caminho reabre uma resposta.** Sem `UPDATE`, uma correção é uma nova resposta com
carimbo próprio, e o histórico permanece.

## Telemetria e critérios de aceite

Eventos com runbook, guarda bidirecional: convite enviado, convite suprimido por teto de
frequência, resposta registrada, alerta de detração emitido. O comentário **não** vai para o
log nem para a auditoria — a mesma regra que o termo digitado na busca já segue.

**Aceite.** (1) Concluída uma fase, o cliente recebe uma pergunta com o contexto daquela
fase, e não um NPS genérico. (2) Um segundo evento na mesma semana **não** gera segundo
convite, por causa do teto. (3) Nota baixa aparece na fila de ação interna imediatamente,
com o comentário. (4) O cliente não consegue editar a nota depois de enviada; uma correção
cria nova resposta. (5) Nenhuma tela interna exibe o painel agregado antes de existir
escritor e dado — e o painel, quando vier, não mostra campo que ninguém escreve. (6) O
apagamento de uma organização leva convites e respostas junto.

## Testes e avaliações de IA

Teste de isolamento entre organizações; teste do teto de frequência; teste de que o papel de
aplicação não consegue atualizar nota ou comentário; teste de que o comentário não aparece em
log nem em auditoria. E a guarda de forma que a ADR 0033 originou: **nenhum painel sobre
campo sem escritor** — a asserção olha o controle e o produtor, não só o valor.

**A IA entra depois, e só para ler o texto aberto.** A nota é rasa; o ouro está no "por quê"
que o cliente escreve. Ela classifica o comentário, resume o padrão da carteira — "três
clientes reclamaram de prazo de resposta este mês" — e prioriza detratores para o time. Herda
o prompt versionado com registro de digests, as avaliações adversariais contra modelo hostil
e a quota por organização já existentes. **IA resume e sinaliza; humano age.** Nada disso
responde ao cliente.

**E a trave que nenhuma feature resolve:** o jogo real é velocidade de resposta. Um alerta de
detração que ninguém atende em horas é pior que não perguntar, porque a pergunta cria
expectativa. Isso é compromisso operacional, não código — e é por isso que este é o **segundo**
sinal, não o primeiro: três radares tocando para um time que não dá conta de agir em um é
pior que um radar que ele respeita.
