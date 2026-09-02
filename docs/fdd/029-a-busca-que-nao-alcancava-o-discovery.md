# FDD — A busca que não alcançava o Discovery

Fase 7, ADR 0087. Fecha o item aberto da ADR 0086 e a Issue `biahflow/one#102`.

**Classificação:** `BROWSER_CONDITIONAL`. Não há superfície nova — são linhas novas na lista de
resultados que já existe, e `data-item` nos blocos que a aba já desenha. Não há Design Approval
Package, porque não há desenho a aprovar.

## Objetivo e não objetivos

**Objetivo.** Que o termo digitado na lupa alcance as quatro listas que a aba Discovery mostra —
Process (com etapas), Findings, Pain Points e o Improvement Opportunity Backlog —, e que o clique
caia **na linha**, não só na aba. É a regra da ADR 0024 §5 aplicada ao que a ADR 0086 acrescentou à
tela: *só entra o que o cliente já alcança por alguma aba*, e desde a ADR 0086 ele alcança quatro
listas a mais.

**Não objetivos.** **Busca semântica**: a busca é lexical desde a ADR 0024, e quem responde à
pergunta em linguagem natural é o chat. **Tela de publicação do Discovery**: é `biahflow/pulse#108`,
do outro lado. **Índice de banco** para as quatro tabelas: as cinco espécies de read model já casam
por `ILIKE` sem índice, e criar um seria decisão própria com o custo de escrita do fan-out. **Buscar
dentro de `Evidence`**: é JSONB e não coluna, e o guard de visibilidade da ADR 0082 não enxerga lá
dentro — a proteção equivalente é a lista branca da ingestão. **Expor qualquer campo barrado por
ela** (`raw_excerpt`, `content_hash`, o `rationale` da priorização).

## Jornada e interface

O cliente abre a lupa e digita uma palavra que aparece num processo mapeado, num achado, numa dor
ou numa oportunidade do backlog. A lista de resultados mostra a linha com o rótulo da espécie —
`Process`, `Finding`, `Pain Point`, `Improvement Opportunity`, que são os títulos que a própria aba
desenha —, e o clique abre a aba **Discovery** com a linha destacada pelo anel do `.is-anchored`.

Quando o casamento veio de uma **etapa** do processo, o resultado diz qual: o processo aparece com
o nome da etapa embaixo, e sem isso o cliente veria um processo na lista sem ter como saber por que
ele apareceu.

Todo resultado de achado carrega o **estado epistêmico** ao lado — `Fato`, `Hipótese` ou `Pergunta
em aberto`, os mesmos três rótulos que a aba mostra no `StatePill`. Uma hipótese nunca chega ao
cliente parecendo afirmação.

Enquanto o Pulse não publicar Discovery, as quatro listas estão vazias e a busca não devolve
resultado nenhum delas — o mesmo estado em que a aba já vive, e ela diz isso.

## Critérios de aceite

| # | Critério |
|---|---|
| 1 | Um termo que só existe numa das quatro listas devolve resultado, e o hit traz `tab="Discovery"` |
| 2 | Um termo que só existe numa coluna de `ProcessStep` devolve o **processo**, com o nome da etapa no `detail` |
| 3 | Um termo que só existe numa `SolutionHypothesis` devolve a **oportunidade** que a contém |
| 4 | Um processo cujo nome **e** cuja etapa casam produz **uma** linha, com `detail` vazio |
| 5 | Nenhum hit de `finding` chega sem estado epistêmico legível no `detail` |
| 6 | Os três rótulos epistêmicos são idênticos nos dois deployables, e uma guarda reprova a divergência |
| 7 | A âncora do Discovery é `<namespace>:<id da origem>`, e a das outras cinco espécies não muda |
| 8 | Os quatro namespaces estão em `anchors.ALL`, em `HIT_ANCHOR` e como `data-item` da aba — as três listas fecham |
| 9 | O `data-item` está **dentro** do componente que a aba Discovery abre |
| 10 | Um termo que só a **outra conta** usa não devolve nada, e o dono daquela conta o acha pela mesma rota |
| 11 | Com `TenantContext` forjado sob `rls_session`, o Discovery da outra conta devolve zero linhas |
| 12 | Projeto que o chamador não alcança responde **404**, nunca 403 |
| 13 | Trechos de documento continuam alcançáveis num projeto com vinte linhas de read model casando |
| 14 | O termo digitado não vai para o log nem para `audit_log` |
| 15 | O contrato publicado não muda: nenhum campo novo em `SearchHitOut` |
| 16 | Dor e oportunidade saem com `detail` **vazio**: nada que a aba não desenhe, e nenhum código cru da origem |
| 17 | O hit de reunião traz `Realizada`/`Agendada` — o mesmo mapa do BFF, com a mesma queda para o código cru |

