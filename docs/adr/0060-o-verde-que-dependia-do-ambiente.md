# ADR 0060 — O verde que dependia do ambiente

**Status:** aceito
**Data:** 20/08/2026
**Fase:** 7 — irmã da ADR 0058, e retificação do diagnóstico que ela deixou

## Contexto

A ADR 0058 tirou o **relógio** de dentro do verde da bateria e declarou duas pontas
abertas. Esta fatia mede as duas e descobre que uma delas estava **diagnosticada errado**.

### A ponta que a 0058 acertou: a configuração ainda decide

Aquela ADR escreveu que "`_settings()` ainda deixa `CONTACT_QUIET_HOURS_START/END` do
ambiente entrar nos testes de janela". Está certo, e é maior do que parecia — são **duas**
portas e não uma:

| # | Medição | Resultado |
|---|---|---|
| M1 | `CONTACT_QUIET_HOURS_START=0 CONTACT_QUIET_HOURS_END=0 pytest test_whatsapp.py` | reprovam **5** |
| M2 | um `.env` no disco com **só** aquelas duas linhas, sem variável exportada | reprovam **os mesmos 5** |

Os cinco são `test_inside_the_quiet_window_nothing_is_sent_and_nothing_is_stamped`,
`test_inside_the_quiet_window_the_contact_budget_is_not_spent`,
`test_after_the_quiet_window_the_same_notice_goes_out`,
`test_the_window_is_read_in_the_product_timezone_and_not_in_utc` e
`test_the_sweep_asks_the_clock_once_instead_of_waking_every_project`.

**M2 é a porta que a ADR 0058 não viu.** `Settings.model_config` carrega `env_file=".env"`,
e quem seguiu o `cp .env.example .env` do README tem um: fechar só `os.environ` deixaria
metade do problema de pé, com a aparência de resolvido.

E o alcance não é de duas variáveis. São **103 campos** em `Settings`, e o `.env` chega a
qualquer um deles.

### A ponta que a 0058 errou: não é resíduo do banco

A ADR 0058 declarou que `test_authorization.py::test_a_client_only_sees_and_reads_their_own_notifications`
e `test_drive_sync.py::test_the_beat_tick_only_fans_out_enabled_connections` "leem estado
deixado por execuções anteriores no Postgres de desenvolvimento". **Para o primeiro, isso é
falso**, e a medição é de dois passos:

| # | Execução | Resultado |
|---|---|---|
| M3a | `test_authorization.py` com o contêiner `worker` **de pé** | `assert ['Para o clie...erta pela IA'] == ['Para o cliente']` — *Left contains one more item: 'Pendência aberta pela IA'* |
| M3b | `docker compose stop worker` e o **mesmo** teste, no **mesmo banco** | passa, exit 0 |

Mesmo banco, mesma linha, resultado oposto: não pode ser resíduo. O fixture `world`
(`test_authorization.py:76-77`) é `scope="session"` e etiquetado com `uuid.uuid4().hex[:8]`,
de modo que nada de corrida anterior alcança aquela caixa.

O que acontece é o **processo ao lado escrevendo durante a corrida**. Oitenta e nove linhas
antes, no mesmo `world`, `test_a_gap_in_the_chat_writes_a_pendencia_and_an_audit_entry`
(`:358`) faz um `POST /chat` de verdade; `main.py:562` chama `queue_pending_notification`
(`worker.py:1240`), que publica `notify_pending_created` no **Redis do compose**; o contêiner
`worker` consome a task contra o **mesmo Postgres** e insere a notificação — e
`NotificationKind.pending_opened` é `_EVERYONE` (`notifications.py:74`), então ela cai na
caixa do cliente.

A ADR 0058 acertou sobre o segundo teste pela metade. Ele reprova (M4:
`assert ['44adc759-8fa6-43d2-892c-fe8167646572'] == []`) por causa de uma conexão de Drive
de outro tenant no banco — mas isso **não é resíduo a limpar**: `sync_due_drive_connections`
é uma varredura **global por desenho** (`worker.py:439-443`), e `assert queued == []` é uma
asserção sobre o produto inteiro. Ela ficou verde por anos só porque o banco de quem rodava
estava vazio.

