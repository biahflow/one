# ADR 0033 — A guarda que parecia cobrir o contrato, e os oito esquemas

**Status:** aceita — 06/08/2026
**Contexto:** Fase 6. Quarta repetição do padrão das ADRs 0024/0026/0027 — e desta vez a
promessa quebrada era **uma guarda de CI**, que é o mecanismo que existe para as promessas não
serem quebradas.

## Contexto

A ADR 0029 criou a guarda de que *"o contrato tem de ser consumido, não só casado"*: para cada
esquema do dashboard, toda propriedade declarada tem de ser desreferenciada no mapeamento do BFF.
Ela nasceu vermelha apontando `PendingOut.priority`, e o comentário dela encerra dizendo que a
allowlist *"existe e está **vazia**, e a meta é que continue"*.

Só que ela era um `for` sobre **oito nomes escritos à mão** lendo **um arquivo**
(`PAGE = app/page.tsx`). O contrato publicado tem **56 esquemas de resposta**. Os outros 48 nunca
foram olhados — e a allowlist seguia vazia não porque nada escapava, mas porque nada a consultava.

É a forma exata da ADR 0023, repetida: lá o `dependency-review` *parecia* varredura e olhava só o
diff de um PR, e foi por isso que nove avisos do `next`, sete do `starlette` e seis do
`python-multipart` passaram verdes a cada push. Aqui a guarda *parecia* cobrir o contrato e cobria
14% dele.

## O que escapou

Três achados à mão e o resto pela guarda generalizada. Os três primeiros importam porque não são
campo faltando na tela — são **a tela afirmando coisa que não é**:

1. **`ResultsOut.assumption_basis`** existe em `results.py` com o docstring *"A conta em si, para o
   cliente poder refazê-la na mão"*, e não aparecia em lugar nenhum de `app/`. No lugar dele, a
   linha "Fórmula do ROI" imprimia um **literal**: `(economia apurada − investimento) ÷
   investimento` — que nem casa com a fórmula que a API devolve (`beneficio`, não `economia
   apurada`). O `CLAUDE.md` afirma que nenhum caminho da tela fabrica resposta ou citação; era
   verdade para citação, e a **explicação do número** estava fabricada — no bloco "Como
   calculamos", que a Fase 3 abriu justamente para o cliente conferir a conta.
2. **`feedback_comment` não tinha escritor.** A API aceitava, a rota do BFF repassava, e
   `rateAnswer` mandava só `{message_id, helpful}`. Enquanto isso `/admin/assistente` renderizava
   um painel intitulado **"O que os clientes disseram"** sobre um campo sempre `null` — três dias
   depois de a ADR 0030 chamá-lo de *"o campo mais informativo do conjunto: o polegar diz que
   errou, o comentário diz o quê"*.
3. **`DriveConnectionOut.last_sync_stats`**, cujo produtor nomeia a tela para a qual foi feito
   (*"Vira `last_sync_stats` **e a linha da tela**"*). Uma sincronização que bateu no teto
   (`truncated`) ou barrou arquivos na fronteira era **indistinguível** de uma completa, na tela
   cuja razão de existir é responder "por que a IA não sabe disso?".

E mais: `ChatOut.confidence` descartado no chat (o cliente via "Pendência criada" sem nada dizer
que a resposta acima dela não tinha lastro), `currency` mapeado e ignorado com todo formatador em
`BRL` fixo — uma premissa em outra moeda saía **errada**, não incompleta —, `scanned_at`,
`rotated_from_id` (que um runbook manda o operador ler), `labor_savings_cents`/`avoided_cost_cents`
(a divisão que o card já afirmava), `events_without_assumption`, `days_in_period` e `period.from`.

## Decisão

### 1. O escopo sai do contrato, não de uma lista

Nem os esquemas nem os arquivos ficam escritos à mão — foi a lista à mão que produziu o defeito, e
uma lista nova envelheceria igual. Os esquemas saem por fechamento transitivo de `$ref` sobre as
respostas 2xx das rotas que o BFF chama; os arquivos saem de `app/`. Rota nova com esquema novo
entra sozinha, no commit que a cria.

### 2. O corpus é por esquema, e isso foi medido — não deduzido

A primeira versão usava **um corpus único sobre todo `app/`**. Ela ficou verde, e estava errada: ao
neutralizar o mapeamento de `.priority` em `app/page.tsx`, a guarda **não reprovou** — porque
`.priority` também é o nome do campo na *view*, num arquivo que recebe o valor por prop e não do
JSON. Ou seja, a guarda generalizada nasceria verde em cima do defeito exato da ADR 0029: o mesmo
erro que ela existe para não repetir, cometido por ela.

