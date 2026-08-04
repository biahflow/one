# ADR 0005 — Jobs

**Status:** Aceito

Celery e Redis processam tarefas que não devem bloquear a experiência: sync Drive, extração, indexação, notificações e agregados. Jobs são idempotentes, rastreáveis e carregam tenant/projeto.
