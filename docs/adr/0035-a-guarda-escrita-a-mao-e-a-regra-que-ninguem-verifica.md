# ADR 0035 — A guarda escrita à mão, e a regra que ninguém verifica

**Status:** aceita — 06/08/2026
**Contexto:** Fase 6. Sexta repetição do padrão das ADRs 0024/0026/0027/0033/0034, e desta vez o
alvo é o mecanismo inteiro: **as guardas que carregam as regras inegociáveis são, elas próprias,
listas digitadas** — o defeito que a ADR 0033 nomeou, sobrevivendo em quatro lugares.

## Contexto

A ADR 0033 encontrou uma guarda de CI que parecia cobrir o contrato e percorria oito nomes
escritos à mão num contrato de 56 esquemas. A ADR 0034 encontrou o mesmo formato na telemetria e
acrescentou o argumento que sustenta esta fatia: um conserto manual num arquivo que ninguém
verifica *"é uma afirmação sobre o dia em que foi escrito"*.

A pergunta que faltava fazer era sobre as **próprias regras**. O `AGENTS.md` tem princípios
numerados que ADRs, FDDs e docstrings de teste citam por número — vinte citações, uma delas dentro
do artefato publicado `docs/api/openapi.json`. Contá-las revelou os cinco defeitos abaixo.

## Os defeitos, todos medidos

### 1. A regra 2 era provada por seis sentinelas contra dezesseis segredos

`test_eval_no_secret_ever_reaches_the_model` é a **única** asserção do repositório dedicada a
"nunca envie segredos ao modelo de IA", e o próprio docstring dizia ser *"a regra 2 do `AGENTS.md`
como contra-asserção, e não como intenção"*. Ela fixava seis valores à mão.

`Settings` declara 85 campos. **Dezesseis** carregam segredo, e o segundo casador é o que mostra
por que uma lista digitada não bastava: doze batem `_SECRET_HINTS` pelo nome, e **quatro escondem
a credencial dentro do valor** — as `database_*_url` são DSN completo
(`postgresql+psycopg://portal_app:…@…`), e nenhuma delas casa `_SECRET_HINTS`, porque o casador do
log pergunta pelo *nome* do campo, que no log é a chave do `extra` e ali está certo.

Ficavam de fora, entre outros, `drive_token_encryption_key_previous` — a chave **anterior** da
rotação, que abre todo ciphertext de refresh token ainda não resselado (ADR 0016) — e a senha do
`portal_admin`, a credencial que escreve `membership` (ADR 0011).

**E isso foi medido, não deduzido.** Com um vazamento injetado em `ai/service.py`
(`question + settings.database_admin_url`), a guarda nova reprova nomeando `database_admin_url`; a
antiga, com as mesmas seis sentinelas, **passa verde** — e uma asserção auxiliar confirmou que o
DSN estava de fato no corpo do pedido.

### 2. A regra 6 não tinha guarda, e já havia sido quebrada em silêncio

"Caso negativo de permissão para qualquer endpoint ou busca nova" é a disciplina mais invocada do
repositório e sustenta as duas primeiras linhas do `threat-model.md`. Toda outra inegociável tem
portão derivado da fonte — `test_rls_isolation.py` consulta `pg_class`/`pg_policies`, o contrato
tem quatro propriedades sobre *toda* rota, a telemetria varre a AST. A regra 6 eram **30 funções
escritas à mão contra 46 pares rota+método publicados**, e nada perguntava se a lista estava
inteira.

`GET` e `PUT /api/v1/admin/organizations/{organization_id}/ai-quota` — que definem o **teto mensal
de gasto de IA** de uma organização — não tinham teste de espécie alguma. As catorze asserções de
`test_ai_quota.py` exercitam o razão e o 429, e **todas** fixam o teto escrevendo a linha direto no
banco pela fixture `limit_of`: o caminho que uma pessoa percorre — a rota, com tela desde a ADR
0027 — nunca havia sido tocado.

A guarda nasceu vermelha com **cinco** pares, e o mais caro não era o teto:
`GET /api/v1/projects/{project_id}/results` é a **única** rota de cliente que recebe um
identificador de projeto no caminho, ou seja, o caso literal da regra 1, e não havia teste nenhum a
exercitando. Junto vieram o histórico do expurgo e o chat — este o irmão exato de
`test_notifications_require_a_project` e `test_search_requires_a_project`, que existiam.

### 3. Um pulo escapou da regra do `skip_unless_ci`

`test_backup_restore.py:432` usava `pytest.skip` cru — o único do arquivo. As outras três
checagens da mesma variável de ambiente usam `skip_unless_ci`, e a vizinha traz o comentário que
nomeia o problema: *"Este era o pulo mais caro do repositório: silencioso, em toda execução do CI
(…). Hoje ele falha no CI (ADR 0020)."*

