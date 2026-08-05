# Runbook — Falha do provedor de IA

Desabilitar novas respostas, manter documentos e chat histórico disponíveis e avisar que a
resposta contextual está temporariamente indisponível. Não usar um provedor alternativo sem
revisão de dados e contrato.

## Telemetria de falha (ADR 0018)

O provedor entra por dois adaptadores, e eles falham em lugares diferentes:

```bash
docker compose logs worker | grep '"event":"embedding.failed"'   # indexação
docker compose logs api    | grep '"event":"http.failed"'        # resposta do chat
```

`embedding.failed` traz o `document_id`: o documento fica `failed` e **não entra no índice**,
então o chat passa a declarar a lacuna para perguntas que dependiam dele — comportamento
correto, por motivo errado. O limiar está em `alerts.md` (5 em 1 h).

Vale lembrar o que **não** é falha do provedor: sem `ANTHROPIC_API_KEY` ou `VOYAGE_API_KEY` o
portal usa o respondedor e o embedder offline determinísticos (ADRs 0007 e 0014), sem erro
nenhum no log. Uma stack que "não está citando" com as chaves vazias está funcionando como
desenhado.
