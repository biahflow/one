# ADR 0034 — O evento nomeado, e o runbook que o conhece

**Status:** aceita — 06/08/2026
**Contexto:** Fase 6. Quinta repetição do padrão das ADRs 0024/0026/0027/0033 — e desta vez o
argumento não é que a promessa foi quebrada, é que **ela já tinha sido consertada à mão e voltou
a quebrar**.

## Contexto

A ADR 0018 entregou `trace_id`, `JsonFormatter` e o `alerts.md`, e existiu porque três runbooks
mandavam ler coisas que o código não produzia. A ADR 0028 encontrou mais uma — o `alerts.md`
citava `drive.rejected`, que o código **nunca emitiu** — e consertou escrevendo a linha certa.

O conserto não deixou guarda. Dois dias depois o mesmo arquivo divergiu de novo, agora no sentido
oposto: **doze eventos que o código emite e o runbook não conhece**. Um conserto manual num
arquivo que ninguém verifica é uma afirmação sobre o dia em que foi escrito.

## Os quatro defeitos, todos medidos

### 1. O runbook mandava vigiar um estado que não pode existir

A linha dizia: *"em produção com `CLAMAV_HOST` configurado, `skipped` sustentado é alerta:
significa que o scanner configurado não está respondendo"*.

`get_scanner` só devolve `OfflineScanner` quando `clamav_host` está **vazio**. Com ClamAV
configurado quem responde é o `ClamavScanner`, e ele retorna `clean`, `infected` ou `error` —
**nunca** `skipped`. Quem seguisse a instrução vigiava um contador estruturalmente pinado em zero
exatamente enquanto o antivírus caía. E `error`, o estado que de fato significa isso, não tinha
linha em runbook nenhum.

Pior: o único sinal de clamd fora era `logger.warning("clamd indisponível em %s:%s: %s", …)` — o
defeito 2, no lugar onde ele custa mais caro.

### 2. Dez sítios emitiam um `event` diferente por ocorrência

`JsonFormatter` põe `record.getMessage()` — a mensagem **já interpolada** — no campo `event`, e o
`alerts.md` abre dizendo que *"cada linha é um evento nomeado (…) a regra é sempre a mesma
consulta: filtrar por `event` e contar dentro de uma janela"*. As duas frases não podem estar
certas: `"Objeto %s não removido do storage"` produz um `event` novo a cada chave, e nenhum limiar
se aplica a um valor que nunca se repete.

Medido por AST: **50 eventos nomeados contra 13 em prosa, 10 delas interpolando**. E o
`document-ingestion-failure.md` mandava procurar `Objeto … não removido do storage` — a única
instrução de runbook do repositório que só se cumpria por substring, enquanto todas as outras
mandam filtrar por `event`.

