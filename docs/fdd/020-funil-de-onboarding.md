# FDD 020 — Funil de onboarding

**Status:** **parcialmente implementado** — 07/08/2026 (ADR 0039, ADR 0040, ADR 0041).
Recorte construível da **RFC 001**.

> *Os passos 1 e 3 da RFC estão de pé, e os **sete** degraus existem. O 1 — "carimbar sem
> expor" — trouxe a tabela, as policies, os seis degraus que tinham produtor e a
> purga/apagamento alcançando-os. O 3 trouxe a leitura, a lista interna em `/admin/funil` com
> a distinção "travou no cliente" × "travou em nós", e o alerta em dois canais: evento nomeado
> com limiar em `alerts.md` e notificação interna no sino e no digest. A ADR 0041 fechou o
> sétimo degrau, `artifact_accepted`, quando o Biahflow passou a afirmá-lo (FDD 031 de lá) —
> e com ele a régua, porque a âncora do funil passou a poder começar no **ganho**. **Falta o
> passo 4**, a vigília da IA, que só vem quando houver histórico para priorizar. Os critérios
> de aceite abaixo estão marcados um a um.*

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
carimbo (`test_the_stamp_is_immutable`). (3) **Feito em 07/08/2026 (ADR 0041), e o adiamento
era condicional:** este critério dizia que `artifact_accepted` **não existia** no enum porque
"o snapshot do Biahflow não carrega artefato nenhum" e declarar degrau sem produtor seria o
painel sem escritor de novo. A condição estava escrita — *"ele entra quando o outro lado o
afirmar"* — e o outro lado afirmou: a FDD 031 de lá pôs `artifact_accepted_at` no snapshot,
com emissor, levando **só a data**. O sync carimba com a data da decisão
(`test_the_snapshot_stamps_the_approval_with_the_date_of_the_decision`), e um Biahflow
anterior àquela fatia não carimba nada (`test_a_snapshot_without_the_field_stamps_nothing`).
São **dois** os degraus que nascem lá agora — a aprovação e o primeiro entregável fora de
`pending` —, e nenhum é carimbado antes de o snapshot o afirmar.
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

**E o mesmo limite valeu para o sétimo degrau (ADR 0041), previsto em vez de descoberto.**
Sendo o primeiro da escada, `artifact_accepted` sem carimbo seria o degrau atual de toda
organização anterior à FDD 031 do Biahflow — a tela mandaria registrar o contrato de clientes
que estão em produção há meses. A corroboração é estrutural: **projeto vivo no Biahflow
significa negócio fechado**, então a existência da linha reconhece o degrau, declara
`artifact_not_reported` e **não escreve carimbo** — por isso a âncora daquela organização
continua saindo do convite, que é honesto. Na prática o degrau só fica em aberto para quem não
tem projeto vivo, e aí ele é a verdade. *"Não registraram o artefato" com projeto vivo é
higiene de cadastro, não desengajamento*, e um radar que telefona por isso é um radar que o
time aprende a ignorar.

**A régua ganhou o ponto de partida que lhe faltava.** O `_anchor` da ADR 0040 nunca teve o
**ganho**: sua cadeia era último carimbo → convite → criação da organização. Um cliente ganho
em 12/06 e convidado em 30/07 contava a partir de 30/07, de modo que dezoito dias de demora
**nossa** encurtavam o número em vez de aparecer nele — o funil escondendo justamente o atraso
que existe para tornar visível. Com o carimbo da aprovação, a contagem começa no ganho
(`test_the_approval_anchors_the_ruler_on_the_win_and_not_on_the_invite`).

## Testes e avaliações de IA

Teste de isolamento entre organizações no funil, junto do meta-teste existente. Teste de
imutabilidade do carimbo. Teste de que a purga por idade e o apagamento por decisão alcançam
os degraus. Teste de que o papel de aplicação não consegue inserir degrau.

**Mais o defeito que a ADR 0041 mediu, e ele era da ADR 0039** — os dois testes que o seguram
no lugar. `sync_snapshot` **cria** a organização e chamava um `stamp` de sessão própria: no
primeiro snapshot de um cliente novo a linha `organization` ainda não estava comitada, a
chave estrangeira barrava o `INSERT` e o carimbo se perdia em silêncio, saindo como
`onboarding.stamp_failed` — que o `alerts.md` diagnostica como indisponibilidade do banco.
Era raro com o entregável e é o caso **central** com a aprovação. `stamp_within` carimba
dentro da transação que já é do sistema, com `SAVEPOINT`, e há teste para os dois lados: o
primeiro snapshot de um cliente novo já carimba
(`test_the_first_snapshot_of_a_brand_new_client_already_stamps`), e um degrau impossível de
gravar não derruba a transação que o continha
(`test_a_failed_stamp_inside_the_sync_does_not_take_the_transaction_down`).

**Sem IA até aqui**, e o passo 4 continua condicionado ao que três documentos escrevem: a
instrumentação tem um dia e o time ainda não agiu sobre um alerta. A vigília que prioriza quem
empacou e escreve o sinal em linguagem de
ação vem depois, quando houver histórico para priorizar — e o `NEXT_ACTION` da ADR 0040, um
mapa estático de degrau × lado, é exatamente o que ela substitui — e quando vier, lê o **agregado**
(quem travou, onde, há quanto tempo), nunca o conteúdo das conversas ou documentos do
cliente, herdando o prompt versionado, as avaliações adversariais e a quota por organização
que já existem.
