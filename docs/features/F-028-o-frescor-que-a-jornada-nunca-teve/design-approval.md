# Design Approval Package — F-028 · O frescor que a jornada nunca teve

Classification: INTERFACE_CHANGE (superfície de uma `INTEGRATION_CHANGE`)
Revision: 1
Status: Approved
Date: 2026-08-26
Produced by: Claude Opus 4.8 (1M context), sob a Engineering OS

> Governado por `docs/engineering-os/workflows/design-approval.md`. Evidência para gate humano.
> Não é implementação. Um agente produz e revisa; **não aprova**.

## O que este pacote decide

A jornada já é renderizada (`JourneyPanel`, "Você está aqui"). Este pacote decide **o que a tela
mostra sobre a saúde do próprio dado**: o carimbo de frescor, e os estados em que o dado está velho
ou indisponível. A ADR 0026 **removeu** um "Atualizado há 2 dias" que era frescor **inventado** — a
decisão de hoje é *não* carimbar por falta de timestamp honesto. Este pacote reintroduz o carimbo,
mas **honesto**: derivado de um `observed_at` real do contrato de projeção, e com um estado **stale**
explícito quando a idade cruza o limiar. Decide também **decisões/gates ancorados na timeline**.

O que está em aberto para o gate: o tratamento visual de frescor/stale/indisponível (três estados
distintos), e como uma decisão/gate aparece ancorada à fase que desbloqueou.

## Approval record

| Campo | Valor |
| --- | --- |
| What was approved | **visual e cópia** (as *Open questions* seguem em aberto — a aprovação não as resolve) |
| Approved by | Daniel Campos |
| Date | 26/08/2026 |
| Revision approved | **1** |
| Explicitly **not** approved | Exibição de qualquer campo internal-only (GitHub/CI/ClickUp/LangGraph/LangSmith/margens — ADR 0067) · o limiar numérico exato do stale (é decisão de operação, não de design) · tema escuro |

## Artifact

| File | O que é |
| --- | --- |
| `design/one-journey-freshness.html` | Renderização auto-contida: a timeline da jornada com o carimbo de frescor, o estado **stale**, o estado **indisponível**, o estado **encerrado**, e uma decisão/gate ancorada à fase. Abre com duplo clique, sem build/toolchain/rede. |
| `../F-025-.../design/captures-r4/` | A pele aprovada (F-025) que a timeline veste. |

**Capturas** (passo do gate, Chromium headless, 1280 desktop / 390×844 mobile): frescor recente,
stale acima do limiar, indisponível, encerrado, e a timeline com decisão/gate.

## Surfaces and states included

| Superfície | Estado | No pacote |
| --- | --- | --- |
| Timeline da jornada | fase atual, fases concluídas/bloqueadas | sim |
| Timeline — decisão/gate ancorada à fase | client-safe (title/racional/data) | sim |
| Carimbo de frescor | recente ("Atualizado há X") | sim |
| Carimbo de frescor | **stale** (acima do limiar — pill + mensagem) | sim |
| Projeção | **indisponível** (falha de fetch) | sim |
| Projeção | **encerrado/removido** (`archived_at`/`source_deleted_at`) | sim (já existe; a jornada respeita) |
| Timeline | carregando | sim |

Deliberadamente **fora**:

| Superfície | Por que |
| --- | --- |
| Qualquer campo internal-only | ADR 0067 proíbe atravessar a fronteira; o teste de filtro reprova. |
| Risk register / economia interna | idem. |
| Estado de PR/CI | idem. |

## Provenance of visual values

Design system: [`docs/design/one-design-system.md`](../../design/one-design-system.md), lido em
26/08/2026; timeline-origem: `JourneyPanel` + `readOnlyReason` (`app/DashboardClient.tsx`). **CSS
vence em divergência.**

