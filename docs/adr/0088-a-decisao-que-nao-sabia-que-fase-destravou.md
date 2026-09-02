# ADR 0088 — A decisão que não sabia que fase destravou

**Status:** aceito
**Data:** 02/09/2026
**Fase:** 7

> Fecha o **único critério de aceite em aberto** da Issue #62 — *"decisões e gates
> entendíveis sem termos internos"* —, que estava `DEPENDENCY_BLOCKED` desde 27/08/2026
> esperando o Pulse carimbar `phase_ref`. Ele carimbou em **31/08/2026**
> (`biahflow/pulse#46`, ADR 0057 e FDD 032 de lá), e ninguém deste lado percebeu.

## Contexto

### A promessa estava no desenho aprovado, não num documento de fundo

O DAP r1 da F-028 está `Approved` desde 26/08/2026 e lista, entre as superfícies que ele
decide, *"Timeline — decisão/gate ancorada à fase (client-safe: title/racional/data)"*.
A tabela de proveniência de valores visuais daquele pacote é ainda mais explícita:

> **Nó de decisão/gate na timeline** (title/racional/data ancorado à fase) — *`Decision`
> já projetado, mas como lista* — **sim, a ancoragem à fase é nova**.

E a decisão 3 do pacote diz por que ela existe: *"o cliente vê qual decisão destravou
qual fase, dentro do que é client-safe"*. Nada disso foi construído: a decisão saía numa
lista solta na aba Decisões, e a jornada não sabia que ela existia.

### O bloqueio era real, e deixou de ser sem que nada ficasse vermelho

A alternativa — inferir a fase por `decided_on` × janela da fase — foi **considerada e
recusada em gate humano** em 27/08/2026, e recusada de novo, do outro lado, na ADR 0057
do Pulse. São dois gates humanos independentes sobre a mesma pergunta. Com a inferência
fora, a superfície dependia de um campo que a origem não mandava, e a FDD 028 foi
declarada `BLOCKED` **por decisão registrada, não por omissão** — que é a forma certa.

O que ficou sem dono foi a outra ponta. Em 31/08/2026 o Pulse passou a carimbar
`phase_ref` por decisão publicada, e daquele dia até esta fatia o campo **chegava no
envelope e era descartado na ingestão**: `phase_ref` aparecia em quatro documentos deste
repositório e em **zero linhas de código**. É a forma do defeito que a ADR 0033 mediu,
girada 180 graus — lá um painel publicado sobre campo que nunca teve escritor; aqui um
campo com escritor do outro lado e nenhum leitor deste. E é o defeito que a ADR 0037 já
tinha visto nesta mesma fronteira: o que entra no snapshot precisa de consumidor, sob
pena de o portal exibir menos do que a origem já lhe diz.

### O contrato do produtor, verificado no código dele

`backend/apps/core/portal.py` do `biahflow/pulse`:

- `journey.phases[].id = phase.pk`;
- `decisions[].phase_ref = decisao.project_phase_id`, com o comentário do arquivo dizendo
  que é a **mesma identidade** de `journey.phases[].id`.

E as regras da ADR 0057 de lá, que valem como contrato:

- a chave `phase_ref` **existe sempre**, e vem `null` no legado — *"a lacuna é declarada
  em vez de mascarada por heurística"*;
- decisão publicada nova **exige** fase, e a fase pertence ao mesmo projeto;
- `SET_NULL` na remoção da fase: o fato sobrevive e volta a declarar a lacuna.

## Decisão

### 1. O recasamento é na ingestão, e `ProjectPhase` não ganha coluna

`Decision` ganha `project_phase_id` — FK anulável para `project_phase` com `ON DELETE SET
NULL`, **espelhando `meeting_id` linha a linha**, porque o problema é literalmente o
mesmo: `sync_snapshot` apaga e recria as duas tabelas a cada webhook, então o uuid da
fase muda toda passagem e o vínculo só se sustenta se for refeito na mesma transação.