## Telemetria

**Nenhum evento novo, e nenhuma linha nova em `docs/runbooks/alerts.md`.** `search.performed`
continua levando `hits`, `kinds`, `term_length` e `duration_ms`; as quatro espécies aparecem em
`kinds`, que é o campo que já existia para dizer o que a busca alcançou. Um evento por espécie nova
seria um acontecimento inventado para um dado que já viaja.

## Testes

| Teste | O que prova |
|---|---|
| `test_each_discovery_list_is_reachable_by_a_term_only_it_uses` | Critério 1 |
| `test_the_process_is_found_by_a_column_of_its_step_and_the_hit_is_the_process` | Critério 2 |
| `test_the_improvement_opportunity_is_found_by_its_solution_hypothesis` | Critério 3 |
| `test_a_process_whose_name_and_step_both_match_is_a_single_row` | Critério 4 |
| `test_no_finding_reaches_the_client_without_its_epistemic_label` | Critério 5 |
| `test_ready_made_labels.py` (cinco asserções) | Critérios 6 e 17, nas duas direções, sobre o produtor e sobre a queda |
| `test_the_search_never_shows_more_of_a_row_than_the_tab_does` | Critério 16 |
| `test_the_meeting_hit_says_realizada_and_not_held` | Critério 17, pelo stack HTTP |
| `test_the_discovery_hit_anchors_by_the_source_id_and_not_by_the_label` | Critério 7 |
| `test_every_anchored_kind_is_rendered_by_the_screen` | Critério 8 |
| `test_the_anchor_lands_on_the_tab_the_link_opens` | Critério 9 |
| `test_a_discovery_term_only_the_other_account_uses_finds_nothing` | Critério 10 |
| `test_the_database_refuses_the_discovery_of_another_account` | Critério 11 |
| `test_a_project_the_caller_does_not_reach_is_404_and_never_the_default` | Critério 12 (regra 6 do `AGENTS.md`) |
| `test_the_document_excerpt_survives_a_screenful_of_read_model_rows` | Critério 13, com Postgres |
| `test_search_quota.py` (cinco asserções) | Critério 13, na aritmética e **sem** Postgres |
| `rendered-html.test.mjs` — "o link do aviso destaca a linha" | Critérios 7 e 9 no HTML do SSR |
| `test_openapi_contract.py` + `npm run test:contract` | Critério 15 |

O critério 14 não ganhou teste novo: `search.performed` não foi tocado, e `test_telemetry.py` já
varre o AST atrás de mensagem interpolada e de campo com nome de segredo.

## Casos de eval de IA

Nenhum. A fatia não muda prompt, recuperador, modelo nem ferramenta — a busca é uma consulta ao
Postgres, e `conversation_message` continua não sendo fonte de recuperação.

## Riscos

**A fatia não devolve resultado nenhum ao cliente enquanto `biahflow/pulse#108` não entregar a tela
de publicação.** É a mesma posição em que a `#90` foi construída e mergeada, e o custo de ligá-la
depois — com a aba já povoada e a regra da ADR 0024 vencida por semanas — é maior que o de ligá-la
agora.

**A busca continua lexical.** "O que trava o fechamento?" não acha um `PainPoint` cujo texto não
contenha as palavras digitadas. É o limite declarado da ADR 0024, e ele vale igual aqui.

**Dor e oportunidade não têm `detail`, e um dia podem precisar.** Hoje o título basta e o `status`
não serve — é código cru, e a aba não o desenha. Se algum bloco passar a desenhá-lo, o caminho
está aberto e tem forma: rótulo pronto saindo da API com guarda comparando os dois deployables, que
é o que a reunião ganhou nesta mesma fatia.

**O rótulo de reunião cai para o código cru num estado que a tabela não conhece.** É a decisão, e o
preço é o cliente ver `cancelled` se a origem inventar esse estado antes de este lado saber lê-lo.
Vazio seria pior — esconderia que a origem passou a dizer algo novo —, e não há guarda de
completude possível porque `Meeting.status` é `String` por decisão do modelo. Quem percebe primeiro
é quem lê a tela, não um teste: é o limite conhecido.

**Sem índice, o casamento é varredura.** Vale enquanto o Discovery de uma conta for dezenas de
linhas, que é a ordem de grandeza de um levantamento. Se virar milhares, o índice passa a ser
decisão com medição, e o argumento contrário (custo de escrita no fan-out) está escrito na ADR.
