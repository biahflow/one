# FDD 020 — Funil de onboarding

**Status:** **parcialmente implementado** — 07/08/2026 (ADR 0039, ADR 0040). Recorte
construível da **RFC 001**.

> *Os passos 1 e 3 da RFC estão de pé. O 1 — "carimbar sem expor" — trouxe a tabela, as
> policies, os seis degraus escritos pelas rotas de verdade e a purga/apagamento
> alcançando-os. O 3 trouxe a leitura, a lista interna em `/admin/funil` com a distinção
> "travou no cliente" × "travou em nós", e o alerta em dois canais: evento nomeado com
> limiar em `alerts.md` e notificação interna no sino e no digest. **Falta o passo 4**, a
> vigília da IA, que só vem quando houver histórico para priorizar. Os critérios de aceite
> abaixo estão marcados um a um.*

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

**Aceite.** (1) **Feito:** um cliente convidado e sem login aparece na lista com o degrau
pendente e a contagem de dias correta
(`test_a_client_invited_and_never_seen_shows_up_with_the_right_day_count`).
(2) **Feito:** o primeiro login carimba a data uma vez, e um segundo login não altera o
carimbo (`test_the_stamp_is_immutable`). (3) **Adiado, e não esquecido:** o snapshot do
Biahflow não carrega artefato nenhum, então o degrau `artifact_accepted` **não existe** no
enum — declará-lo sem produtor seria o painel sem escritor de novo. O degrau do Biahflow que
existe é o primeiro entregável fora de `pending`, carimbado pelo sync e nunca antes.
(4) **Feito:** um cliente cujo degrau depende de entrega não realizada é rotulado como travado
**em nós** (`test_a_deliverable_that_never_left_pending_is_stuck_on_us`), e a tela põe os dois
lados em painéis separados — nunca uma soma. (5) **Feito:** o apagamento leva os degraus
junto, e precisou de exclusão escrita à mão — escopado por organização, o funil não vem no
CASCADE do projeto (`test_the_erasure_removes_the_funnel_too`). (6) **Feito:** nenhuma rota de
cliente devolve o funil, e o papel de requisição não tem policy sobre a tabela
(`test_the_app_role_never_reads_the_funnel`); a rota interna é `internal_admin` e nega com 404
(`test_a_client_cannot_read_the_onboarding_funnel`).

**A lacuna ganhou um limite que a medição impôs (ADR 0040).** "Degrau ausente não é degrau
zerado" continua valendo, e o que a execução mostrou é que ele quase fez a medição nascer
cega: no primeiro dia da instrumentação *toda* organização é anterior a ela, e o degrau
incerto de todas seria o primeiro login — a tela mandaria ligar para todo cliente do produto
dizendo que ele nunca entrou. O primeiro degrau passou a ter corroboração fora do funil
(`user.external_subject`, que é o sinal que a RFC original apontava); os demais seguem
incertos em organização velha, e uma linha incerta **não conta como travada**. A contagem de
dias, por sua vez, sai sempre de uma data real — o que a regra proíbe é o zero fabricado, e
ele só apareceria se a âncora fosse a data da instrumentação.

## Testes e avaliações de IA

Teste de isolamento entre organizações no funil, junto do meta-teste existente. Teste de
imutabilidade do carimbo. Teste de que a purga por idade e o apagamento por decisão alcançam
os degraus. Teste de que o papel de aplicação não consegue inserir degrau.

**Sem IA até aqui.** A vigília que prioriza quem empacou e escreve o sinal em linguagem de
ação vem depois, quando houver histórico para priorizar — e o `NEXT_ACTION` da ADR 0040, um
mapa estático de degrau × lado, é exatamente o que ela substitui — e quando vier, lê o **agregado**
(quem travou, onde, há quanto tempo), nunca o conteúdo das conversas ou documentos do
cliente, herdando o prompt versionado, as avaliações adversariais e a quota por organização
que já existem.
