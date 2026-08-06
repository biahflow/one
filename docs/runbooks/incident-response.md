# Runbook — Incidente

1. Classificar severidade e preservar `trace_id`/auditoria (ver abaixo).
2. Revogar sessão, token ou conector afetado.
3. Conter o acesso, avaliar tenant impactado e restaurar serviço.
4. Registrar causa, impacto, comunicação e ação preventiva em RFC/ADR quando aplicável.

## `erasure.failed` / `erasure.storage_failed` (ADR 0017, 0028)

O `alerts.md` manda para cá em qualquer ocorrência, e a razão é que um apagamento
pedido e não cumprido é obrigação contratual. O que fazer:

1. **Ler o motivo na própria linha do pedido** — ele foi gravado junto do estado, e é
   a diferença entre "o S3 recusou" e "o `DELETE` explodiu", que têm respostas
   diferentes:

   ```sql
   SELECT id, state, requested_reason, error, started_at, completed_at, removed
     FROM portal.data_erasure_request
    WHERE organization_id = '<org>' ORDER BY created_at DESC;
   ```

2. **Nada foi apagado pela metade.** A sessão que falhou é revertida antes do carimbo,
   e há teste que afirma isso (`test_a_failed_erasure_removed_nothing`). Um `failed`
   descreve uma tentativa inteira que não aconteceu, nunca uma parcial.

3. **O pedido não é retentado sozinho** — de propósito (ADR 0028): numa falha
   permanente o laço gravaria o mesmo erro a cada tick e dispararia este alerta junto.
   Corrigida a causa, quem pede de novo é uma pessoa em **`/admin/organizacao`**; um
   `failed` já libera pedido novo, e o registro do que falhou fica.

4. **Se o estado é `running` e não muda**, o worker morreu no meio. Nenhum `except`
   alcança um processo que sumiu: espere `ERASURE_STALE_AFTER_SECONDS` (30 min) e o
   próximo tick reivindica — a mesma janela e o mesmo motivo do
   `DRIVE_SYNC_STALE_AFTER_SECONDS` em `drive-sync-failure.md`.

## Como seguir um `trace_id` (ADR 0018)

O identificador é o mesmo do navegador ao worker, e existe em três lugares: no log de
cada serviço, no header `X-Request-ID` da resposta da API, e na coluna
`audit_log.data`. As três direções:

**Do cliente para o log.** A tela de erro mostra um **Código** — é o `digest` do
Next, e a pessoa consegue lê-lo ao telefone. Ele aparece numa linha só:

```bash
docker compose logs web | grep '"digest":"<codigo>"'
```

Essa linha (`web.request_error`) carrega o `trace_id`.

**Do `trace_id` para a história inteira.** Um `grep` em todos os serviços de uma vez;
a ordem cronológica já é a ordem dos fatos:

```bash
docker compose logs | grep '"trace_id":"<id>"'
```

O que se espera ver: `http.request` na API, os `task.started`/`task.finished` que
aquela requisição disparou, e o evento que falhou no meio.

**Da ação registrada para o log, e de volta.** Toda linha de `audit_log` carrega o id
da requisição que a produziu:

```sql
SELECT action, entity_type, created_at, data->>'trace_id' AS trace_id
  FROM portal.audit_log
 WHERE organization_id = '<org>' AND created_at > now() - interval '1 hour'
 ORDER BY created_at DESC;
```

**O que não tem id.** A negação do portão de sessão do BFF — o 401 em `/api/` e o
redirect das páginas — acontece antes de o identificador ser cunhado, e só o carrega
quando quem chamou mandou um. Uma requisição barrada ali não deixa rastro
correlacionável; se a suspeita é de sondagem de sessão, o sinal a ler é o
`auth.rejected` da API, que é onde as tentativas que passaram do portão aparecem
(`auth-failure.md`).

**O que nunca está no log.** Texto de documento, pergunta do cliente, token, chave e
senha — por construção, e há teste que falha se um campo com nome de segredo passar
(`test_telemetry.py`). Se a investigação precisa do conteúdo, ele está no storage e no
banco, sob as regras de `data-classification.md`, e não no log.
