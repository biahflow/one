# F-025 — Evidence

O handoff de revisão. Consolida referências; **não substitui** os artefatos que aponta. Um resumo
aqui nunca é mais autoritativo que a evidência que ele resume.

## Round

```text
round: 1
reviewed_commit_or_state: a branch `o-nome-que-a-tela-ainda-nao-sabia`, de `dc10ff3` a `HEAD`
authorization: seleção humana da Issue #46 em 25/08/2026; Design Approval revisão 4, visual e cópia, aprovada em 25/08/2026
```

## 1. Contrato e plano

| Artefato | Onde |
| --- | --- |
| Feature Contract | `docs/fdd/025-o-nome-que-a-tela-ainda-nao-sabia.md` |
| Design Approval Package | `docs/features/F-025-o-nome-que-a-tela-ainda-nao-sabia/design-approval.md` — revisão 4, `Approved` |
| Artefato aprovado | `design/one-dap-r4.html` + `design/captures-r4/` |
| Execution Plan | `plan.md` — `PLAN_VALID`, com `PLAN_DEVIATION 01` registrado |
| Task Contracts | `tasks/T01.md` a `tasks/T05.md` |
| Decisão registrada | `docs/adr/0069-o-nome-que-a-tela-ainda-nao-sabia.md` |

Classificações declaradas: `INTERFACE_CHANGE` e `BROWSER_REQUIRED`.
Classificação de paralelismo: **`PARALLELISM_RISK`** → execução sequencial, um Builder ativo, um
worktree (`../portal-cliente-issue-46`), uma branch.

## 2. BASELINE

Medido em 25/08/2026 sobre `main` @ `7c58d2a`, **antes** de qualquer trabalho desta fatia.

| Perfil | Comando | Resultado |
| --- | --- | --- |
| `lint` | `npm run lint` | limpo |
| `web-unit-contract` | `npm test` | 139 passed / 0 failed |
| `api-unit-integration` | `pytest apps/api/tests` sem o de backup | **2 FAILED** |

**As duas falhas eram pré-existentes e não são atribuíveis a esta fatia:**
`test_every_accepted_adr_has_a_line_in_the_roadmap` e
`test_every_adr_status_is_a_word_this_guard_knows`, causadas pelos commits `a5d8e2e` e `7b36961`
(as ADRs 0067/0068 declaravam `Status: Accepted`, palavra que a guarda não lê, e não tinham linha
no `ROADMAP.md`).

Foram consertadas em **commit próprio e separado** (`dc10ff3`), como decisão registrada de split:
sem isso o PR não alcança `CI_GREEN`, que é critério de aceite da Issue.

## 3. CHANGE

Um commit por tarefa, em ordem de caminho crítico. O `BUILD REPORT` completo de cada Builder está
preservado no histórico de execução da sessão; abaixo, a atribuição por tarefa.

| Task | Commit(s) | O que entregou |
| --- | --- | --- |
| — | `dc10ff3` | baseline verde: cabeçalho das ADRs 0067/0068 e as duas linhas no roadmap |
| — | `5577f94` | Feature Contract (FDD 025) |
| — | `bf897d0`, `8e7a21c`, `e5a946d`, `a18f0f1` | Design Approval Package, revisões 1 a 4, e o plano |
| — | `d1ae7c1` | achado de revisão da T01 + emenda de T02/T04 (`PLAN_DEVIATION 01`) |
| T01 | `03fffcd` | tokens no `@theme`, os quatro hex de marca eliminados, `one-design-system.md` |
| T02 | `6426029`, `5576551` | `components/one/` (Brand, StatePill, Button) + o reparo dos quatro achados |
| — | `8d73ad3` | errata dos dois pixels no pacote |
| T03 | `38c22a8`, `7c88151` | a varredura do nome; o favicon e o `og.png` |
| T04 | `d870fbf`, `58f4892` | a guarda de admissão de token; a vitrine `/admin/design` |
| T05 | `00fcb54` | a evidência de navegador e o manifesto |

## 4. Validação

Na revisão final da branch, **executada e conferida pelo revisor**, não só reportada pelos Builders:

| Perfil | Comando | Resultado |
| --- | --- | --- |
| `lint` | `npm run lint` | limpo |
| `web-unit-contract` | `npm test` | **142 passed / 0 failed** (139 do baseline + 3 da guarda nova) |
| `api-unit-integration` | `pytest apps/api/tests` sem o de backup | **659 passed / 0 skipped / 0 failed** |
| `e2e` | `npm run test:e2e` com a pilha de pé | **38 passed** |
| `security` | `npm run audit` | 0 aviso, 0 aceito com prazo |
| `supply-chain-pins` | dentro do perfil de API | verde |
| deriva de migração | `alembic check` | `No new upgrade operations detected` |
| deriva de contrato | `python -m portal_api.openapi --write` + `git diff` | sem deriva |
| `browser` | `node scripts/capture-browser-evidence.mjs` | 8 capturas, 1,29 MB |

