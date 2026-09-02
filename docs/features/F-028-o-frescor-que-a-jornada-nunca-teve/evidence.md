# Evidência — F-028

**Estado:** T01–T08 entregues e mergeados (PR #73 e PR #75), **mais a ancoragem decisão→fase**
(ADR 0088, 02/09/2026), que era o único critério em aberto. A feature está
`READY_FOR_HUMAN_REVIEW`, com recomendação de `DONE` — o estado é decisão humana. As seções abaixo
estão em ordem cronológica: o baseline de 26/08, a fatia não-interface (T01–T05), a superfície
(T06–T08), a nota de fechamento de 27/08 e a **reabertura de 02/09** ao final.

## Baseline (26/08/2026, `main`)

- Jornada já projetada (`build_dashboard`) e renderizada (`JourneyPanel`).
- **Sem frescor:** não há coluna `observed_at`/`synced_at`; `source` é hardcoded `"live"`; a ADR 0026
  removeu o carimbo inventado "Atualizado há 2 dias".
- **Sem defesa anti-regressão:** sync idempotente (re-busca snapshot inteiro), sem versão/observação
  comparável; único precedente de dedup por evento é `external_event_id` no `AgentEvent`.
- **Contrato não versionado** (ADR 0067 pediu); decisões são lista read-only, sem vínculo a fase.
- Padrão honesto de estado somente-consulta já existe: `readOnlyReason` (`archived_at`/
  `source_deleted_at`, ADR 0036/0037).

## A preencher na execução

- ADR aceita (contrato versionado + reconciliação) e capturas do DAP aprovado.
- `BUILD REPORT` por tarefa; teste de evento fora de ordem; guarda de filtro de campo interno.
- Prova de que stale/indisponível/encerrado são visivelmente distintos; isolamento intacto.
- Decisões humanas: gate de design, ADR, gate de plano, merge.

## Superfície (T06–T08, revisão 2 do plano) — 27/08/2026

Gate de design cumprido (DAP r1 `Approved`, 26/08) e revisão 2 do plano aprovada (27/08).
`observed_at`/`synced_at`/`projection_version` já vinham da fatia anterior (T01–T05, no `main`).

### O que a tela passou a dizer

| Estado | Onde | O que aparece |
| --- | --- | --- |
| Frescor da **origem** | cabeça da jornada | "Atualizado há X · sincronizado com o Biahflow" |
| Frescor da **cópia** (fallback declarado) | idem | "Sincronizado há X · hora da cópia, não da origem" |
| Sem carimbo | idem | **nada** — sem hora de verdade a tela não inventa uma (ADR 0026) |
| **Stale** | idem | `StatePill` `warning` "Pode estar desatualizado" + o motivo com a idade |
| **Indisponível** | `app/error.tsx` | `StatePill` `danger` "Projeção indisponível" + "não um projeto vazio" |
| Encerrado / removido | `status-card` | inalterado (ADR 0036/0037), e as asserções de antes seguem verdes |

O limiar do stale **não** é constante de componente: sai de `PROJECTION_STALE_HOURS`
(`.env.example` e `docker-compose.yml`), com default 24 h para a variável esquecida não
significar "nunca fica velho".

### Portões

- `npm run lint` — limpo.
- `npm test` — **162 passed, 0 failed, 0 skipped** (baseline do `main`: 156; seis testes novos).
- `npm run test:contract` — **92 passed**; quatro linhas de `NOT_CONSUMED` removidas
  (`observed_at`/`synced_at` nos dois esquemas, que agora têm leitor), duas mantidas
  (`projection_version`, que não é para a tela) com o motivo verdadeiro e sem prazo.
- `pytest apps/api/tests` (sem `test_backup_restore.py`) — **688 passed**, igual ao baseline.

### Guardas novas, medidas por mutação (ADR 0065)

| Mutação | Efeito esperado | Medido |
| --- | --- | --- |
| `FRESHNESS_LABEL.synced` passa a dizer "Atualizado" | o rótulo mente | ✖ *"o fallback é rotulado como hora da cópia"*, e só ela |
| `staleAfterHours()` devolve a constante e ignora o ambiente | o limiar deixa de ser de operação | ✖ *"o limiar do stale sai da configuração"*, e só ela |
| `freshnessOf` carimba `now()` quando não há hora nenhuma | volta o "Atualizado há 2 dias" da ADR 0026 | ✖ *"sem hora nenhuma não há carimbo"*, e só ela |

### Capturas (`evidence/browser/`)

Chromium headless, 1280×900 @1.5 (desktop) e 390×844 @2 (mobile), sobre `next start` com o
stub de API e o cookie forjado do teste de SSR — a mesma montagem de `rendered-html.test.mjs`,
porque não há portal de pé desde 13/08 (ADR 0053). O script foi descartável.

`01`/`02` frescor recente (desktop, mobile) · `03` fallback rotulado como cópia ·
`04`/`05` stale · `06`/`07` indisponível · `08` foco por teclado na fase da jornada.

**O `08` é sobre teclado e o script verificou o comportamento, não só a imagem**: o foco pousa
num `<button>` dentro de `.journey-track` e o `Enter` seleciona a fase (`Prove`), que é o que
`inertButtons()` cobra na fonte.

**As capturas do indisponível são a única evidência possível dele, e isso foi medido**: o
documento do SSR sai com o `loading.tsx` dentro do limite de Suspense e um `$RX(...)` no fim —
o componente de servidor lança **depois** de os cabeçalhos irem embora, então a resposta é 200
e quem desenha o cartão é o cliente, na hidratação. Nenhuma asserção sobre HTML renderizado
alcança aquele markup; o teste de SSR afirma a parte negativa (nada do projeto atravessa, e o
`digest` viaja), a forma do cartão fica sob guarda de fonte, e o pixel está aqui.

### Achado fora de escopo, não corrigido

`07-indisponivel-mobile.png`: o botão "Tentar de novo" vira um **círculo roxo sem rótulo** em
390px. A causa é anterior a esta fatia — a regra móvel `.ai-button { padding: 10px; font-size: 0 }`
foi escrita para o botão do herói (que tem ícone) e alcança também o botão do `state-card`, que
não tem. Não foi tocado: é do shell (F-025/F-026), e o único caminho de recuperação da tela de
erro ficar sem nome no celular merece decisão de quem é dono daquela superfície.

### Fora desta fatia, por decisão registrada

Ancoragem decisão→fase na timeline: `DEPENDENCY_BLOCKED` no gate de 27/08 — depende de
`phase_ref` carimbado pelo Pulse. A heurística por `decided_on` foi **recusada** no gate. A
Issue #62 não fecha por inteiro enquanto ela não existir.

> *Resolvido em 02/09/2026 — ver "Reabertura" no fim deste arquivo. A recusa da heurística
> continua valendo e ganhou teste.*

## Nota de fechamento (27/08/2026)

O escopo construível **neste** repositório está entregue e em `main`:

| Fatia | Tarefas | PR | O que entrou |
| --- | --- | --- | --- |
| Não-interface | T01–T05 | #73 | colunas de frescor/versão + migração `0031_projection_freshness`; `sync_snapshot` consome `observed_at`/`projection_version` com fallback rotulado; reconciliação anti-regressão (`projection.stale_rejected`); `build_dashboard` + schemas + OpenAPI; guarda client-safe medida por mutação |
| Superfície | T06–T08 | #75 | carimbo "Atualizado há X" vs. "Sincronizado há X" (rótulo honesto por origem), `StatePill` de stale e de indisponível, limiar por `PROJECTION_STALE_HOURS`; evidência desktop+mobile |

Critérios de aceite da Issue #62 atendidos neste repo: projeção autorizada com **proveniência e
frescor** explícitos; campos internal-only **excluídos por contrato e teste** (guarda client-safe,
ADR 0067); stale/indisponível **visivelmente representados**; eventos duplicados/fora de ordem
**não corrompem** a projeção (reconciliação por versão); isolamento cross-tenant intacto
(`test_authorization.py`/RLS); PRs abertos pelo harness, **merge humano**.

**Único critério em aberto:** "decisões/gates entendíveis sem termos internos", que depende da
ancoragem decisão→fase — `DEPENDENCY_BLOCKED` no `phase_ref` do Pulse (acima). Por isso a FDD está
`BLOCKED` e não `DONE`: a feature entrega valor hoje, mas o fechamento pleno é gate cross-repo, não
trabalho pendente aqui. Quando o Pulse carimbar `phase_ref`, a superfície correspondente do DAP
entra em fatia própria e a FDD pode ir a `DONE` sob decisão humana.

## Reabertura — a ancoragem decisão→fase (02/09/2026)

**A condição escrita acima se cumpriu**, e cumpriu-se dois dias depois de escrita: o Pulse
carimba `phase_ref` por decisão publicada desde **31/08/2026** (`biahflow/pulse#46`, ADR 0057 e
FDD 032 de lá). O campo passou a chegar no envelope e era **descartado na ingestão** — aparecia em
quatro documentos deste repositório e em zero linhas de código.

A superfície correspondente do DAP entrou em fatia própria, como esta nota previa, sob a
[ADR 0088](../../adr/0088-a-decisao-que-nao-sabia-que-fase-destravou.md). O que ela entrega:

| Item | Onde |
| --- | --- |
| `Decision.project_phase_id`, FK anulável `SET NULL`, resolvida na ingestão contra os ids das fases do mesmo envelope | `models/decision.py`, `integrations/biahflow.py`, migração `0042_decision_phase_anchor` |
| `DecisionOut.journey_phase_name` — rótulo e não id, pelo motivo do `meeting_title` | `schemas.py`, `docs/api/openapi.json`, `docs/contracts/one-visibility.json` |
| Nó `.journey-decision` na timeline, com título, racional e data, na forma do `.gate` do DAP r1 | `app/DashboardClient.tsx`, `app/globals.css` |
| Decisão sem fase: continua na aba Decisões, **sem nó e sem estado novo** | limite nomeado na ADR 0088 §3 |
| `projection.phase_ref_unresolved` para o carimbo que não resolve, com linha no runbook | `integrations/biahflow.py`, `docs/runbooks/alerts.md` |
| A recusa da heurística por data, agora com **teste** que a fixa | `test_the_phase_is_never_inferred_from_the_decision_date` |

### Portões (02/09/2026)

Banco dedicado à tarefa (`portal_wt62` no Postgres local, porta 5433), pelo eixo de estado
externo do `worktree-execution.md` (ADR 0078) — worktree isola git, não Postgres.

**O baseline foi medido antes da primeira edição, e é a única hora em que dá.** Refazê-lo depois
— guardar o diff e rodar de novo — devolve 511 *errors*, não 826 *passed*: o banco fica na
migração `0042` enquanto a árvore volta para a `0041`, e o `alembic upgrade head` do `conftest`
não acha a revisão. É o sintoma que a ADR 0078 descreve, com o nome trocado: colisão de estado
externo aparece como erro de *fixture*, não como conflito de *merge*.

- `pytest apps/api/tests` — **830 passed, 6 skipped, 0 failed**; baseline do `main` na mesma
  montagem: **826 passed, 6 skipped, 0 failed**. Quatro testes novos, todos em
  `test_biahflow_integration.py`: a âncora sobrevivendo a dois syncs, o rótulo publicado em vez
  do id, o `phase_ref` que não resolve (grava `NULL` e conta), e a recusa da inferência por data.
- `alembic upgrade head` + `alembic check` — *No new upgrade operations detected*.
- `npm run build` + `npm test` — **212 passed, 0 failed, 0 skipped** (209 no baseline; três
  testes de SSR novos).
- `npm run lint` — limpo. `npm run audit` — *auditoria limpa: 0 aviso(s)*. `npm run pins` —
  40 de 41 pinadas, a mesma do baseline (`variables.tf`, sem tag).

### Guarda medida por mutação (ADR 0065)

| Mutação | Efeito esperado | Medido |
| --- | --- | --- |
| `page.tsx` deixa de ler `journey_phase_name` (mapeia `null`) | o campo publicado fica sem leitor | ✖ *"o BFF consome todo campo que DecisionOut entrega"*, e só ela |
| o campo se chamaria `phase_name` | colide com `DeliverableAcceptanceOut.phase_name` no corpus por arquivo | ✖ *"a allowlist não guarda entrada que deixou de ser necessária"* — foi o que decidiu o nome |

### Capturas (`evidence/browser/`)

Chromium headless, 1280×900 @1.5 (desktop) e 390×844 @2 (mobile), sobre `next start` com o
stub de API e o cookie forjado do teste de SSR — a **mesma montagem** declarada em `runtime`
pela fatia T06–T08, e pela mesma razão: não há portal de pé desde 13/08 (ADR 0053) e as portas
locais são de outro ambiente. O script foi descartável.

`09`/`10` a decisão ancorada dentro da fase `Prove` (desktop, mobile) · `11` a fase `Welcome`,
que não tem decisão ancorada — **sem nó e sem rótulo de "sem fase"**, que é o limite nomeado da
ADR 0088 §3 fotografado.

O `09` mostra as duas coisas que a fatia precisa provar juntas e que nenhuma asserção de HTML
distingue sozinha: o selo **"Decisão da fase · aguardando"** (o `GateDecision` da ADR 0081) e o
**nó da decisão** logo abaixo, no mesmo painel. São duas superfícies distintas sobre a mesma
fase — o desfecho do gate e a decisão que a destravou —, e é por isso que o nó não se chama
`.journey-gate`.

**Recomendação:** a FDD 028 pode ir a `DONE`. Quem a move é decisão humana.

**Fica aberto, e é do outro lado:** o backfill das decisões publicadas antes de 31/08, que seguem
sem `phase_ref` na origem. Deste lado não há o que fazer que não seja inventar.
