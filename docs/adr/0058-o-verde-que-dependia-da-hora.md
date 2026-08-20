# ADR 0058 — O verde que dependia da hora

**Status:** aceito
**Data:** 20/08/2026
**Fase:** 7 — defeito da ADR 0055, achado ao rodar a bateria fora do horário comercial

## Contexto

A ADR 0055 entregou o teto de horário do canal de WhatsApp: o worker consulta
`whatsapp.within_quiet_hours` antes de enviar (`worker.py:971` e `:1110`), e a janela é
21h–08h em `America/Sao_Paulo`. Ela acrescentou o helper `_freeze`, que congela
`retention.now`, e o usou **nos testes que ela mesma criou**.

Os testes anteriores não o usam. Eles chamam `_run`, que monta a passagem e roda a task —
e `_run` não congelava nada. A partir daquela fatia, portanto, **a hora da máquina passou a
decidir se sete testes passam**, e nada ficou vermelho para dizer isso: a ADR 0055 foi
commitada às 17h13 de São Paulo, fora da janela, e o CI concordou.

A medição é nas duas direções, e é ela que transforma o diagnóstico em afirmação:

| Execução | Resultado |
|---|---|
| `pytest apps/api/tests/test_whatsapp.py` às 23h31 de SP | reprovam os **sete** anteriores |
| a mesma, com `CONTACT_QUIET_HOURS_START=0 CONTACT_QUIET_HOURS_END=0` | os sete passam, e reprovam os **cinco** que afirmam sobre a janela |

O custo não é local. O runner do CI roda em UTC, e 21h–08h em São Paulo é **00:00–11:00 UTC**:
o job `api-quality` estava vermelho por onze horas por dia, para qualquer branch, por um
motivo que não tem nada a ver com o código empurrado. É o inverso exato do que a ADR 0020
decidiu ao tirar o `continue-on-error` do `e2e` — lá um portão não podia reprovar, aqui um
portão reprova sozinho —, e as duas coisas custam a mesma: o vermelho deixa de significar
alguma coisa.

**De quebra, o mesmo relógio no código de produto.** `_results_projection`
(`integrations/biahflow.py`) decidia "marco atrasado" com `date.today()` — a data da
**máquina**, que no contêiner é UTC. Um marco com prazo hoje passava a contar como atrasado
às 21h de São Paulo, três horas antes do dia virar para quem olha a tela. É a mesma classe do
defeito dos testes, do lado que o cliente vê, e `date.today()` aparecia em exatamente dois
lugares no repositório inteiro — este e o teste de vigência de preço do `test_ai_quota.py`,
que reprova entre 21h e meia-noite pelo motivo simétrico: o razão conta o dia por
`func.date(occurred_at)`, que é UTC, e o teste comparava com a data local.

## Decisão

**O momento entra por parâmetro em quem aciona o envio, e o "dia do produto" tem um dono.**

### `clock.py`, e ele é folha

`PRODUCT_TIMEZONE` sai de `integrations/whatsapp.py` e vira `clock.py`, com `product_hour` e
`product_date` — funções puras, momento por parâmetro, na forma de `within_quiet_hours`,
`results.py` e `audit.evaluate`. **Muda de casa e não muda de valor**, como os rótulos de aba
na ADR 0043 e os espaços de nomes na ADR 0057.

O argumento é o de `textfold.py`, `tabs.py` e `anchors.py`, e é o único que importa: o
segundo lugar a responder "que dia é hoje para este cliente" diverge do primeiro sem nada
ficar vermelho. Havia dois — um fuso explícito no canal e uma data implícita na projeção —, e
eles **já divergiam**.

`PRODUCT_TIMEZONE` **não** foi reexportado em `whatsapp.py`: nenhum módulo e nenhum teste o
importava de lá, e reexportar símbolo sem leitor é o defeito que a ADR 0033 mede.

### `_run` exige a hora, e a exigência é da assinatura

`_run(monkeypatch, ids, settings, *, at)` — obrigatório, não opcional com padrão. Um padrão
resolveria os sete casos de hoje e deixaria o oitavo nascer errado amanhã; a assinatura
obrigatória faz o arquivo **não importar** enquanto alguém não declarar.

### As guardas, e o que cada uma mediu

**Guarda 1 — todo teste que alcança o envio declara o momento antes de acionar.** Varredura de
AST sobre o próprio arquivo, na forma das varreduras de `test_telemetry.py`. Nasceu vermelha
nomeando **oito** funções com as linhas:

```
AssertionError: teste(s) que acionam o envio sem declarar o momento (`_freeze` ou
`_run(..., at=...)`): test_without_consent_nothing_is_sent_even_with_the_channel_on (linha 174);
test_revoking_the_consent_cancels_what_is_already_queued (linha 199); … (oito ao todo)
```

Oito, e não os sete do baseline: `test_without_consent_nothing_is_sent_even_with_the_channel_on`
também aciona o envio sem declarar a hora, e o relógio não o pegava porque ele afirma sobre um
caminho que recusa antes da janela. **A guarda vê o que a falha não mostrava** — que é a razão
de ela existir em vez de o conserto ser sete linhas.

**O elo é com a ordem, e isso foi medido.** A primeira versão perguntava se existe um `_freeze`
na função. Trocando um `_run(..., at=_AWAKE)` por um envio direto seguido de `_freeze`, aquela
versão passa **verde** sobre um teste em que o relógio não foi congelado para o envio nenhum;
com a comparação de linha, ela reprova nomeando a função. É a frouxidão que a ADR 0035 mediu ao
dar `POST /chat` como coberto por um 404 que era de outra rota. Pelo mesmo motivo a varredura é
`ast.walk` e não `tree.body`: um teste dentro de classe é teste, e a guarda que só enxerga o
topo do módulo nasce cega para ele.

**Guarda 2 — o dia do marco é o dia do produto.** Um marco com prazo em 19/08 não está atrasado
às 23h30 de São Paulo, instante em que UTC já é 20/08. Provada por mutação — trocando
`clock.product_date(...)` pelo `.date()` do momento UTC:

```
>       assert projection["overdue"] == 0
E       assert 1 == 0
```

## Consequências

**O que fica declarado, e não corrigido.**

- **Dois testes reprovam por resíduo do banco local**, e não por esta fatia:
  `test_authorization.py::test_a_client_only_sees_and_reads_their_own_notifications` e
  `test_drive_sync.py::test_the_beat_tick_only_fans_out_enabled_connections` leem estado
  deixado por execuções anteriores no Postgres de desenvolvimento — uma conexão do Drive do
  passeio local, avisos de outra passagem. Passam isolados e em banco novo, e o CI cria o
  Postgres a cada corrida. Fica nomeado porque um baseline não declarado vira, na fatia
  seguinte, "o teste que já estava vermelho".
- **`_settings()` ainda deixa `CONTACT_QUIET_HOURS_START/END` do ambiente entrar nos testes de
  janela.** Com as duas variáveis em `0`, cinco deles reprovam. Não é o defeito desta fatia — o
  relógio deixou de decidir, a configuração explícita ainda decide — e está registrado para não
  ser rediagnosticado como o mesmo problema.

**Sem evento de log novo**, e portanto sem linha em `docs/runbooks/alerts.md`: a guarda de
eventos é bidirecional desde a ADR 0034, e uma linha de runbook sem emissor reprovaria. É
afirmação desta ADR, não omissão dela.

**E o que esta fatia não é.** O portal está fora do ar desde 13/08/2026 (ADR 0053). Isto
devolve significado a um portão de CI; nada aqui foi observado servindo cliente.