O preenchimento copia o `reuniao_por_id` que já existia ao lado: o laço das fases monta
`fase_por_id: dict[str, ProjectPhase]` a partir de `phase_data["id"]`, e o laço das
decisões resolve `phase_ref` nesse mapa. As fases são inseridas **antes** das decisões na
mesma transação, e o `flush` por fase que já existia — *"precisamos do phase.id para os
entregáveis"* — é o que torna o mapa utilizável sem um segundo.

**`ProjectPhase` não ganha `external_ref`**, e o contraste com `PhaseDeliverable` é o
argumento: lá o id da origem é persistido porque um fato **fora** do read model precisa
nomear aquele entregável meses depois (o aceite do cliente, ADR 0077). Aqui o id da
origem só é necessário **dentro** da transação que recria as duas tabelas juntas.
Persistir uma identidade que nenhum leitor consulta é o defeito da ADR 0033 na direção de
entrada — campo com escritor e sem leitor.

### 2. O contrato publica o rótulo, não o id

`DecisionOut` ganha `journey_phase_name: str | None`. Três precedentes deste repositório mandam
isso, e os três dizem a mesma coisa:

- `DecisionOut.meeting_title` já é rótulo e não id, com a razão escrita — *"o uuid da
  reunião muda a cada sync"*, e o da fase muda igual;
- `DeliverableAcceptance.phase_name` desnormalizou o nome da fase pelo mesmo motivo, e
  ali ele precisa **sobreviver** à fase sumir da origem;
- a tela já ancora a fase **pelo nome**: `data-item={`phase:${item.name}`}` e o
  `screenAnchors()` do `DashboardClient.tsx`.

Ou seja: o servidor resolve pela identidade estável — o id da origem, na ingestão — e
publica a identidade que a tela já sabe casar. Homônimos caem na degradação benigna que a
ADR 0056 já aceitou e escreveu: *"o primeiro casamento vence"*.

Nada novo atravessa a fronteira da ADR 0067 por isso: o nome da fase já sai por
`PhaseOut.name` na **mesma resposta**. O que é novo é o vínculo.

**O nome do campo é `journey_phase_name` e não `phase_name`, e quem o decidiu foi a
medição.** `DeliverableAcceptanceOut.phase_name` já existe, com linha no `NOT_CONSUMED`
porque a tela genuinamente não o lê (ADR 0077 — ele é congelado *para o outro lado*). A
asserção de obsolescência daquela allowlist pergunta se o corpus do esquema contém
`.phase_name`, e o corpus é **por arquivo**: `app/page.tsx` mapeia o dashboard inteiro,
então está no corpus dos dois esquemas. Com `DecisionOut.phase_name`, a guarda cobrava a
linha da `DeliverableAcceptanceOut` como obsoleta — sobre um campo que continua sem
leitor —, e apagá-la deixaria a metade de cobertura verde por coincidência com outro
identificador: é o `.priority` da ADR 0033 e o `date`/`dated_at` da ADR 0038 outra vez, e
a saída daquelas duas foi a mesma, renomear para tornar o elo verificável. Medido: com
`phase_name`, vermelho; com `journey_phase_name`, os dois campos ficam verificáveis um a
um, e a mutação (trocar a leitura de `page.tsx` por `null`) reprova só o novo.

### 3. Decisão sem fase: nada na timeline, e nenhum estado novo

O legado vem com `phase_ref: null`. Essas decisões continuam aparecendo na aba Decisões
exatamente como hoje, e simplesmente não ganham nó na timeline.

**Não há rótulo de "sem fase" nem estado vazio**, e isso é limite nomeado e não lacuna: o
DAP aprovado não os desenha, e acrescentar superfície que o gate de design não aprovou é
furar o gate. É também a leitura que o resto do repositório já faz da nulidade —
ausência é ausência de afirmação, como em `canonical_stage`, `engagement_id` e
`observed_at`.

**O risco fica escrito, porque ele existe:** um cliente cujo projeto seja inteiramente
legado verá a timeline sem nó de decisão nenhum, e não terá como distinguir *"ninguém
decidiu nada nesta fase"* de *"a origem não ancorou estas decisões"*. A aba Decisões
mostra as decisões, então nada some — o que falta é o vínculo, e ele é falso quando
adivinhado. Se um dia isso enganar alguém, o conserto é **backfill no Pulse**, que é onde
a informação existe, e não um rótulo aqui.

