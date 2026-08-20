# FDD — A busca do projeto

Fase 6, ADR 0024.

## Objetivo e não objetivos

**Objetivo.** Que a lupa do topbar faça o que a frase embaixo dela promete desde a primeira
versão da tela — buscar no contexto do projeto —, e que o critério de aceite da Fase 1 passe a
ser verdadeiro nas três camadas que ele nomeia: API, banco **e busca**.

**Não objetivos.** **Busca semântica**: cobraria por tecla com chave configurada e devolveria
ruído sem ela, e é o que o chat já faz — a diferença entre as duas superfícies é que uma
responde e a outra aponta (ADR 0024, alternativas). **Busca entre projetos**: o topbar é do
projeto corrente, e trocar de projeto é a URL desde a Fase 2 — *emendado em 19/08/2026 (ADR 0057):
**a frase descrevia a intenção e não o código**. `GET /api/v1/me/search` resolvia
`access.default_project`, que devolve a membership mais recente, e não aceitava `?project=`; o BFF
tampouco o mandava. Um cliente com dois projetos, vendo B por `?project=B`, recebia os resultados de
**A**. Corrigir era mudança de contrato da rota e ficou nomeado no `ROADMAP.md` em vez de
contornado.* — **e foi corrigido em 20/08/2026 (ADR 0059)**: a rota aceita `?project=`, o BFF o
manda, e projeto que o chamador não alcança é 404 e não a busca do projeto padrão. A emenda de
ontem fica porque ela é a razão de o parâmetro existir. **Decisões nos resultados**: não
havia aba de decisões, e um hit que leva a lugar nenhum é a classe de defeito que a ADR 0017
corrigiu — *entrou na ADR 0049, junto com a aba, casando também o racional*. **Filtros nas abas**: item aberto da Fase 2, outro controle, outra fatia. **Histórico
de buscas**: o termo é a pergunta de alguém e não é guardado em lugar nenhum, nem no log.

## Jornada e interface

