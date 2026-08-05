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

Indicadores: latência e erro de API, fila, sincronização Drive, indexação, falha de conectores, custo/latência de IA, cobertura de citações, taxa de lacuna, pendências abertas/resolvidas e anomalias de autorização.

Os quatro indicadores de IA dessa lista saem de um evento só: `chat.answered` (ADR 0021), com
`prompt_version`, `responder`, `model`, `confidence` e a contagem de citações por turno — de
onde vêm cobertura de citações e taxa de lacuna por versão de prompt, que é o que torna uma
regressão de prompt visível em vez de anedótica. E o mesmo trio está gravado em
`conversation_message`, pela razão do `last_sync_error` da conexão do Drive e do `scan_state` do
documento: o log responde "está acontecendo agora" e some com a retenção; a coluna responde
"aconteceu na terça passada", que é quando alguém pergunta.

O resultado de cada sincronização do Drive vive na própria linha da conexão (`last_sync_at`, `last_sync_error`, `last_sync_stats`), e não só no log: é o que faz "por que a IA não sabe disso?" ser respondível pela tela. `rejected > 0` é o contador da fronteira — atalhos e arquivos de fora da pasta autorizada — e deve ser lido como o controle funcionando, não como erro.

O estado da varredura vive na linha do documento (`scan_state`, `scan_error`, `scanned_at`) pela
mesma razão do `last_sync_error` da conexão do Drive: "por que este arquivo não responde no
chat?" precisa ser respondível pela tela, não só pelo log. `infected > 0` é o controle
funcionando — leia como o `rejected` do conector.

A poda e o expurgo (ADR 0017) reportam contagem por tabela: a poda no retorno da task, o expurgo
na coluna `removed` do próprio pedido, que sobrevive ao apagamento. Nunca amostra do conteúdo.
