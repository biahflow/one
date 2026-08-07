# ADR 0040 — O alerta de cliente travado

**Status:** aceito
**Data:** 07/08/2026
**Fase:** 7 — implementa o passo 3 da RFC 001 (FDD 020)

## Contexto

A ADR 0039 construiu o passo 1 da RFC 001 — *carimbar sem expor* — e encerrou dizendo que o
funil nascia **sem leitor**, de propósito, porque a ADR 0033 achou um painel publicado sobre
um campo que nunca teve escritor. O escritor existe há um dia. Esta ADR é o leitor, e com ele
o valor que a RFC nomeia: *"o valor não está no gráfico — está no alerta por cliente
travado"*.

O caso que a fatia inteira existe para tornar visível é uma linha: **"ganho há nove dias,
convite enviado, nunca logou"**. Aos nove dias ainda se resolve com um telefonema; aos trinta
virou churn.

## Decisão

### A leitura mora em `onboarding.py`, ao lado do carimbo

Mesma razão que o docstring daquele módulo já escrevia: se "o que conta como degrau" estiver
espalhado, a pergunta que a RFC quer responder deixa de caber num arquivo — e é exatamente a
pergunta de quem calibra o alerta. A forma é a de `results.py`: computação **na leitura**,
pura sobre uma `Session`, com `gaps` onde falta base.

### O degrau atual é o mais baixo em aberto, e não o mais alto alcançado

Parece equivalente e não é. `stamp` aceita `reached_at` justamente para o degrau do Biahflow,
que chega pelo sync com a data do fato — então um cliente pode ter
`first_deliverable_delivered` carimbado com data **anterior** a um `first_login` que nunca
aconteceu. "Mais alto alcançado" diria que esse cliente completou o funil. A regra do mais
baixo em aberto diz que ele está travado no login, que é a verdade: entregamos alguma coisa
que ele nunca viu.

### A rota autoriza sob `portal_admin` e computa sob `portal_system`

Duas transações, e não é atalho. **`pending_item` não tem policy `TO portal_admin`** — grep
de `CREATE POLICY` nas migrações: o papel administrativo tem policy em `organization`,
`project`, `membership`, `user`, `document`, `organization_ai_quota` e mais oito tabelas, e
não nessa. O `roles.sql` concede o `SELECT` por default privileges, então a consulta **não
falha**: devolve zero linhas em silêncio.

É o mesmo desenho que a ADR 0039 escolheu de propósito para `portal_app` nesta mesma tabela,
encontrado do lado de dentro. Sob o papel administrativo, o `EXISTS` de "há pendência aberta
nesta organização?" responderia "não" para **todas**, e todo cliente do produto apareceria
rotulado *travou em nós* — com a forma de um alerta de verdade, e nada ficando vermelho.

A alternativa considerada era uma policy nova em `pending_item`. Recusada: alargaria
permanentemente o alcance da credencial administrativa sobre conteúdo do cliente (títulos e
descrições de pendência) para atender um `EXISTS`. A autorização não afrouxa por isso — o
`organization_id` que a segunda transação usa é o que `_authorized_org` acabou de provar, e
não o que veio na URL. O precedente de abrir sessão de sistema dentro de `admin.py` é
`_claim_oauth_state`.

### O alerta toca uma vez, e a memória disso já existia

O evento sai **uma vez por organização e por degrau**, como o `step_reached`. A memória de
"já avisei" não é tabela nova: é o `dedupe_key` da notificação que acompanha o alerta, com
`uq_notification_user_dedupe_key` e `ON CONFLICT DO NOTHING` — `fan_out` devolve só os ids
que nasceram, e lista vazia significa que o sino já tem.

Persistir o estado foi considerado e tem preço escrito: a tabela do funil **não aceita
`UPDATE` de papel nenhum**, nem do sistema (migração 0024), então seria tabela própria, com
policy (o meta-teste de isolamento cobra), predicado de purga e uma **terceira** exclusão à
mão em `run_erasure`. Tudo para guardar um booleano.

A chave é `onboarding:stuck:<organization_id>:<step>`, **sem data** — ao contrário do
`project_status_changed`, onde a data existe porque um projeto volta a um status anterior e a
segunda transição seria engolida. Aqui o fato não recorre: uma vez alcançado, o degrau deixa
de ser o degrau travado. E **com** o `organization_id`, que não é redundante com a coluna: a
unicidade é `(user_id, dedupe_key)`, e um `internal_admin` que administra duas organizações
teria o aviso da segunda deduplicado contra o da primeira.

O custo honesto: `notification` é podada aos `retention_notification_days` (180), então uma
organização travada há mais de meio ano toca de novo, uma vez. Está declarado no `alerts.md`
em vez de engenheirado contra — um cliente travado há seis meses merece o segundo olhar.

### `_INTERNAL_ONLY` deixa de ser órfã

`NotificationKind.onboarding_stuck` é o **primeiro** aviso cuja audiência é só o time. A
constante existe em `notifications.py` desde a ADR 0012 e nunca fora usada — constante
definida e nunca usada é a mesma forma do campo sem escritor que a ADR 0033 encontrou.

E o esquecimento aqui não seria silencioso, seria **invertido**: `recipients` faz
`AUDIENCE.get(kind, _CLIENT_ONLY)`, de modo que uma espécie sem linha no mapa avisa **o
cliente** de que ele está sendo medido — exatamente o que a FDD 020 proíbe. Daí a guarda de
completude nova (`test_every_notification_kind_declares_its_audience`), que não opina sobre
qual audiência é certa: cobra que alguém tenha escolhido.

### O projeto que ancora o aviso