O que escapou é a decisão 6 da ADR 0019 — *restaurar bytes corrompidos é pior que falhar*. Se o
`env:` do job perder `POSTGRES_PASSWORD`, os vizinhos ficam vermelhos e justamente este some em
verde.

### 4. A guarda bidirecional de eventos só enxergava metade do repositório

`test_telemetry.py` fixava `SOURCE_ROOT` no pacote Python. O BFF tem logger estruturado próprio
(`app/lib/log.ts`), escreve no mesmo formato e emite quatro eventos — `api.rejected`,
`api.unreachable`, `api.failed` e `web.request_error` — e **nenhum tinha linha em runbook nenhum**.
Era a mesma divergência que a ADR 0034 acabara de fechar do outro lado, e a guarda dela não podia
vê-la.

Havia inclusive a evidência dentro da própria guarda: um `elsewhere = {"web.request_error"}`
declarando que aquele evento era "emitido pelo BFF, não por este código". A exceção descrevia o
ponto cego em vez de fechá-lo — a mesma assimetria do `health.broker_unavailable`.

### 5. A numeração que todo mundo cita não existia

`AGENTS.md` tinha **cinco** princípios numerados. `CLAUDE.md` publicava **seis** "from
`AGENTS.md`" — renumerados: promovia uma *convenção* ("o frontend não decide autorização") e um
*item de checklist de pull request* ("caso negativo de permissão") a princípio, e **descartava** o
princípio 5, o dos segredos em commits, fixtures, logs e documentação.

A numeração que circulava era a da cópia. Seis lugares citavam uma "regra 6" que não existia com
esse número, e "regra 5" queria dizer coisas diferentes em `docs/adr/0018` e `docs/adr/0025`.

## Decisão

### 1. O eval da regra 2 deriva de `Settings`, com dois casadores

`_SECRET_HINTS` entra por `import` de `telemetry.py` — o precedente literal é
`test_openapi_contract.py`, e recopiar garantiria que uma das cópias envelhecesse sozinha, que é o
argumento que moveu `captured()` para o `conftest.py` na ADR 0028. O segundo casador é sobre o
**valor**, e existe porque o primeiro não bastava: um DSN esconde a senha onde o nome do campo não
denuncia.

Os falsos positivos viraram allowlist com motivo e guarda de obsolescência, e cinco dos seis são a
mesma piada: **"keycloak" contém "key"**, então o casador pega o realm e os dois client ids junto
com o client secret que de fato importa.

`voyage_api_key` com sentinela escolheria o `VoyageEmbedder` e abriria rede; o embedder é fixado
offline no teste e a sentinela **continua atravessando** o serviço — o caminho existe, e o que se
prova é que ele não termina no pedido.

### 2. A regra 6 vira propriedade do contrato: quem promete 404, prova o 404

A pergunta sai do artefato publicado, não de quem lembrou. E a escolha do predicado é o que
dispensa allowlist: as superfícies que legitimamente não negam por tenant — as duas sondas, o
webhook e as duas rotas `/me` sem identificador — **não declaram 404**, então se isentam sozinhas.
Sobrou uma única exceção escrita, `GET /api/v1/admin/organizations`, que responde 200 com lista
vazia por desenho (ADR 0027) e herda o 404 do `CLIENT_ERRORS`.

**O elo é entre o 404 e a resposta daquela chamada, e isso foi medido.** A primeira versão ligava
"a função chama a rota" a "há um 404 em algum lugar do corpo", e com ela `POST /api/v1/chat`
aparecia **coberto** — por `test_rating_a_colleagues_answer_is_404`, onde o chat só monta a
conversa e o 404 é da rota de feedback. A guarda nasceria verde sobre uma rota sem negativo, que é
exatamente o defeito da ADR 0033 repetido dentro da correção dele.

A varredura segue os auxiliares de módulo, e isso também não é refinamento: `test_agent_events.py`
manda a requisição por um `_post()` de três linhas, e sem seguir helpers a guarda concluiria que a
rota de eventos — a única com credencial própria — não tem negativo nenhum.

**Prova de que casa de verdade:** neutralizado o `assert ... == 404` do negativo de retenção, a
guarda reprova nomeando `PUT /api/v1/admin/organizations/{organization_id}/retention` — e **só** o
`PUT`, porque o `GET` continua provado por outro teste. A precisão é o ponto.

### 3. `skip_unless_ci` no teste do backup adulterado

Uma linha, e o `skip_unless_ci` já estava importado.

### 4. A guarda de eventos passa a enxergar o BFF

Varredura por expressão regular — não AST, porque é TypeScript — sobre os `.ts` da raiz e
`app/`+`components/`, exigindo primeiro argumento literal que case `EVENT_NAME`.

**Numa guarda só, e não num teste node ao lado**, porque o `alerts.md` é um arquivo só: duas
guardas sobre o mesmo arquivo divergem, que é literalmente o defeito que esta seção existe para
impedir. O precedente de teste Python lendo artefato de fora do pacote é o
`test_seed_matches_realm.py`.

