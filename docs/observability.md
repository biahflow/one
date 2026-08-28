# Observabilidade

Cada requisição recebe `trace_id`; jobs propagam o mesmo identificador (ADR 0018). Telemetria
não inclui texto bruto de documentos ou segredos.

O id nasce no BFF (`app/lib/trace.ts`), viaja em `X-Request-ID` — que a API ecoa em toda
resposta — e atravessa a fila como **header da mensagem**, nunca como argumento de task. Uma
task nascida do beat cunha o próprio e o marca `root=beat`. O mesmo id é carimbado em
`audit_log.data`, e é isso que faz a primeira linha do `incident-response.md` ser executável:
da ação registrada se chega ao log, e do log se volta à ação.

O log é uma linha JSON por evento (`LOG_FORMAT=text` dá o formato legível do dia a dia, com os
mesmos campos). O formatter promove os campos de `extra` e **redige** os que parecem segredo,
com `key_prefix` numa allowlist — sem ela o runbook da API de eventos voltaria a mandar ler um
campo que não sai. A lista de eventos, com limiar e destino, está em `runbooks/alerts.md`.

Indicadores: latência e erro de API, fila, sincronização Drive, indexação, falha de conectores, custo/latência de IA, cobertura de citações, taxa de lacuna, pendências abertas/resolvidas, anomalias de autorização e clientes travados no funil de onboarding.

*O último entrou com emissor no mesmo commit (ADR 0040), que é a lição da linha abaixo: `onboarding.client_stuck` sai uma vez por organização e por degrau, e a leitura por trás dele mora em `/admin/funnel`. Ele é o único indicador desta lista que **não** descreve a saúde do sistema — descreve a relação do cliente com o produto, e por isso a ação dele é um telefonema, não um deploy.*

**"Anomalias de autorização" saiu por último, e até a ADR 0034 não existia.** Esta
página listava o indicador desde a Fase 1 enquanto `access.py` — o arquivo onde a
decisão acontece — não tinha uma linha de log, e as vinte e três negações de
`main.py`/`admin.py` só traduziam `None` em 404. Um cliente autenticado percorrendo
ids alheios produzia apenas `http.request` com `status: 404` e o *template* da rota,
sem ator: não havia como responder "quantas negações o sujeito X disparou em cinco
minutos", que é a diferença entre um link velho e uma enumeração — e é exatamente o
que as duas primeiras linhas do `threat-model.md` descrevem. Hoje o indicador é
`authz.denied`, com `subject_prefix` (o prefixo, nunca o `sub` inteiro, pela razão do
`chat_limit.py`) e um `reason` que separa acesso cruzado (`not_a_member`) de escalada
dentro do próprio tenant (`role_insufficient`). **A resposta ao chamador não mudou**:
segue o mesmo 404 opaco, porque o sinal é para dentro (ADR 0010).

**E o `event` é sempre um nome estável** — `familia.acontecimento`, com o detalhe em
`extra`. Não é convenção de estilo: o `JsonFormatter` põe a mensagem **já
interpolada** em `event`, então um `logger.warning("Objeto %s não removido", key)`
produz um valor diferente por ocorrência, e o limiar que `runbooks/alerts.md` promete
deixa de ser aplicável. Dez sítios faziam isso até a ADR 0034 — um deles era o único
sinal de que o antivírus tinha caído. `test_telemetry.py` varre o AST e reprova a
volta; a exceção é o punhado de comandos de operação (`seed`, `preflight`, `backup`,
o bootstrap da ADR 0025), cujo leitor é uma pessoa no terminal e não um coletor.

Os indicadores de IA dessa lista saem de um evento só: `chat.answered` (ADR 0021), com
`prompt_version`, `responder`, `model`, `confidence` e a contagem de citações por turno — de
onde vêm cobertura de citações e taxa de lacuna por versão de prompt, que é o que torna uma
regressão de prompt visível em vez de anedótica.

**Custo saiu junto, e até a ADR 0022 não existia.** Esta página listava "custo/latência de IA"
entre os indicadores enquanto o `response.usage` que a SDK devolve em toda resposta era
simplesmente descartado — nenhuma coluna, nenhum evento, nenhuma setting de token ou gasto. Hoje
`chat.answered` carrega `input_tokens` e `output_tokens` (e os dois estão na allowlist do
formatter, porque contêm "token" sem serem um), e a latência é o `duration_ms` de `http.request`.
O par log/coluna é o de sempre: o evento responde "quanto está saindo agora", `ai_usage_event`
responde "quanto esta organização gastou no mês" — e os dois se reconciliam, o que importa
porque o razão vive na transação do turno e um turno revertido não cobra.

O dinheiro **não** é um indicador gravado: ele nasce na leitura, pelo preço vigente no dia da
chamada (`ai/quota.py`), pela razão de `results.py` — reajustar o preço do modelo hoje não pode
reprecificar março. Chamada cujo modelo não tem preço vigente **declara lacuna**
(`ai_quota.price_missing`) em vez de contar zero.

E o mesmo trio está gravado em
`conversation_message`, pela razão do `last_sync_error` da conexão do Drive e do `scan_state` do
documento: o log responde "está acontecendo agora" e some com a retenção; a coluna responde
"aconteceu na terça passada", que é quando alguém pergunta.

A busca emite `search.performed` com `hits`, `kinds`, `term_length` e `duration_ms` — e **nunca
o termo** (ADR 0024). Ele é conteúdo do cliente, como o texto do documento, e o comprimento já
explica uma lista vazia sem gravar o que a pessoa procurava. Pela mesma razão a busca não grava
`audit_log`: o download é auditável porque tira o arquivo do portal, procurar é ler o que já
está nas abas, e uma linha por tecla afogaria a trilha que o `incident-response.md` manda ler.

O resultado de cada sincronização do Drive vive na própria linha da conexão (`last_sync_at`, `last_sync_error`, `last_sync_stats`), e não só no log: é o que faz "por que a IA não sabe disso?" ser respondível pela tela. `rejected > 0` é o contador da fronteira — atalhos e arquivos de fora da pasta autorizada — e deve ser lido como o controle funcionando, não como erro.

O estado da varredura vive na linha do documento (`scan_state`, `scan_error`, `scanned_at`) pela
mesma razão do `last_sync_error` da conexão do Drive: "por que este arquivo não responde no
chat?" precisa ser respondível pela tela, não só pelo log. `infected > 0` é o controle
funcionando — leia como o `rejected` do conector.

A poda e o expurgo (ADR 0017) reportam contagem por tabela: a poda no retorno da task, o expurgo
na coluna `removed` do próprio pedido, que sobrevive ao apagamento. Nunca amostra do conteúdo.
