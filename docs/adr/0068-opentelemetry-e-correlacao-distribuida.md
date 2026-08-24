# ADR 0068 — OpenTelemetry e correlação distribuída no One

**Status:** Accepted  
**Data:** 2026-08-24

## Contexto

One já propaga um `trace_id` próprio entre BFF, API, fila, worker e auditoria. O novo padrão transversal da Biahflow passa a ser OpenTelemetry com W3C Trace Context, mantendo vendor neutrality e correlação entre Pulse, BiahflowOS, One, integrações e agentes.

## Decisão

- Instrumentar progressivamente BFF, FastAPI, Celery/workers, acesso a banco e integrações com OpenTelemetry.
- Propagar `traceparent`, `tracestate` e `baggage` em HTTP e mensageria quando suportado.
- OpenTelemetry Collector é a camada de coleta/processamento/exportação.
- Grafana Cloud é o backend inicial para metrics/logs/traces.
- O `trace_id`/`X-Request-ID` atual pode permanecer durante migração e como identificador amigável, desde que não concorra com o trace distribuído.
- Eventos/auditoria relevantes devem carregar `correlation_id` e, quando disponível, referência ao trace técnico.

## Sampling

Não existe requisito de exportar 100% dos traces. Erros, lentidão e fluxos críticos devem ter prioridade; tráfego normal pode ser amostrado. A política deve ficar no Collector sempre que possível, evitando acoplamento ao backend.

## Privacidade e cardinalidade

- conteúdo bruto de documentos, prompts, respostas privadas e segredos não entra na telemetria por padrão;
- IDs de alta cardinalidade não viram labels de métricas;
- tenant/project context só é propagado quando necessário e de forma compatível com a política de dados.

## Consequências

A observabilidade custom existente não é descartada de uma vez; migra-se incrementalmente preservando os runbooks e a capacidade de incident response já existente.
