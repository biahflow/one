# Evidência — F-027

**Estado:** implementada (T01–T04 não-interface; T05–T08 superfície). Aguarda merge — gate humano.

## Baseline (26/08/2026, `main`)

- Superfície de aceite existe **desenhada e reservada** na F-025 §10 (não renderizada).
- `PhaseDeliverable` **não tem** identidade estável (`external_ref`) e é apagado/recriado a cada sync
  — pré-requisito medido para o aceite (dossiê #61).
- Integração Biahflow é **unidirecional** (só `httpx.get` do snapshot; nenhum `post` de volta) — o
  `client.accepted` de retorno é lacuna verde.
- Precedentes de tabela cliente-escrita imutável: `pending_item_comment` (ADR 0032, migração 0021),
  `conversation_message.feedback` (ADR 0015, migração 0012).

## Execução (27/08/2026)

Gates cumpridos: ADR 0077 aceita · DAP r1 `Approved` (26/08) · Revisão 2 do plano aprovada (27/08),
com as *Open questions* resolvidas no gate — aba própria "Revisão" com contador, e comentário
**opcional** em Aprovar.

### Não-interface (T01–T04)

| Prova | Resultado |
| --- | --- |
| Bateria da API | **703 passed, 0 failed** (baseline `main`: 688) |
| Imutabilidade **por privilégio** | `\dp portal.deliverable_acceptance` → `portal_app=ar` — INSERT e SELECT, **sem `w`, sem `d`** |
| `test_rls_isolation` | aceite de outro tenant invisível; `INSERT` cross-tenant rejeitado; app role não reescreve nem apaga |
| `test_authorization` | **404 nunca 403** no GET e no POST; 409 em projeto encerrado, **depois** do 404 |
| Segunda decisão | **acrescenta**, não sobrescreve (teste dedicado) |
| Aviso interno | sai para o time, **não** chega ao cliente; não avisa quem decidiu; dedupe por `(external_ref, action)` |
| `alembic check` | sem deriva; cadeia linear `0030→0031→0034→0035→0036`, head único |

### Superfície (T05–T08)

| Prova | Resultado |
| --- | --- |
| `npm test` | **167 passed, 0 failed, 0 skipped** (baseline da branch: 157) |
| `npm run test:contract` | **95 passed, 0 failed** |
| `npm run lint` / `tsc --noEmit` | limpos |
| `inertButtons()` | verde — os controles **agem**: as capturas 02/03 saem de cliques reais atravessando a Server Action |
| Os cinco rótulos | tons do pacote; **`done` em cinza** ("Concluído pela operação") — o cliente não o declara |
| merge ≠ aceite | "Entrega de engenharia" e "Seu aceite" em metades separadas, com a linha `merge de engenharia ≠ seu aceite` |
| Supersessão visível | decisão anterior **riscada** e marcada `SUPERADA`; nenhuma affordance de edição |
| Foco de teclado | alcançado em 18 tabuladas, `focus-visible`, `outline` `rgb(110,86,207)` = `--color-focus` |

Capturas em [`evidence/browser/`](evidence/browser/) — aguardando / ajuste-pedido / aprovado em
1440×900 e 390×844, mais foco, vazio, erro e não autorizado (404). O `manifest.json` separa o que
elas **provam** do que **não provam**, e carimba o `sha256` do `git diff HEAD` como procedência.

### Dívida de allowlist fechada

Saíram 5 linhas (`NOT_CALLED` da rota de aceite e 4 de `NOT_SENT`) mais a constante
`AWAITING_DESIGN_APPROVAL`: o motivo delas era o gate de design, e o gate caiu. Entraram 4 linhas
**sem prazo**, porque a razão é estrutural e não adiamento — dois ecos do caminho da rota (forma do
`PendingCommentsOut.pending_item_id` já aceito) e dois campos denormalizados na escrita **para o
outro lado** (ADR 0077).

## Fica aberto

- Mecanismo do retorno ao Pulse (ADR 0077 §Aberto) — a persistência do evento é a fonte da verdade;
  a exposição espera decisão com o lado Biahflow.
- `superseded`/`cancelled` como rótulo visual — exigem revisão de design própria.
- `client_review` e `done` aparecem na **legenda** da escada, não em card: nada neste produto os
  emite hoje, e fabricá-los seria a tela afirmando o que a API não disse.
- Decisão humana pendente: **merge**.