**Uma retificação de ADR aceita é ADR nova**, não uma reescrita: a linha da 0058 fica onde
está, e esta ADR é o que a corrige.

### O terceiro sítio, e por que ele não aparecia

`test_onboarding.py:714-717` afirma `resultado["alerted"] == 1` e
`enfileirados == [str(cenario.project_id)]` sobre `alert_stuck_onboarding`, que também é
global. **Passa hoje** (M5), e por acidente do arranjo: o monkeypatch `falha_na_primeira`
(`:702-707`) levanta para toda organização que não é a do cenário, e o `except` do laço
(`worker.py:673-678`) as tira da conta. A imunidade vem do monkeypatch, não da asserção.

## Decisão

**A bateria lê o ambiente para saber *onde está um serviço*, nunca para saber *como o
produto se comporta*. E o que ela enfileira para no processo dela.**

### Metade A — as fontes da `Settings`, e não os campos

`conftest.py` troca as **fontes** que o Pydantic monta, via
`Settings.settings_customise_sources`, envolvendo `env_settings` **e** `dotenv_settings` num
filtro sobre `INHERITED_FROM_THE_ENVIRONMENT` — sete nomes, cada um com motivo escrito, cada
um passado ao processo de teste por um bloco `env:` do `ci.yml` (`:48-51` e `:119-121`).

**Não** fixar `contact_quiet_hours_*` no `base` de `_settings()`: aquilo consertaria 2 campos
em 1 arquivo e deixaria 101 campos de pé — a lista escrita à mão que a ADR 0033 mediu.
**Não** largar o `dotenv` inteiro: quebraria quem guarda `STORAGE_ACCESS_KEY` no `.env`
local, que é o caso legítimo que a allowlist existe para preservar.

**Envolver** a instância que o Pydantic montou, em vez de subclassar e reconstruir: ela já
sabe do `env_file`, do `case_sensitive` e dos prefixos, e refazê-la criaria um segundo lugar
decidindo como uma variável vira campo — a divergência silenciosa contra a qual `textfold.py`
existe.

**No nível de módulo do conftest, e isso é medível em vez de estilo:** `worker.py:60` chama
`get_settings()` no import, `:67` monta o `celery_app` com `settings.redis_url` e `:110-154`
deriva o `beat_schedule` de flags de `Settings`. Uma fixture `autouse`, ainda que de sessão,
chegaria depois do import dos módulos de teste.

**Uma saída, estreita e escrita.** Uma subclasse de `Settings` que **nomeia o próprio
arquivo** tem o `dotenv` liberado, porque nomear é declarar. Foi medido: sem isso,
`test_homolog_config.py::test_the_homolog_template_is_itself_refused` fica **vermelho** — a
pergunta dele é literalmente *"o `.env.homolog.example` seria recusado?"*, e filtrar responde
"sim, porque não li o arquivo", que é a resposta certa pela razão errada. O `os.environ`
continua filtrado até para ela, porque o ambiente nunca é declaração de ninguém, e a saída
tem allowlist com motivo e guarda própria — senão ela seria invisível, e bastaria escrever a
subclasse para o isolamento sumir num arquivo, em verde.

### Metade B — a porta única do enfileiramento, e um vizinho barulhento

**B0.** Fixture `autouse` interceptando `worker.celery_app.send_task` — a porta por onde todo
`.delay()` desce, via `Task.apply_async`. O repositório já sabia do defeito e o consertou num
sítio só: o docstring de `queued_ingestions` (`conftest.py:298-313`) diz com todas as letras
que *"sem isto o upload publicaria de verdade no Redis do compose, e o worker que estiver de
pé pegaria a task no meio do teste"*. O que faltava era a porta, e não o remendo — é o padrão
da ADR 0035, a lista escrita à mão virando predicado derivado.

**B1, B2, B3 — as três asserções passam a ser sobre linhas identificadas.**