`Notification` é escopada por projeto e o funil por organização, então alguma linha tem de
ser escolhida: o **projeto vivo mais antigo**, `ORDER BY created_at ASC, id ASC`. O `id` não
é enfeite — `created_at` é `server_default now()`, e no Postgres `now()` é o instante de
início da transação, então dois projetos criados pelo mesmo sync empatam. E mesmo que a
âncora mude entre passagens, o aviso não duplica: a chave não carrega projeto.

Organização sem projeto vivo é pulada inteira, o que resolve junto o fantasma pós-expurgo:
`run_erasure` apaga projetos e `membership` e **mantém** a linha `organization`, de propósito
(ADR 0017). Sem o filtro, todo tenant apagado viraria uma linha perpétua "ninguém foi
convidado" com um alerta diário atrás.

### O que o alerta emite quando não há a quem avisar

`onboarding.alert_undeliverable`, e ele fecha um ponto cego real: sem destinatário interno o
`fan_out` devolve vazio, o que é indistinguível de "já avisei" — o tenant ficaria travado em
silêncio absoluto, o único desfecho pior que o alerta não existir. Repete a cada passagem de
propósito: é defeito de configuração, não sinal de cliente.

## O defeito que só apareceu ao executar

**A primeira regra de lacuna teria feito a medição nascer cega**, e foram dois erros
encavalados que só a execução separou.

O primeiro: a condição era `anchor_at >= INSTRUMENTED_SINCE`, juntando duas perguntas
diferentes. Um carimbo de **anteontem** saía sem contagem, porque a instrumentação começou
ontem — e um carimbo é um fato com data, então "há quantos dias este cliente não recebe nada"
continuava perfeitamente verdadeiro. A incerteza é sobre **o degrau** (uma organização de
junho pode ter aberto um documento em junho, sem carimbo), não sobre o relógio.

O segundo, mais caro, apareceu ao corrigir o primeiro: no dia 07/08/2026, *toda* organização
existente é anterior à instrumentação, e o degrau incerto de todas elas seria `first_login`.
A tela nasceria mandando **ligar para todo cliente do produto** dizendo que ele nunca entrou
no portal — o alerta mais caro possível, porque telefona justamente para quem está usando o
produto, no primeiro dia. E não haveria nada de errado no código: a lacuna estava declarada,
a regra estava coerente, e o resultado era inútil.

A saída é a evidência que a própria RFC 001 apontava e que a ADR 0039 tinha usado para outra
coisa: **`user.external_subject`**. Ele deixa de ser nulo no primeiro login, não depende do
funil e sobrevive a qualquer coisa que a instrumentação tenha perdido. Consultado, o degrau do
login passa a ter corroboração fora do carimbo — e é o único que tem. Os demais continuam
incertos em organização velha, e uma linha incerta **não conta como travada**: ninguém é
chamado por um degrau que talvez já esteja cumprido.

A contagem de dias, por sua vez, nunca é nula quando há degrau em aberto, e isso é o que a FDD
020 de fato exige. O que ela proíbe é exibir "0 dias" para quem talvez já tenha passado — e o
zero fabricado só apareceria se a âncora fosse a data da instrumentação. Ela nunca é: é o
último carimbo, o convite, ou a criação da organização, todas datas reais.

## Consequências

- **A tela não escreve nada**, então `app/admin/actions.ts` não ganha `revalidatePath` novo.
  Não é esquecimento: `/admin/assistente` também está ausente daquelas quatro linhas pelo
  mesmo motivo, e a página é `force-dynamic` com `cache: "no-store"`.
- **A ordenação por gravidade mora no BFF**, e a rota da API continua escopada por
  organização. `bind_admin_org` é monotônica — religar outra organização na mesma transação
  levanta —, então uma rota cross-org não conseguiria ler sob as policies do papel
  administrativo. O fan-out é o preço, e ele mantém "rota escopada declara 404" e o
  `_CANNOT_ANSWER_404` com uma linha só.
- **Um 404 no fan-out derruba a linha e não a página**, ao contrário de `/admin/organizacao`.
  Lá o id vem da URL e 404 significa "você não administra esta"; aqui os ids vieram da
  listagem derivada dos vínculos do próprio chamador, então 404 é corrida — e um vínculo
  revogado não pode apagar da tela a lista de todos os outros clientes.
- **As cinco settings novas não entram no `.env.example` nem no compose**, e isto não é a
  armadilha da ADR 0022: aquela é a inversa (variável documentada que nenhum compose passa), e
  a guarda que a codifica roda numa direção só. O precedente irmão é
  `retention_onboarding_days`, de ontem. A consequência é que o alerta nasce ligado e
  desligá-lo exige editar o compose — a mesma postura da retenção.
- **O `NEXT_ACTION` é um mapa estático**, e é o que a IA substitui no passo 4. Enquanto ela
  não vem, é a fatia inteira do valor: um alerta sem o que fazer é um relatório com um sino.
- **O digest sai com o texto do cliente.** `_subject`/`_body` falam "Novidades em {projeto}",
  e para um lote de um item o assunto é o próprio título do alerta, que lê bem; só um lote
  misto lê estranho. Ramificar o template é fatia própria e tem pergunta aberta de verdade
  (qual assunto para um lote que mistura `pending_opened` e alerta interno).

## O que fica em aberto

A **vigília da IA** (passo 4 da RFC 001), que lê o agregado — quem travou, onde, há quanto
tempo — e nunca o conteúdo das conversas ou dos documentos, herdando o prompt versionado, as
avaliações adversariais e a quota por organização. E `artifact_accepted`, que continua sem
produtor no snapshot: fatia do outro lado, na forma da ADR 0037.