O docstring do próprio `JsonFormatter` **abençoava** a prosa (*"e também quando é prosa — quem
consome filtra por `event` de qualquer jeito"*). Era a frase que permitiu os dez sítios, e ela
saiu.

### 3. "Anomalias de autorização" era indicador sem emissor

`observability.md` o lista desde a Fase 1. `access.py` — o arquivo onde a decisão acontece — tinha
**quatro** caminhos de negação e **zero** chamadas a logger; as 23 negações de `main.py`/`admin.py`
só traduzem `None` em 404.

As duas primeiras linhas do `threat-model.md` — "cliente acessa outro projeto" e "IDOR em
arquivo/documento" — descrevem um chamador **autenticado** passeando por ids alheios. Isso
produzia apenas `http.request` com `status: 404` e o *template* da rota, sem ator: não havia como
responder *"quantas negações o sujeito X disparou em cinco minutos"*, que é a única pergunta que
separa um link velho de uma enumeração. `auth.rejected` não cobre — é autenticação (401), e o
`incident-response.md` já manda para ele quem suspeita de sondagem de **sessão**.

### 4. Doze eventos emitidos e ausentes do runbook

Dois deles controles de segurança, e **dois só apareceram porque a guarda os encontrou**:

- **`document.infected_object_kept`** — malware confirmado que **não saiu do bucket**. O
  `alerts.md` acorda alguém em `document.infected` a "qualquer ocorrência" e o caso estritamente
  pior era anônimo.
- **`drive.scope_refused`** — o controle "OAuth Drive excessivo" do threat-model *disparando*: o
  Google concedeu escopo diferente de `drive.readonly` e a conexão foi recusada.
- **`http.failed`** — toda exceção que atravessa a API. O 500 era o único desfecho do produto sem
  limiar escrito.
- **`health.broker_unavailable`** — irmão exato do `health.database_unavailable`, que tem linha
  com limiar. Mesmo endpoint, mesmo 503, e só metade acordava alguém.

## Decisão

### 1. `authz.denied`, em `access.py`, com dois `reason`

Onde a decisão acontece, e não nas 23 rotas. Os motivos são fatos operacionais distintos:
`not_a_member` (a policy não devolveu a linha — id inexistente e id de outro tenant são
indistinguíveis daqui, e é exatamente esse o sinal de acesso cruzado) e `role_insufficient` (é
membro e o papel não basta — escalada **dentro** do tenant, outra investigação).

`default_project`, `visible_projects` e `administered_organizations` **não** emitem: devolver vazio
ali é "sem projeto atribuído", estado normal que a tela trata.

O campo de identidade é `subject_prefix`, reusando o precedente literal do `chat_limit.py` — *o
bastante para saber quem está em laço, sem o log virar um rastro estável por pessoa*.

**A resposta ao chamador não muda**, e o teste afirma isso: segue o mesmo 404 opaco de um id
inexistente. Uma fatia que distinguisse "não é seu" de "não existe" teria criado o oráculo que a
ADR 0010 evita — o sinal é para dentro.

### 2. A mensagem é o nome; o detalhe vai em `extra`

Regra que `ai/service.py` já enunciava no código e que agora vale para todo o pacote, com guarda
por AST. A **allowlist** é para os comandos de operação (`seed`, `preflight`, `backup`, o bootstrap
da ADR 0025): ali o leitor é uma pessoa no terminal, não um coletor, e exigir
`familia.acontecimento` pioraria a saída para quem a lê.

### 3. A guarda é bidirecional, porque as duas direções já falharam

Todo evento emitido tem linha no `alerts.md`; todo evento que o `alerts.md` nomeia é emitido. A
segunda é o defeito da ADR 0028; a primeira é o que divergiu depois dela.

**Ela lê o arquivo menos as notas históricas, e isso foi medido.** O `alerts.md` cita
`drive.rejected` dentro da própria nota que registra a correção da ADR 0028. Uma guarda ingênua
reprovaria a nota — ou seja, cobraria que o repositório apagasse o registro do próprio erro, que é
justamente a memória que dá valor a estas ADRs. A marcação `*Corrigido em …*` já existia como
convenção de escrita; aqui ela vira executável.

Dois falsos positivos foram medidos e viraram lista com motivo: nomes de arquivo
(`observability.md` casa `familia.acontecimento` perfeitamente) e `drive.readonly`, que é o
**escopo** do consentimento e não um evento.

### 4. Duas allowlists, e as duas vencem

`PROSE_IS_FINE` (módulos de operação) e `NOT_AN_ALERT` (eventos de curso normal, que não merecem
limiar) seguem a regra do `advisories.json`: uma linha que deixou de ser necessária **reprova**.
Sem isso viram sedimento e a guarda afrouxa sozinha.

## Consequências

- **As três guardas nasceram vermelhas** — oito sítios de prosa (dois dos dez estavam em módulos
  de operação e viraram allowlist) e doze eventos órfãos.
- **A guarda achou mais do que a investigação que a motivou.** `http.failed` e
  `health.broker_unavailable` não estavam no levantamento manual: apareceram porque a máquina
  perguntou por todos, e não pelos que alguém lembrou.
- **O antivírus caindo em produção deixou de ser invisível**, que era o defeito mais caro do
  conjunto: a instrução existia, era executável, e apontava para o lugar errado.
- **A primeira linha do threat-model ganhou verificação**, e ela afirma as duas metades — o evento
  sai e a resposta continua opaca.
- **Custo:** `authz.denied` é uma linha de log por negação no caminho de requisição. É `warning`,
  e o `alerts.md` a coloca com limiar por taxa e por pessoa, não em "qualquer ocorrência",
  justamente porque a negação isolada é rotina.
- **Sem migração, sem coluna, sem rota nova.**

## Alternativas recusadas

**Emitir a negação nas rotas, junto do `raise`.** São 23 lugares e a decisão não é tomada em
nenhum deles — seria a mesma dispersão que `notifications.py` e `conversations.py` existem para
evitar, com o agravante de que esquecer um lugar produz um ponto cego silencioso.

**Um `reason` só.** Apagaria a distinção exatamente onde ela decide o que fazer: acesso cruzado e
escalada interna levam a investigações diferentes.

**Registrar o `sub` inteiro.** Daria correlação perfeita por pessoa e transformaria o log num
rastro estável de comportamento. O prefixo responde "quem está em laço" — que é a pergunta do
runbook — e o `chat_limit.py` já tinha decidido isso.

**Deixar a guarda ler o arquivo inteiro, incluindo as notas históricas.** Simples, e cobraria que
a nota da ADR 0028 fosse apagada. O registro do erro é o que impede a terceira repetição.

**Um campo `event` separado da mensagem no formatter**, mantendo a prosa. Resolve o sintoma e cria
a dúvida que o docstring original já temia — qual dos dois ler — enquanto deixa dez sítios sem
nome. A regra "a mensagem é o nome" é mais barata e já era a convenção de 50 dos 63 sítios.