### 4. `phase_ref` que não resolve emite evento

Se `phase_ref` não é nulo e **não** casa com nenhuma fase do mesmo envelope, grava `NULL`
e emite `projection.phase_ref_unresolved`, com o id não resolvido em `extra` — nunca
interpolado na mensagem (ADR 0018/0034) — e com linha no `alerts.md` no mesmo commit,
porque a guarda é bidirecional.

A razão de o evento existir: tratar isso como "legado nulo" apagaria a diferença entre *a
origem não carimbou* e *a origem carimbou algo que não chegou*. A segunda é
inconsistência do produtor — a fase saiu do `journey.phases[]` enquanto a decisão
continuou apontando para ela —, e alguém precisa poder vê-la. O `phase_ref` nulo segue
**silencioso**: ele é o caso normal, e um evento por decisão legada afogaria o runbook.

### 5. Nenhuma inferência por data, em nenhuma camada, e um teste que fixa isso

Não há fallback por `decided_on`. `test_the_phase_is_never_inferred_from_the_decision_date`
monta o caso em que a heurística pareceria certa — decisão sem `phase_ref` cuja data cai
**dentro** da janela de uma fase — e afirma que ela continua sem fase.

O teste existe porque sem ele reintroduzir o casador deixaria a suíte inteira verde: o
campo passaria a vir preenchido, e nenhum outro teste pergunta de onde ele veio.

## Consequências

- Migração `0042_decision_phase_anchor`, aditiva (ADR 0066) e **sem policy, RLS ou
  GRANT**: `decision` já tem RLS desde a `0003` e o papel de requisição já tem `SELECT`.
  Quem escreve a coluna é o sync sob `portal_system`, como toda coluna desta tabela.
- Com índice, ao contrário das três colunas da `0039`: a leitura do dashboard junta
  `decision` a `project_phase` por ela, que é o oposto de "nenhuma consulta filtra ou
  ordena por elas". É o índice que o `meeting_id` já tem, pelo mesmo motivo.
- `build_dashboard` ganha um segundo `outerjoin`, pela razão do primeiro: uma consulta por
  linha seria N+1 num laço que já é do dashboard.
- O seed local passou a ter os dois ramos — `apps/api/src/portal_api/seed_data/biahflow-snapshot.json`
  estava numa cópia de envelope **anterior a 31/08** e não exercitava nem um. Sem isso o
  passeio local nunca veria o caminho novo.
- `docs/contracts/one-visibility.json` ganha a linha de `DecisionOut.journey_phase_name` com a
  razão escrita: campo de resposta de cliente reprova por omissão (ADR 0082).
- A ordem de deleção do sync foi conferida e é inócua: `delete(ProjectPhase)` roda antes
  de `delete(Decision)`, então com o `SET NULL` as decisões velhas ficam momentaneamente
  sem fase antes de serem apagadas. Nenhuma leitura acontece no meio.
- **Cinco documentos deixaram de afirmar um bloqueio que caiu em 31/08** — FDD 028,
  `plan.md`, `evidence.md`, `ROADMAP.md` e a seção *Aberto* da ADR 0076 —, retificados com
  data e sem apagar a história.
- A FDD 028 passa a ter **recomendação** de `DONE`, e não o estado: quem a move é decisão
  humana.

### Aberto

- **Backfill do legado.** As decisões publicadas antes de 31/08 seguem sem `phase_ref` na
  origem. Corrigi-las é trabalho no Pulse, com a pessoa que sabe qual fase cada uma
  destravou; deste lado não há o que fazer que não seja inventar.
- **Exclusão de fase entre dois snapshots** deixa a decisão sem âncora até a passagem
  seguinte, se a origem repuser a fase. É o comportamento que o `SET NULL` escolhe dos dois
  lados, e a diferença entre esse caso e o legado é justamente o que o evento da §4 grava.
- **Âncora de item na aba Decisões** continua fora: ela é `ANCHORLESS_HITS` por decisão da
  ADR 0056, e esta fatia não a reabre.
