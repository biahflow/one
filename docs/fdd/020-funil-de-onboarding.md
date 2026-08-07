# FDD 020 — Funil de onboarding

**Status:** **parcialmente implementado** — 07/08/2026 (ADR 0039). Recorte construível da
**RFC 001**.

> *O passo 1 da RFC — "carimbar sem expor" — está de pé: a tabela, as policies, os seis
> degraus escritos pelas rotas de verdade, e a purga e o apagamento alcançando-os. **Não**
> estão de pé a lista interna de clientes travados, a distinção "travou no cliente" × "travou
> em nós" e a vigília da IA; eles são os passos 3 e 4 da RFC, e a ordem é deliberada. Os
> critérios de aceite abaixo estão marcados um a um.*

## Objetivo e não objetivos

**Objetivo.** Registrar **quando** cada degrau de valor foi alcançado por organização, e
acender um alerta interno quando um cliente trava num degrau. A régua é o
**time-to-first-value**: do ganho até a primeira aprovação e até o primeiro ROI visto.

**Não é objetivo** medir esforço do cliente. "Logou doze vezes" não entra: pode ser um
cliente perdido procurando o que deveria estar óbvio, e instrumentar esforço otimiza
engajamento medindo ansiedade. Só entra degrau em que o cliente **recebeu** algo.

**Não é objetivo** produzir painel de conversão agregada nesta fatia. O valor está no alerta
por cliente travado; o agregado vem depois, e depois de haver dado — este repositório já
publicou um painel sobre um campo que nunca teve escritor (ADR 0033), e a ordem aqui é
deliberadamente a inversa.

**Não é objetivo** originar status. O portal observa e carimba; o Biahflow continua sendo
quem afirma que algo aconteceu (ADR 0006/0008).

## Jornada e interface

Um degrau alcançado não muda nada na tela do cliente — ele não deve saber que está sendo
medido em funil, e não há nada a fazer com essa informação do lado dele.

Do lado interno, `/admin` ganha a lista de clientes com o degrau atual, há quantos dias
parado e qual a próxima ação sugerida, ordenada por gravidade. O caso que justifica a fatia
inteira é a linha "ganho há nove dias, convite enviado, nunca logou" — hoje invisível, e aos
nove dias ainda recuperável com um telefonema.

Cada linha distingue **travou no cliente** de **travou em nós**: se o degrau não avança
porque a entrega não saiu, o alerta é sobre a equipe. Os dois aparecem, com rótulos
diferentes, e nunca somados na mesma contagem.

## Dados, API e permissões

**Degraus deste repositório**, todos já existentes como estado: convite aceito e primeiro
login (`user.external_subject` deixando de ser nulo), primeiro documento aberto, primeira
pendência respondida, primeira conversa com o assistente, primeiro ROI visto.

**Degraus vindos do Biahflow**, pelo sync que já existe: artefato aceito e primeiro
entregável saindo de `pending`. Esses **não** são inferidos aqui — chegam afirmados.

**Modelo.** Uma linha por organização e degrau, com o instante da primeira ocorrência, sob
`TenantMixin`, sem qualificação de esquema (o `search_path` cuida disso). O carimbo é
**imutável**: primeira vez é primeira vez, e reescrevê-lo destruiria a única métrica que
interessa. Não há `UPDATE` no contrato.

**Escrita é do produtor.** O carimbo nasce do sync ou de um observador do lado do servidor,
sob a credencial de sistema. O papel de aplicação **não** ganha `INSERT` sobre o funil — um
caminho de requisição capaz de escrever o próprio degrau é um caminho capaz de falsear o
próprio engajamento. É a mesma razão pela qual só o sistema insere em `notification`.

**Policy na mesma migração**, como toda tabela com `organization_id`; o meta-teste de
isolamento reprova o CI caso contrário. Onde houver `user_id`, as policies somam o predicado
da pessoa ao do tenant, na forma de `notification`.

**API.** Nenhuma rota de cliente. As rotas internas ficam sob `/api/v1/admin/*`, alcançáveis
só por quem já é `internal_admin` na organização, e entram no contrato publicado com a regra
de sempre: ninguém declara 403, rota escopada declara 404.

## Estados de erro e segurança

**Degrau ausente não é degrau zerado.** Um cliente sem carimbo de "primeiro ROI visto" pode
não ter chegado lá **ou** pode ser anterior à instrumentação. A leitura declara a lacuna em
vez de exibir "0 dias", pelo mesmo princípio com que `results.py` declara base ausente em vez
de dividir por zero.

**Comportamento de pessoa identificada é dado sensível.** Entra na `data-classification.md`,
é alcançado pela retenção por organização e pelo apagamento por decisão (ADR 0017). Um funil
que sobrevive ao apagamento do tenant reintroduziria o defeito que aquela ADR fechou.

**Sync parcial não vira degrau falso.** Se a sincronização truncar, o degrau do Biahflow não
é carimbado — ausência de afirmação não é negação, e tampouco confirmação.

## Telemetria e critérios de aceite

Eventos com runbook correspondente, porque a guarda é bidirecional (ADR 0034): degrau
carimbado, cliente entrando em estado travado, alerta emitido. Nenhum deles carrega conteúdo
— só identificadores e o nome do degrau.

**Aceite.** (1) ~~Um cliente novo, convidado e sem login, aparece na lista interna com o
degrau "convite aceito" pendente e a contagem de dias correta.~~ **Passo 3** — não há lista.
(2) **Feito:** o primeiro login carimba a data uma vez, e um segundo login não altera o
carimbo (`test_the_stamp_is_immutable`). (3) **Adiado, e não esquecido:** o snapshot do
Biahflow não carrega artefato nenhum, então o degrau `artifact_accepted` **não existe** no
enum — declará-lo sem produtor seria o painel sem escritor de novo. O degrau do Biahflow que
existe é o primeiro entregável fora de `pending`, carimbado pelo sync e nunca antes.
(4) ~~Um cliente cujo degrau depende de entrega não realizada aparece rotulado como travado
**em nós**.~~ **Passo 3.** (5) **Feito:** o apagamento leva os degraus junto, e precisou de
exclusão escrita à mão — escopado por organização, o funil não vem no CASCADE do projeto
(`test_the_erasure_removes_the_funnel_too`). (6) **Feito:** nenhuma rota de cliente devolve o
funil, e o papel de requisição não tem policy sobre a tabela
(`test_the_app_role_never_reads_the_funnel`).

## Testes e avaliações de IA

Teste de isolamento entre organizações no funil, junto do meta-teste existente. Teste de
imutabilidade do carimbo. Teste de que a purga por idade e o apagamento por decisão alcançam
os degraus. Teste de que o papel de aplicação não consegue inserir degrau.

**Sem IA nesta fatia.** A vigília que prioriza quem empacou e escreve o sinal em linguagem de
ação vem depois, quando houver histórico para priorizar — e quando vier, lê o **agregado**
(quem travou, onde, há quanto tempo), nunca o conteúdo das conversas ou documentos do
cliente, herdando o prompt versionado, as avaliações adversariais e a quota por organização
que já existem.