O cliente clica na lupa, digita, e a lista aparece embaixo do campo — agrupada por espécie,
cada linha com o rótulo do que é ("Documento", "Reunião", "Pendência", "Marco", "Trecho de
documento"), o título e um detalhe.

Clicar leva ao destino, e o destino depende do que foi achado: uma linha do read model abre a
**aba** onde ela mora e **destaca a linha** (ADR 0057); um trecho de documento **abre a fonte**,
pela mesma URL assinada de vida curta que a citação do chat usa (ADR 0017).

A âncora vem pronta da API em `item_anchor`, pelo mesmo motivo do `tab` ao lado: a tela navega por
rótulo desde a Fase 2, e um segundo mapa no navegador envelheceria sozinho. É o mesmo formato
`<namespace>:<rótulo>` que o link do aviso usa (ADR 0056), e é a mesma âncora — o vocabulário mora
em `anchors.py` e nenhuma das duas superfícies o redefine. Ela só é aplicada se a tela **desenha**
aquela linha; uma decisão não ancora, e a aba abre sem realce e sem nota, o que está declarado em
`ANCHORLESS_HITS` com o motivo escrito.

Fechar a lupa esquece o termo. Não há histórico, não há sugestões e não há "buscas recentes".

Quatro estados, quatro frases — porque respondem a perguntas diferentes:

| Situação | O que a tela diz |
|---|---|
| Menos de 2 caracteres | "Comece a digitar para buscar no contexto do projeto." |
| Chamada em curso | "Buscando..." |
| A chamada falhou | "Não consegui buscar agora." |
| A API respondeu sem casamento | "Nada encontrado para “termo”." |

A última é a que importa: **nenhum caminho da tela fabrica resultado**. Uma busca que falhou diz
que falhou, na mesma forma que o chat passou a usar na ADR 0021.

## Permissões e estados

A rota é `GET /api/v1/me/search`, escopada como o dashboard: o projeto é o que a tela nomeia em
`?project=` e, na ausência dele, o de `access.default_project` (ADR 0059). Quem não tem membership
recebe **404** — nunca 403, nunca uma lista vazia que insinue que o projeto existe —, e **projeto
alheio recebe o mesmo 404**, nunca a busca do projeto padrão com 200.

| Situação | Resultado |
|---|---|
| Cliente do projeto, termo que casa | 200 com os resultados daquele projeto |
| Cliente do projeto, termo que não casa | 200 com `results: []` |
| Termo com menos de 2 caracteres | 200 com `results: []` — a busca não erra, ela não acha |
| Termo de outro projeto | 200 com `results: []` — e o dono do outro projeto acha o mesmo termo |
| Sem membership em projeto nenhum | 404 |
| Sem `Authorization` | 401 |
| Documento barrado pela varredura | o título aparece; o conteúdo, não; e não há `document_id` para abrir |

Nenhuma tabela nova, nenhuma policy nova e nenhum GRANT novo: a busca lê o que o papel de
requisição já lia. Uma busca que precisasse de privilégio novo estaria alcançando algo que a
tela não mostra.

## Telemetria

Um evento, `search.performed`, com `hits`, `kinds`, `term_length` e `duration_ms` — e o
`trace_id` que o `TraceMiddleware` já carimba (ADR 0018).

**Sem o termo.** É conteúdo do cliente (`docs/data-classification.md`); `term_length` explica
uma lista vazia sem gravar o que a pessoa procurava. E **sem `audit_log`**: o download é
auditado porque tira o arquivo do portal, procurar é ler o que já está nas abas, e uma linha
por tecla afogaria a trilha que o `incident-response.md` manda ler.

## Critérios de aceite

| Critério | Coberto por |
|---|---|
| As quatro espécies que as abas mostram são achadas | `test_search.py::test_each_kind_the_tabs_show_is_reachable` |
| O clique leva à aba certa, com o rótulo vindo da API | `test_the_hit_carries_the_tab_it_belongs_to`, `tests/e2e/search.spec.ts` |
| **E à linha, não só à aba** (ADR 0057) | `test_the_hit_carries_the_row_it_points_at_and_not_only_the_tab`, `tests/e2e/search.spec.ts` |
| **A decisão diz que não tem linha, em vez de inventar uma** | `test_the_decision_says_it_has_no_row_instead_of_inventing_one`, `tests/e2e/search.spec.ts` |
| **O espaço de nomes da busca é um que a tela desenha, na aba que o clique abre** | `test_item_anchor.py` — as quatro guardas que a ADR 0057 provou por mutação |
| "reuniao" acha "Reunião", e "MIGRAÇÃO" acha "Migração" | `test_the_search_folds_accents_and_case` |
| Um termo dentro do documento é achado, com a página e o id | `test_a_term_inside_a_document_is_found_with_the_page` |
| O texto do documento também é achado sem acento | `test_the_document_text_is_found_without_its_accents_too` |
| **O termo exclusivo do outro projeto não aparece — e o dono dele acha** | `test_a_term_only_the_other_project_uses_finds_nothing` |
| A RLS recusa mesmo com o filtro da aplicação apontando errado | `test_the_database_refuses_even_when_the_app_filter_points_elsewhere` |
| Sem membership, 404 | `test_authorization.py::test_search_requires_a_project` |
| Termo curto não é erro | `test_a_term_too_short_finds_nothing_and_is_not_an_error` |
| `%` e `_` são texto, não sintaxe de consulta | `test_the_wildcards_of_like_are_not_a_query_language` |
| Documento barrado pela varredura não oferece o que abrir | `test_a_document_barred_by_the_scanner_offers_nothing_to_open` |
| Decisão não é alcançável enquanto não houver aba | `test_a_decision_is_not_reachable_because_no_tab_shows_one` |
| O teto é por espécie antes de ser geral | `test_the_result_is_capped_per_kind` |
| O BFF leva a sessão e o `trace_id`, e recusa anônimo | `tests/rendered-html.test.mjs` (três casos da rota `/api/search`) |
| A tela não fabrica resultado, e o campo está ligado | `tests/rendered-html.test.mjs` — a guarda de forma |
| A fixture do SSR casa com o contrato publicado | `tests/api-contract.test.mjs::…/me/search` |
| No navegador: digitar acha, clicar navega, e nada encontrado é nada encontrado | `tests/e2e/search.spec.ts` (três casos) |

## Riscos

**A busca é lexical.** "Quanto tempo temos para cancelar" não acha "cláusula de rescisão"; quem
responde isso é o chat. O risco é de expectativa, não de correção, e está declarado na ADR.

**O índice GIN é sobre uma expressão.** Se alguém mudar a dobra em `textfold.py` sem regerar o
índice, a consulta continua **correta** e para de usar o índice — fica lenta em silêncio. É por
isso que os três lugares leem da mesma função em vez de repetir o texto, e por isso a migração
0019 diz isso no próprio docstring.

**Um projeto com muito conteúdo satura o teto.** Cinco por espécie, vinte no total. Sem
paginação de propósito: um popover de topbar não é uma tela de resultados, e a hora em que
alguém precisar rolar é a hora de haver uma página de busca — o que muda a jornada e pede
decisão de produto.