- `test_drive_sync.py`: `assert queued == []` vira a conexão do vizinho **presente** e a
  `disabled` deste teste **ausente**. O controle positivo é obrigatório: um `not in` sozinho
  nasceria verde sobre um tick que não enfileira nada — a frouxidão que a ADR 0035 mediu.
  `ProjectDriveConnection` é única por projeto, e é por isso que o controle positivo é a
  conexão do vizinho.
- `test_authorization.py`: id da própria linha presente, id da do colega ausente,
  `unread_count` em **delta** e `read_at` conferido **por id** no lugar de `marked == 1`.
  O delta preserva a única cobertura que `unread_count` tem no repositório (`app/page.tsx:311`
  do outro lado); apagá-lo deixaria campo publicado e consumido sem teste, que é o defeito da
  ADR 0033 pelo avesso. **Escopar "ao próprio tenant" não resolveria este caso**: a linha
  intrusa é do mesmo tenant, do mesmo projeto e do mesmo usuário. A regra é *a linha que este
  teste criou*.
- `test_onboarding.py`: o digest deste projeto presente, o do vizinho ausente.

O que **não** muda: `sync_due_drive_connections` continua global, e não ganha escopo por
tenant. A varredura é global por desenho; o defeito era da asserção.

## O que foi medido

### Guarda 1 — nenhuma variável de produto alcança uma `Settings` de teste

Envenena ela mesma o ambiente, campo a campo, derivado de `Settings.model_fields` — 103
campos, zero lista à mão. Nasceu vermelha nas **duas** portas:

```
E  AssertionError: 96 de 96 campos de produto atravessaram do ambiente para uma
   `Settings` construída em teste: agent_events_rate_limit=127 (default 120),
   agent_key_lifetime_days=187 (default 180), agent_key_pepper='envenenado' (default ''),
   ai_quota_monthly_cents=20007 (default 20000), … A costura fica em
   `conftest.INHERITED_FROM_THE_ENVIRONMENT`
E  AssertionError: 96 de 96 campos de produto atravessaram de um `.env` do disco para uma
   `Settings` construída em teste: … As fontes são duas (`env_settings` e
   `dotenv_settings`) e a costura precisa filtrar as duas.
```

Mutação **(a)**, apagar a costura: as duas mensagens acima, idênticas — 96 campos.
Mutação **(c)**, devolver `dotenv_settings` sem filtro: só a segunda, e com um `.env` de
verdade no disco os **cinco** de M2 voltam a reprovar.

### Guarda 1b — a allowlist não guarda linha desnecessária

Mutação obrigatória, `CONTACT_QUIET_HOURS_START` na allowlist:

```
E  AssertionError: estes nomes estão em `INHERITED_FROM_THE_ENVIRONMENT` e nenhum bloco
   `env:` do `ci.yml` os passa ao processo de teste: CONTACT_QUIET_HOURS_START. A lista é
   para onde está um serviço, e um serviço que o CI não aponta não é herança — é
   comportamento de produto entrando pela porta de trás.
```

E, com aquela linha, **o defeito literal da 0058 volta**: os cinco de M1 reprovam de novo.
Isto é o que impede a allowlist de virar a porta de trás da própria costura.

Mutação simétrica, apagando `STORAGE_ACCESS_KEY` de `ci.yml:120`:

```
E  AssertionError: estes nomes estão em `INHERITED_FROM_THE_ENVIRONMENT` e nenhum bloco
   `env:` do `ci.yml` os passa ao processo de teste: STORAGE_ACCESS_KEY.
```

### Guarda 1c — completude do envenenador

Sem ela, um campo cujo tipo o envenenador não sabe alterar sai da medição **em silêncio** — o
`.priority` da ADR 0033 na forma que a ADR 0038 nomeou: *a cobertura de um portão é a dos
ramos que a amostra percorre*. Mutação, cegando `_poison_for` para `float`:

```
E  AssertionError: estes campos de `Settings` não entram na medição de isolamento:
   clamav_timeout_seconds, rag_max_distance, rag_offline_max_distance. Ensine `_poison_for`
   a alterar o tipo, ou declare o campo em `CANNOT_BE_POISONED` com o motivo escrito.
```

