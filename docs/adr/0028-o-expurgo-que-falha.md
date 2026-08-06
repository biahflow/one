# ADR 0028 — O expurgo que falha, e o alerta que o denunciaria

**Status:** aceita — 06/08/2026
**Contexto:** Fase 6. Fecha o caminho de falha que faltava no apagamento por organização, e
faz existir os dois eventos que o `alerts.md` mandava procurar.

## Contexto

`docs/runbooks/alerts.md` promete o alerta `erasure.failed` para **qualquer ocorrência**, com o
argumento escrito na própria linha: um apagamento pedido e não cumprido é obrigação contratual, e
o pedido fica `failed` no banco *"mas ninguém olha uma tabela sem motivo"*.

**O código nunca emitiu esse evento**, e o motivo é que o caminho de falha não existia. Em
`worker._run_erasure`, só a metade do *storage* tinha tratamento:

```python
except storage.StorageError as exc:
    ...  # state=failed, error, logger.exception("erasure.storage_failed")
```

A metade do banco — `retention.run_erasure(session, organization_id)` — não tinha nenhum. Uma
exceção ali (FK, deadlock, timeout num tenant grande) produzia quatro coisas de uma vez:

1. A transação revertia. Nada era apagado.
2. A linha ficava em `running` **para sempre**: `_claim_erasure` só reivindicava `pending`, e
   `run_erasure_requests` só *selecionava* `pending`. Nunca era retentada.
3. Nenhum `erasure.failed` era registrado — o alerta não tinha como disparar.
4. `admin.py` trata `pending|running` como "já existe pedido", então a tela da ADR 0027
   respondia **"já existe um pedido em execução" para sempre**, e o tenant ficava
   permanentemente inapagável pela interface.

O item 4 é o que dá urgência, e é consequência direta da fatia anterior: dar tela à rota
transformou uma falha silenciosa do worker num beco sem saída visível para uma obrigação
contratual. A tela não criou o defeito; ela o tornou alcançável.

### Duas assimetrias mostram que foi lapso, não decisão

`purge_expired_data`, **dez linhas acima no mesmo arquivo**, envolve cada organização em
`try/except Exception` e emite `retention.purge_failed`. As duas rotinas são o mesmo assunto —
apagar dado por política — e só uma sabia falhar.

E o docstring de `_claim_erasure` diz, literalmente, que ele reivindica *"como o sync do
Drive"*. Copiou o `UPDATE` condicional e **não** a janela de `drive_sync_stale_after_seconds`,
que existe lá exatamente para um processo morto não deixar a linha presa. A omissão custava mais
aqui do que lá: uma conexão de Drive presa deixa de sincronizar; um expurgo preso deixa uma
obrigação por cumprir *e* tranca a tela.

### E o mesmo runbook nomeava um segundo evento inexistente

`alerts.md` citava `drive.rejected` para "atalho, arquivo fora da pasta". O código emitia
`drive.file_outside_authorized_folder` para o segundo caso e **nada** para o primeiro — o atalho
só incrementava `listing.rejected` e sumia. É o defeito que a ADR 0021 corrigiu no runbook do
provedor, de novo, e desta vez com metade da fronteira que a ADR 0016 confere duas vezes passando
por "nada aconteceu".

## Decisão

### 1. A metade do banco ganha o tratamento que a do storage já tinha

Espelho exato do ramo do `StorageError`, inclusive na parte que parece detalhe: a sessão que
carimba `failed` é **nova**, porque a que falhou foi revertida. É essa reversão que garante que
`failed` nunca descreva meia remoção — e há um teste que afirma justamente isso, que o conteúdo
continua lá depois da falha.

### 2. `failed` é terminal para o laço; quem reabre é a tela

O beat não retenta. Como `admin.py` só bloqueia em `pending|running`, um pedido `failed` já
libera um pedido novo — linha nova, e o `error`/`removed` do anterior intactos, que é o histórico
que a ADR 0017 exige quando diz que a linha do pedido sobrevive ao próprio expurgo.

