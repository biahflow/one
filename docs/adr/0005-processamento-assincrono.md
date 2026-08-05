# ADR 0005 — Jobs

**Status:** Aceito

Celery e Redis processam tarefas que não devem bloquear a experiência: sync Drive, extração, indexação, notificações e agregados. Jobs são idempotentes, rastreáveis e carregam tenant/projeto.

## Atualização (Fase 4, ADR 0016)

Esta ADR reivindicava o sync do Drive como job desde sempre; o que faltava era quem acordasse. O `celery beat` existe agora, como serviço próprio no compose e com **réplica única** — duas réplicas significam ticks duplicados.

A guarda de sobreposição não é um lock em Redis: é um `UPDATE` condicional na própria linha da conexão, com uma janela que recupera o que um worker morto deixou reivindicado. Mesmo argumento da janela de rate limit da ADR 0013 — o estado mora onde o dado mora, e o caminho de requisição não ganha uma dependência dura nova.