`CANNOT_BE_POISONED` **está vazia**, e isso é medição e não descuido: os 103 campos são
`str`, `bool`, `int`, `float` e `tuple[str, ...]`, e para os cinco tipos existe valor válido
diferente do default. Nenhum `ValidationError` apareceu. Um campo novo com tipo restrito
(`Literal`, `SecretStr`, enum, URL validada) precisará de linha ali — e enquanto não tiver, a
1c reprova em vez de encolher a medição.

### Guarda 1d — a saída da costura é escrita

Nasceu vermelha sobre a única subclasse existente:

```
E  AssertionError: estas subclasses de `Settings` nomeiam o próprio `env_file` e não estão
   declaradas: FromTemplate (test_homolog_config.py:163). A costura deixa o `dotenv` delas
   passar inteiro — declare em `DECLARES_ITS_OWN_ENV_FILE` por que aquele arquivo é uma
   declaração do teste, e não herança do ambiente.
```

A varredura é por **AST** e não por `Settings.__subclasses__()`: a classe é definida *dentro*
de uma função de teste, então ela só existiria depois daquele teste rodar — e uma guarda cuja
amostra depende da ordem de execução mede o escalonador.

### Guarda 2a — o vizinho barulhento é mesmo barulhento

Controle positivo do próprio fixture: uma organização estrangeira comitada, com conexão de
Drive habilitada, aviso pendente e degrau de onboarding travado. Mutação, calando o vizinho
(conexão pausada, aviso já enviado, convite recente):

```
E  AssertionError: o vizinho barulhento não é encontrado por: alert_stuck_onboarding,
   send_due_whatsapp_notices, sync_due_drive_connections. A fixture parou de fazer barulho,
   e a guarda 2b passou a exigir um parâmetro decorativo.
```

Sem esta metade, `noisy_neighbour` poderia virar uma fixture que varredura nenhuma encontra e
a guarda 2b passaria a exigir um parâmetro decorativo — verde sobre nada.
`run_erasure_requests` é a única varredura declarada em `NOT_REACHED_BY_THE_NEIGHBOUR`, com o
motivo escrito: ela seleciona só pedido de apagamento que alguém **gravou**, e dar um ao
vizinho o apagaria.

E a mutação que devolve `assert queued == []` a `test_drive_sync.py` é a M4 do baseline:

```
E  AssertionError: assert ['44adc759-8f...fe8167646572'] == []
   Left contains one more item: '44adc759-8fa6-43d2-892c-fe8167646572'
```

### Guarda 2b — todo teste que aciona varredura global declara o vizinho

Nasceu vermelha nomeando **cinco** funções, com arquivo e linha:

```
E  AssertionError: teste(s) que acionam uma varredura global sem o vizinho barulhento no
   banco: test_drive_sync.py:591 test_the_beat_tick_only_fans_out_enabled_connections
   (aciona sync_due_drive_connections); test_onboarding.py:689
   test_the_tick_keeps_going_when_one_organization_blows_up (aciona alert_stuck_onboarding);
   test_retention.py:567 test_the_tick_picks_up_a_stranded_request_and_not_a_running_one
   (aciona run_erasure_requests); test_whatsapp.py:620
   test_the_sweep_sends_a_pending_notice_without_a_new_sync (aciona
   send_due_whatsapp_notices); test_whatsapp.py:655
   test_the_sweep_asks_the_clock_once_instead_of_waking_every_project (aciona
   send_due_whatsapp_notices).
```

Mutação obrigatória, tirando `noisy_neighbour` dos parâmetros de um deles: a guarda nomeia a
função e a linha (`test_drive_sync.py:592`).

**A medição que manda no desenho da 2b.** O conjunto de varreduras sai do **AST** de
`worker.py`, e não do `beat_schedule` **avaliado**. Medido:

```
AST       : 5 ['alert_stuck_onboarding', 'purge_expired_data', 'run_erasure_requests',
               'send_due_whatsapp_notices', 'sync_due_drive_connections']
AVALIADO  : 3 ['alert_stuck_onboarding', 'purge_expired_data', 'run_erasure_requests']
PERDIDAS  : ['send_due_whatsapp_notices', 'sync_due_drive_connections']
```

