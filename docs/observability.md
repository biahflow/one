# Observabilidade

Cada requisição recebe `trace_id`; jobs propagam o mesmo identificador. Telemetria não inclui texto bruto de documentos ou segredos.

Indicadores: latência e erro de API, fila, sincronização Drive, indexação, falha de conectores, custo/latência de IA, cobertura de citações, taxa de lacuna, pendências abertas/resolvidas e anomalias de autorização.

O resultado de cada sincronização do Drive vive na própria linha da conexão (`last_sync_at`, `last_sync_error`, `last_sync_stats`), e não só no log: é o que faz "por que a IA não sabe disso?" ser respondível pela tela. `rejected > 0` é o contador da fronteira — atalhos e arquivos de fora da pasta autorizada — e deve ser lido como o controle funcionando, não como erro.