O corpus estrito (só quem chama a rota) também não serve: as rotas de `app/api/**` são **passagem**
— devolvem o JSON sem mapear — e o consumidor de verdade é quem as chama. A versão estrita acusou
49 campos, quase todos falsos.

O que serve são dois elos explícitos, do arquivo que chama a rota para quem consome o que ele
produz:

1. **`import` relativo** — `KnowledgeClient.tsx` importa `../actions`, e é lá que `authorize_url`
   é lido;
2. **`fetch("/api/…")`** — `DashboardClient.tsx` não *importa* `app/api/chat/route.ts`, chama-o por
   URL. Sem este elo, os oito campos de `ConversationMessageOut` apareceriam como descartados.

Nada disso alcança `app/page.tsx`: ninguém o importa e ninguém o chama, porque é um segmento de
rota do Next. **É por isso que `priority` volta a ser pego**, e há prova: com as duas
desreferências neutralizadas, a guarda reprova nomeando o campo.

### 3. Uma segunda asserção: toda rota do contrato tem chamador

Mesmo defeito um nível acima. Foi o que achou `GET /api/v1/projects/{project_id}/results` — rota
completa, com `response_model`, testada, cujo docstring diz que *"é aqui que 'o cliente vê a origem
e a premissa de todo indicador' deixa de ser promessa"* — e `GET /api/v1/dashboard/demo`, que
**saiu**.

### 4. A allowlist vence, como a do `advisories.json`

Uma linha que deixou de ser necessária reprova. Sem isso a allowlist vira sedimento e a guarda
afrouxa sozinha — é a regra da ADR 0023 aplicada aqui.

### 5. As cinco exceções têm todas a mesma forma, e é ela que as torna aceitáveis: **eco**

`NotificationsReadOut.marked`, `PendingCommentsOut.pending_item_id`,
`PreferencesOut.notify_by_email`, `AssistantSignalOut.project_id` e
`DocumentDownloadOut.expires_at` são campos que a resposta devolve e que quem chamou já tinha em
mãos antes de chamar. Não há o que a tela aprenda lendo-os. `MeProjectOut.slug` é a única com
prazo (`02/2027`), porque ali a pergunta é para o contrato.

### 6. `GET /api/v1/dashboard/demo` sai, e o teste afirma a ausência

A casca de demonstração do produto é `app/demo-overview.ts`, no BFF, atrás do gate duplo de
`demoShellEnabled()`. A rota existia desde a Fase 1 e nunca teve chamador. O teste que a exercitava
virou um que afirma que ela responde 404 **com `DEMO_MODE` ligado** — sem essa asserção, "removida"
e "quebrada pelo gate" seriam indistinguíveis.

## Consequências

- **A guarda nasceu vermelha com catorze campos e uma rota**, e a prova de que ela ainda pega o
  caso original da ADR 0029 é executável, não argumentada.
- **Sumiu o último lugar em que a tela do cliente afirmava um número por conta própria.** A frase
  do `CLAUDE.md` sobre não haver mais dado fabricado passa a valer também para a *explicação* do
  dado, e não só para a resposta e a citação.
- **A tela do time interno deixou de ter um painel impossível.** "O que os clientes disseram" tem
  escritor.
- **Uma premissa em moeda estrangeira deixa de ser renderizada como real** — nas duas telas.
- **`app/api/**` ganhou papel declarado:** são passagem, e a guarda sabe disso. Uma rota interna
  nova que ninguém chame passa a ser visível.
- **Custo:** a guarda ficou consideravelmente mais complexa que um `includes()`. É o preço de ela
  ser precisa em vez de só ampla, e a alternativa medida era uma guarda que passa no defeito que
  motivou a anterior.

## Alternativas recusadas

**Corpus único sobre `app/`.** Simples, e **falsa** — medida, não suposta: deixa `priority` passar.
Uma guarda que não pega o caso que originou a guarda anterior é pior que nenhuma, porque o verde
afirma o contrário.

**Corpus estrito por rota.** 49 campos, quase todos falsos, porque ignora que as rotas de
`app/api/**` são passagem. Uma allowlist com 40 linhas de desculpa é o mecanismo de exceção
comendo o controle.

**Exigir que o campo seja *renderizado*, e não só mapeado.** É a pergunta certa e outra guarda: o
mapeamento é sintaticamente localizável, "aparece na tela" não é. `PendingOut.description` é
mapeado e nunca renderizado — fica registrado aqui, e é fatia própria.

**Tipar os produtores do lado Python** (`build_dashboard` devolvendo modelo em vez de `dict`),
recusado de novo pelo argumento da ADR 0020 e da FDD 014: continua sendo o destino natural, e
continua pedindo um período de contrato quieto antes.

**Manter `/api/v1/dashboard/demo` com allowlist.** Seria a allowlist absorvendo superfície morta —
exatamente o que a ADR 0029 diz que uma allowlist crescente significa.