Os quatro eventos ganharam linha no `alerts.md`, e o `elsewhere` saiu.

### 5. Uma numeração só, com guarda

`AGENTS.md` é a fonte e ganha o sexto princípio — o caso negativo de permissão, que seis lugares já
citavam como "regra 6". Os cinco primeiros ficam onde estavam: **renumerar quebraria as citações
corretas** de "regra 3" e "regra 5". `CLAUDE.md` passa a espelhar os seis, com o princípio de
segredos de volta.

`test_agents_rules.py` afirma que as duas listas são a mesma e que toda citação `regra N` resolve.
Ela lê os arquivos **menos as notas históricas**, pela razão da ADR 0034: sem isso cobraria que o
repositório apagasse o registro do próprio erro.

**A guarda achou mais do que o levantamento manual.** A contagem à mão encontrara cinco citações
penduradas; ela encontrou seis, incluindo `test_main.py`.

`docs/adr/0025` recebeu nota em vez de reescrita — o argumento dele continua de pé, só o número
está trocado.

### 6. As allowlists do contrato vencem por data

`NOT_CONSUMED` e `NOT_CALLED` passam de `string` para `{reason, review_by}`. Até aqui as duas
entradas com prazo o traziam como **prosa dentro do motivo** ("Rever em 02/2027") e nada lia
aquela data, enquanto o `advisories.json` — citado como precedente na própria decisão que as
criou — reprova em `review_by < today`.

E a asserção de obsolescência passa a cobrir `NOT_CALLED`, que ficara de fora: uma rota que
ganhasse chamador mantinha a isenção para sempre.

## Consequências

- **As cinco guardas nasceram vermelhas, e há prova de cada uma.** Cinco pares rota+método sem
  negativo; onze segredos fora do eval; quatro eventos do BFF órfãos; seis citações penduradas;
  duas listas de tamanhos diferentes.
- **Duas das guardas encontraram o que a investigação não viu** — `test_main.py` nas citações, e
  `GET /projects/{id}/results` e `POST /chat` nos negativos —, repetindo o que a ADR 0034 observou:
  a máquina pergunta por todos, e não pelos que alguém lembrou.
- **A fronteira já estava certa; o que faltava era a prova.** Os cinco casos negativos novos
  passaram de primeira, inclusive os do teto de IA. Isso não desvaloriza a fatia: significa que o
  repositório passou meses a um refactor de distância de um defeito que nada acusaria.
- **A regra 4 continua sem guarda automática**, e é a única. "Migrações são aditivas" não é
  verificável por `alembic check` — nada impede um `op.drop_column` dentro de um `upgrade()` — e
  "exige ADR/RFC" é julgamento. Fica declarado em vez de silencioso.
- **Sem migração, sem rota nova, sem mudança de contrato.** `alembic check` limpo e
  `docs/api/openapi.json` byte a byte igual.
- **Custo:** a guarda da regra 6 é heurística de ligação, como o corpus da ADR 0033. Um teste
  escrito de forma muito diferente das que existem hoje pode não ser reconhecido — e o desfecho
  disso é uma reprovação pedindo um teste que já existe, nunca um verde sobre rota descoberta.

## Alternativas recusadas

**Exigir que o negativo viva em `test_authorization.py`.** Simples de verificar e errado: os
negativos de administração moram em `test_admin_endpoints.py` ao lado do que provam, e os de
credencial de agente em `test_agent_events.py`. A regra é sobre existir a prova, não sobre onde ela
mora.

**Marcar cada teste negativo com um decorator que nomeie a rota.** Explícito e imune a heurística,
ao custo de anotar trinta testes e de criar uma segunda fonte de verdade que envelhece — a rota
mudaria de caminho e o marcador continuaria dizendo o antigo. É o formato que esta ADR combate.

**Uma allowlist escrita à mão para as rotas sem negativo**, em vez de derivar a isenção do `404` no
contrato. Teria funcionado hoje e voltado a ser uma lista digitada amanhã, com cinco entradas cujo
motivo o próprio contrato já declara.

**Um teste node separado para os eventos do BFF.** Fica no ecossistema certo e cria duas guardas
lendo o mesmo `alerts.md` — que é a divergência que a ADR 0034 documentou.

**Renumerar o `AGENTS.md` para caber a convenção "o frontend não decide autorização" como regra
5.** Alinharia com a cópia que circulava e invalidaria em silêncio as três citações corretas de
"regra 5", além das de "regra 3". A cópia estava errada; corrigir a cópia custa menos que reescrever
o que a citou certo.

**Apagar as citações erradas em vez de dar-lhes nota.** O registro do erro é o que impede a
sétima repetição — decisão 3 da ADR 0034, aplicada a si mesma.