Cada entrada do agendador mora dentro de um `if settings.<flag>`, e `whatsapp_enabled` e
`drive_sync_enabled` são `False` por default. A guarda derivada do agendador avaliado nomeia
**2** violações em vez de 5 — as três que escapam **em verde** incluem
`test_the_beat_tick_only_fans_out_enabled_connections`, que é o defeito que esta fatia existe
para pegar. É a ADR 0038 outra vez, e com uma agravante: a amostra seria a configuração da
máquina que roda a bateria — exatamente a herança que a metade A corta.

### Guarda 3 — a bateria não alcança broker de verdade

Nasceu vermelha antes da fixture existir (`fixture 'published_tasks' not found`). A mutação
obrigatória — a fixture presente, sem interceptar — deixa a guarda vermelha nos **dois**
ambientes, por motivos opostos:

```
# com o worker/redis de pé — a task foi publicada de verdade
E  AssertionError: o enfileiramento não parou na bateria: `celery_app.send_task` não está
   interceptado, e o que este teste publicou foi para o broker de verdade — de onde o
   contêiner `worker`, que fala com o **mesmo banco**, o consome no meio da corrida.
E  assert [] == [('portal_api.notify_pending_created', ('3dfc36d0-…', '91138f11-…'))]

# com redis e worker parados — o `except` de `queue_pending_notification` engoliu a falha
E  assert [] == [('portal_api.notify_pending_created', ('2213a000-…', '60d410a4-…'))]
```

### O critério que distingue a fatia de um conserto de asserção

`pytest apps/api/tests` verde **com o contêiner `worker` de pé** (exit 0) e verde com ele
parado (exit 0). Antes desta fatia, a mesma bateria reprovava dois com o worker de pé.

## Consequências

**Testar comportamento passa a exigir declará-lo.** Um teste que precise de
`whatsapp_enabled=True` continua escrevendo `Settings(whatsapp_enabled=True)` — `init_settings`
passa inteiro, e é essa a forma certa. O que deixa de funcionar é exportar a variável e
esperar que o teste a leia; e isso é o objetivo, não um efeito colateral.

**`alerts.md` fica intocado, e é afirmação e não omissão.** Nenhum evento de log novo é
emitido por esta fatia, e a guarda de eventos é bidirecional desde a ADR 0034: uma linha de
runbook sem emissor reprovaria.

**`alembic check`, `python -m portal_api.openapi --write` e `npm run audit` não se aplicam** —
a fatia não toca modelo, migração, rota nem dependência. Ficam declarados em vez de rodados
por ritual, que é a disciplina da ADR 0023 sobre o que um portão verde afirma.

**O que fica declarado, e não corrigido.**

- **Os cinquenta sítios `Settings(` continuam onde estão.** A costura os cobre sem migrá-los
  para uma fábrica, e migrar seria mexer em nove arquivos para não mudar comportamento
  nenhum.
- **O Postgres de desenvolvimento não é limpo.** O objetivo é um portão que não dependa do
  estado do banco; limpar o banco entregaria o verde e não o portão.
- **`test_backup_restore.py` ficou fora desta fatia**, no mesmo recorte que o job
  `api-quality` do CI usa (`--ignore`): ele tem job próprio, `backup-restore`, que existe
  justamente porque exige o que o resto da bateria não exige — MinIO, as quatro senhas de
  papel e um cliente do Postgres tão novo quanto o servidor. **As três `STORAGE_*` continuam
  na allowlist por causa dele**, com o motivo escrito: são "onde está um serviço", e tirá-las
  quebraria aquele job sem nada ficar vermelho aqui — que é exatamente a forma de defeito que
  a ADR 0019 pagou para descobrir.

**E o que esta fatia não é.** O portal está fora do ar desde 13/08/2026 (ADR 0053). Isto
devolve significado a um portão de CI e retifica um diagnóstico escrito; nada aqui foi
observado servindo cliente, e nenhum comportamento de produto mudou.