| Valor | Origem | Novo? |
| --- | --- | --- |
| Trilha, dots (done/active/locked), pills de fase | `JourneyPanel` / F-025 | não |
| Padrão pill + mensagem para estado honesto | `readOnlyReason` (ADR 0036/0037) | não — reusado |
| Tokens de cor/raio/foco, `StatePill` | F-025 | não |
| **Carimbo de frescor "Atualizado há X"** | — | **sim — decidido aqui** (honesto, deriva de `observed_at`) |
| **Estado stale** (pill `warning` + "pode estar desatualizado") | reusa o padrão de `readOnlyReason` | **sim — decidido aqui** |
| **Nó de decisão/gate na timeline** (title/racional/data ancorado à fase) | `Decision` já projetado, mas como lista | **sim — a ancoragem à fase é nova** |

Nenhum token de cor novo. Stale usa `warning`; indisponível usa `danger`; encerrado usa cinza — os
três já são tokens, e a distinção de cor é o que os torna três estados e não um.

## Delivered vs reserved

| Elemento | Esta fatia | Reservado para | Vira real quando |
| --- | --- | --- | --- |
| Carimbo de frescor + estado stale | entrega | — | — |
| Decisão/gate ancorada à timeline | entrega | — | — |
| Reconciliação/versão (backend) | **sem superfície** | ADR do contrato | contrato versionado existir |
| Limiar numérico do stale | não fixa no design | operação | decisão de operação |

Nada inerte é renderizado: o carimbo só aparece com `observed_at` real; o stale só acima do limiar.

## Decisions this package carries

1. **O carimbo volta, honesto.** A ADR 0026 removeu o carimbo inventado; este o traz derivado de um
   `observed_at` real. Sem o insumo, não há carimbo — a implementação não pode fabricá-lo.
2. **Stale, indisponível e encerrado são três estados distintos** — dado velho (há dado, pode estar
   desatualizado), sem dado (falha de fetch), e projeto encerrado/removido na origem. Cores e
   mensagens diferentes; colapsá-los mentiria sobre qual é o caso.
3. **Decisão/gate mora na timeline, ancorada à fase** — não mais só uma lista solta: o cliente vê qual
   decisão destravou qual fase, dentro do que é client-safe (title/racional/data; nunca o interno).
4. **Nada internal-only atravessa** — a fronteira da ADR 0067 é desenho *e* teste; a tela não mostra
   o que o contrato não deixa passar.

## Open questions

- **`observed_at` da origem ou `synced_at` da cópia?** Proposta: `observed_at` do contrato (mede a
  idade do dado na origem). Se o Pulse não carimbar, fallback declarado para a hora da cópia, **dito
  como tal** — nunca a hora da cópia disfarçada de frescor da origem.
- **Limiar do stale** (quantas horas até "pode estar desatualizado"): decisão de operação, não de
  design; a tela só reflete o resultado.
- **Ancoragem decisão→fase:** por marcação explícita do Pulse (preferido) ou heurística por data
  (`decided_on` × janela da fase)? Declarar o que fica de fora se ambíguo.

## Notes for the implementer

**Intencional e precisa sobreviver.** O carimbo só com `observed_at` real; os três estados distintos
com cores distintas; a decisão ancorada à fase mostrando só campos client-safe; o padrão pill+mensagem
de `readOnlyReason` reusado (não reinventar).

**Ilustrativo, não especificação.** "Atualizado há 2 h", nomes de fase e decisão, datas. A tela só
desenha o que o contrato entregou.

**O que o artefato não mostra e a implementação garante.** Que a reconciliação não regride a projeção
sob evento fora de ordem; que a guarda de filtro reprova campo internal-only; isolamento cross-tenant;
`role="status"` no carimbo/estado; nada anima; `prefers-reduced-motion` respeitado.

**Armadilha.** Carimbar a hora da cópia como se fosse a observação da origem é a falsa precisão que
`results.py` recusa e que a ADR 0026 removeu. Se o insumo honesto faltar, o design manda **não**
carimbar, não improvisar.
