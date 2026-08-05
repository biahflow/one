# Runbook — Incidente

1. Classificar severidade e preservar `trace_id`/auditoria (ver abaixo).
2. Revogar sessão, token ou conector afetado.
3. Conter o acesso, avaliar tenant impactado e restaurar serviço.
4. Registrar causa, impacto, comunicação e ação preventiva em RFC/ADR quando aplicável.

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