**Medição da guarda nova por mutação**, feita duas vezes de forma independente — pelo Builder e pelo
revisor. Token inventado acrescentado ao `@theme` → **vermelho**, nomeando o token; retirado →
**verde**. Mais três mutações do Builder: `@theme` renomeado, `@theme` esvaziado e isenção
desnecessária, todas vermelhas pelo fail-closed e pela asserção de obsolescência.

### Validação pulada, e por quê

- `test_backup_restore.py` — job próprio no CI; exige MinIO com as quatro senhas de papel e cliente
  `pg_dump` compatível. Nada nesta fatia toca backup.
- `codeql` e `dependency-review` — desligados por variável no repositório, e **não por escolha desta
  fatia**: o primeiro pede code scanning habilitado; o segundo exige Advanced Security, que o plano
  do repositório privado não tem. A exceção é anterior e está documentada no próprio workflow.

## 5. Integração

Uma branch, um worktree, um Builder ativo por vez, na ordem `T01 → T02 → {T03, T04} → T05`. Sem
merge local em `main`. O PR é o caminho canônico.

## 6. FINAL

Evidência de navegador em `evidence/browser/`, com `manifest.json` declarando por captura: SHA da
revisão, data, rota, ator, viewport, recorte, bytes e `sha256`.

**O estado de revisão/decisão do cliente não foi encenado.** Ele é `reserved` no pacote de design —
não existe rota, evento nem escrita —, e o manifesto o declara como tal, apontando para a captura
congelada do artefato em vez de fingir uma tela.

## 7. Review

`REVIEW_PASS` na revisão final, com **um round de reparo** no caminho.

| Round | Alvo | Resultado |
| --- | --- | --- |
| 1 | T01 | `REVIEW_FINDINGS` — sete tokens sem consumidor num commit que publicava a regra contrária. `REVIEW_REPAIR_TASK_SCOPE` → virou `PLAN_DEVIATION 01`, com o consumo exigido em T02 e a guarda em T04 |
| 2 | T02 | `REVIEW_FINDINGS` — quatro achados, todos `REVIEW_REPAIR_TASK_SCOPE`: DOM inválido (`<div>` dentro de `<span>`), sidebar recolhida sem marca, 42 px onde o pacote prometeu 44, e `.btn--danger` sem hover. Reparados em `5576551`; `feedback_iterations: 1` |
| 3 | T03 | `REVIEW_PASS`. A tarefa reportou uma afirmação falsa **no pacote de design** (a fonte), confirmada por medição do revisor e corrigida na revisão 4 |
| 4 | T04, T05 | `REVIEW_PASS`. Guarda medida por mutação pelo revisor; evidência conferida contra `captures-r4/` |

```text
feedback_iterations: 1
ci_repair_iterations: 0
```

Nenhum achado exigiu decisão humana nova. Nenhum foi `REVIEW_REPAIR_SCOPE_AMBIGUOUS`.

## 8. Desvios, riscos e decisões humanas pendentes

### Desvio de plano

`PLAN_DEVIATION 01` — a guarda de consumo de token entra em T04. Registrado em `plan.md` com
tarefa, estado planejado, estado real, impacto, resolução e autoridade.

### Riscos que ficam, medidos e não consertados de carona

1. **O `docker-compose.yml` passa `NOTIFICATIONS_FROM_NAME` só ao serviço `api`, e quem envia o
   e-mail é o worker.** Pré-existente. Hoje inofensivo porque o default do `config.py` coincide;
   quem sobrescrever a variável no `.env` verá o nome antigo no remetente.
2. **Não existe `apple-touch-icon`**, embora o pacote nomeie três lugares para o tile.
3. **O anel de foco herda `transition-colors`**, que no Tailwind v4 inclui `outline-color`: nos
   ~150 ms seguintes ao `Tab` ele exibe a cor de origem antes de virar a da marca. O valor final
   está correto. Pré-existente.
4. **Um `.env` no diretório faz `pytest` reportar 419 pulados** com a mensagem "PostgreSQL is not
   reachable", com o Postgres de pé — porque o arquivo aponta o banco para o hostname do contêiner e
   o `pydantic-settings` o lê. No CI não acontece: o job `api-quality` não cria `.env`, e lá um skip
   reprova. Achado desta sessão, registrado na ADR 0069.
5. **`.state--0..3` convive com `.state-pill--*`.** Trocar umas pelas outras no produto inteiro está
   fora de escopo desde T02.

### Decisões humanas pendentes

- **Merge do pull request.** O harness comitou, empurrou e abriu o PR; **não mergeia e não liga
  auto-merge**.
- **`DONE` da F-025.** Merge de PR é evidência de integração de engenharia, não aceitação de cliente
  nem `DONE` operacional.
