# Runbook — Alertas

O que deve acordar alguém, com que limiar, e para onde ir depois. Cada linha é um
**evento nomeado** do log estruturado (ADR 0018), então a regra é sempre a mesma
consulta: filtrar por `event` e contar dentro de uma janela.

Não há Prometheus nem exporter neste repositório — métrica e coletor pertencem ao
item de homologação do `ROADMAP.md`, que é quando existirá para onde mandá-las.
Até lá o substrato é o log JSON no stdout de cada serviço, que qualquer coletor
(Loki, CloudWatch, Datadog) ingere sem código nosso.

## Acordam alguém

| Evento | Limiar | O que significa | Runbook |
|---|---|---|---|
| `document.infected` | qualquer ocorrência | Um arquivo com malware chegou ao portal. O objeto já foi destruído e a linha preservada — o alerta é para **avisar o tenant**, não para conter. | `document-ingestion-failure.md`, `incident-response.md` |
| `erasure.failed` / `erasure.storage_failed` | qualquer ocorrência | Um apagamento pedido não foi cumprido. É obrigação contratual e o pedido fica `failed` no banco, visível — mas ninguém olha uma tabela sem motivo. | `incident-response.md` |
| `health.database_unavailable` | 2 em 5 min | O caminho de requisição perdeu o Postgres. O `/health/ready` já está em 503 e o compose/orquestrador já tirou a réplica do balanceamento. | `auth-failure.md` (a RLS sem contexto devolve zero linhas, que **se parece** com isto) |
| ausência de `task.started` com `root=beat` | 2× `RETENTION_INTERVAL_SECONDS` | O agendador parou. É alerta **por ausência** porque o `beat` não tem healthcheck: com tick de 15 min a 24 h, nenhuma sonda barata distingue "parado" de "entre ticks" (ver o comentário no `docker-compose.yml`). | `drive-sync-failure.md` |

## Avisam, sem acordar

| Evento | Limiar | O que significa | Runbook |
|---|---|---|---|
| `drive.sync_failed` com `disable=true` | qualquer ocorrência | O Google recusou a credencial e a pasta foi **pausada**, não apagada. O índice continua servindo o chat; alguém precisa reconsentir. | `drive-sync-failure.md` |
| `retention.purge_failed` | 2 dias seguidos | A poda de uma organização falha repetidamente. Uma falha isolada é recuperada no tick seguinte por construção. | `incident-response.md` |
| `queue.unavailable` | 5 em 5 min | O Redis está fora. Cada `queue.unavailable` é um trabalho que **não** se perdeu — a linha está comitada —, mas que só sai no próximo tick. Volume alto é indisponibilidade do broker. | — |
| `digest.send_failed` | 10 em 1 h | O SMTP está recusando. As notificações continuam no sino; só o e-mail atrasa (`emailed_at IS NULL` faz a retentativa sozinha). | — |
| `embedding.failed` | 5 em 1 h | O provedor de embeddings está fora. Documentos ficam `failed` e não entram no índice — o chat responde declarando a lacuna, que é o comportamento correto, mas por motivo errado. | `ai-provider-failure.md` |
| `agent_key.rate_limited` | 100 em 5 min por `key_prefix` | Um agente está retentando em loop. Ler o `key_prefix` para saber qual. | `agent-events-failure.md` |

## Não são alerta

São o controle **funcionando**, e tratá-los como incidente ensina a equipe a
ignorar o painel:

- `auth.rejected` — token expirado é o caso comum de qualquer sessão. Só vira
  sinal como **taxa**: um salto sustentado de `reason=signature` ou
  `reason=issuer` é sondagem, e aí o runbook é `auth-failure.md`. Um pico de
  `reason=expired` logo depois de um deploy do Keycloak é rotina.
- `drive.rejected` (atalho, arquivo fora da pasta) — é a fronteira barrando o que
  deve barrar, como diz `observability.md`.
- `document.scan_state=skipped` — é "ninguém varreu", e é o estado normal da
  stack local e do CI, que não têm ClamAV. **Em produção com `CLAMAV_HOST`
  configurado, `skipped` sustentado é alerta**: significa que o scanner
  configurado não está respondendo, e a ADR 0017 é explícita em que `skipped`
  nunca equivale a `clean`.

## Como consultar

O log é uma linha JSON por evento, com `trace_id` em todas:

```bash
docker compose logs api   | grep '"event":"auth.rejected"' | tail -20
docker compose logs worker | grep '"event":"queue.unavailable"'
```

Para seguir uma requisição inteira — web, API e as tasks que ela disparou:

```bash
docker compose logs | grep '"trace_id":"<id>"'
```

E para chegar ao `trace_id` a partir de uma ação registrada:

```sql
SELECT action, created_at, data->>'trace_id' FROM portal.audit_log
 WHERE entity_id = '<id>' ORDER BY created_at DESC;
```