Retentar sozinho foi recusado com dois custos concretos: numa falha permanente o laço grava o
mesmo erro a cada tick, e dispara junto um alerta declarado como "qualquer ocorrência" — que é
como se ensina uma equipe a filtrar justamente o alerta que não deveria filtrar. Uma obrigação
contratual que falhou merece decisão humana.

Nada mudou no web: `OrganizationAdminClient` já renderiza `failed` em vermelho com o motivo.

### 3. Uma janela de `stale`, e um predicado só para os dois usos

Um worker morto **no meio** não passa por `except` nenhum — o processo some. Esse é o caso que a
janela resolve, e é diferente do item 1.

`erasure_stale_after_seconds` (1800, o mesmo número e o mesmo motivo do Drive) e um
`_erasure_is_claimable(settings)` usado **nos dois lugares** — no filtro do tick e no `WHERE` do
`UPDATE`. Um predicado só porque selecionar e reivindicar com regras diferentes é como se ganha
um laço que escolhe o que não consegue pegar; e um teste afirma que o tick *seleciona* o vencido,
não só que o claim o aceitaria.

`started_at` já existia na linha, então **não há migração**.

### 4. O atalho passa a deixar rastro

`drive.shortcut_skipped`, emitido onde o descarte acontece. O adapter é "puro transporte", e o
log não o viola: ele **já registrava** ali mesmo, vinte linhas abaixo, a outra metade da mesma
fronteira. O `alerts.md` passa a nomear os dois eventos reais.

## Consequências

- **Um expurgo que falha grava, avisa e não prende o tenant.** As três coisas que o runbook já
  dava como certas.
- **Os quatro testes nasceram vermelhos e há prova disso.** Neutralizando o `except`, os três que
  dependem dele reprovam, incluindo o de HTTP que percorre o beco sem saída pela rota. É o
  argumento da ADR 0020 contra guarda que nasce verde.
- **O teste do beco sem saída mora em `test_admin_endpoints.py`**, e não junto dos outros: ele é
  sobre o que a *rota* responde depois da falha, e é a costura entre esta ADR e a 0027. Os três
  restantes ficam em `test_retention.py`, ao lado dos que provam que o expurgo apaga o certo.
- **`captured()` saiu de `test_telemetry.py` para o `conftest.py`.** Ela existe por causa de um
  comentário de dez linhas (o Celery reconfigura o logging da raiz, e um teste que passa sozinho
  falha em conjunto), e a segunda a precisar dela foi de outro módulo. Duplicar um utilitário
  cuja razão de existir é um parágrafo garante que uma das cópias envelheça sozinha.
- **Sem migração, sem rota, sem contrato.** `alembic check` limpo e `docs/api/openapi.json`
  parado — a fatia é toda comportamento de worker.
- **O que continua declarado e não implementado:** não há contador de tentativas, então "falhou
  três vezes seguidas" não é uma pergunta que o banco responda; o que existe é uma linha por
  tentativa, e o histórico da tela é onde isso se lê. Uma coluna de tentativas pediria migração e
  uma decisão de "quanto é N" que nada no repositório hoje pede.

## Alternativas recusadas

**Retentar `failed` automaticamente no tick seguinte.** Ver decisão 2.

**Contador de tentativas com corte.** Cobriria a falha transitória e a permanente, ao custo de
coluna, migração e um número arbitrário. A janela de `stale` já cobre o caso transitório que
importa de verdade — o worker que morreu —, e a falha determinística vira decisão de gente.

**Um `except` genérico em volta do `_run_erasure` inteiro.** Pegaria os dois casos com metade do
código, e apagaria a distinção entre `erasure.storage_failed` e `erasure.failed` que o
`alerts.md` faz de propósito: a resposta operacional a "o S3 recusou" não é a mesma que a de "o
`DELETE` explodiu", e o runbook precisa poder mandar para lugares diferentes.

**Deixar o atalho sem log, contando com `listing.rejected`.** O contador vai para as estatísticas
do sync e some no agregado; um alerta por ocorrência não tem como sair de um número que soma
duas causas diferentes — e era exatamente por isso que `alerts.md` tratava as duas como um evento
só que não existia.
