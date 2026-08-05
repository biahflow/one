# Observabilidade

Cada requisição recebe `trace_id`; jobs propagam o mesmo identificador. *(Pendente: o
`trace_id` está desenhado e ainda não implementado — é item da Fase 5, junto de alertas e
backup testado.)* Telemetria não inclui texto bruto de documentos ou segredos.

Indicadores: latência e erro de API, fila, sincronização Drive, indexação, falha de conectores, custo/latência de IA, cobertura de citações, taxa de lacuna, pendências abertas/resolvidas e anomalias de autorização.

O resultado de cada sincronização do Drive vive na própria linha da conexão (`last_sync_at`, `last_sync_error`, `last_sync_stats`), e não só no log: é o que faz "por que a IA não sabe disso?" ser respondível pela tela. `rejected > 0` é o contador da fronteira — atalhos e arquivos de fora da pasta autorizada — e deve ser lido como o controle funcionando, não como erro.

O estado da varredura vive na linha do documento (`scan_state`, `scan_error`, `scanned_at`) pela
mesma razão do `last_sync_error` da conexão do Drive: "por que este arquivo não responde no
chat?" precisa ser respondível pela tela, não só pelo log. `infected > 0` é o controle
funcionando — leia como o `rejected` do conector.

A poda e o expurgo (ADR 0017) reportam contagem por tabela: a poda no retorno da task, o expurgo
na coluna `removed` do próprio pedido, que sobrevive ao apagamento. Nunca amostra do conteúdo.
