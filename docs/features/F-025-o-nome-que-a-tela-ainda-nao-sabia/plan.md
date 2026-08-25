# F-025 — Execution Plan

Produzido pelo Planner a partir do Feature Contract aceito
([FDD 025](../../fdd/025-o-nome-que-a-tela-ainda-nao-sabia.md)) e do Design Approval Package
**revisão 2, aprovado em 25/08/2026**. O plano diz **como** a feature aceita é executada; não
altera requisitos, não escolhe harness ou modelo, e não concede aprovação.

## FEATURE EXECUTION PLAN

```text
feature_id: F-025
goal: Dar ao One identidade de produto e fundação de design consumível — tokens semânticos,
      primitivas com consumidor real, vitrine viva e a terminologia One em toda superfície que
      o cliente alcança — sem mudar comportamento de autenticação, autorização, isolamento de
      tenant ou fluxo de dado.

assumptions:
  - O DAP revisão 2 está aprovado (visual e cópia) e é a especificação visual desta execução.
  - O baseline está verde: 659 testes de API, 139 de web, lint limpo, medido em 25/08/2026.
  - A pilha local sobe (`docker compose up -d --build`) e é o runtime real desta validação;
    o portal não está implantado em nuvem desde 13/08/2026 (ADR 0053) e isso não muda aqui.
  - Nenhuma migração Alembic é necessária: não há mudança de modelo, policy ou privilégio.

risks:
  - A varredura do nome erra por omissão. Mitigado por critério de aceite executável (um `grep`
    que só pode voltar com prosa histórica), não por leitura.
  - `docs/api/openapi.json` casa byte a byte com o gerador; esquecer de regenerar reprova.
  - Mexer no `SYSTEM_PROMPT` sem trocar `PROMPT_VERSION` reprova, e regravar a versão é recusado.
  - `seed.py` e o realm do Keycloak precisam mudar no mesmo commit; divergência produz alguém
    que autentica e não casa com linha nenhuma, o que aparece muito depois como "todo mundo vê 404".
  - Três cores mudam de valor e atingem tela existente. É correção de contraste medida, não gosto,
    mas as asserções de HTML renderizado precisam continuar verdes.

tasks:
  - id: T01
    role: builder
    goal: Os tokens do One no `@theme`, os quatro hex escritos à mão eliminados, e a linguagem
          extraída para documento citável.
    scope: app/globals.css (bloco @theme e as regras que hoje escrevem rgba à mão);
           docs/design/one-design-system.md (novo); docs/project-context.md (linha de fonte).
    out_of_scope: Renomear classe de CSS existente. Redefinir a base de espaçamento do Tailwind.
                  Qualquer arquivo .tsx. A cópia da tela.
    expected_areas: web
    acceptance_criteria:
      - O `@theme` declara `--color-info-50/600`, `--color-focus`, `--color-surface`,
        `--color-surface-sunken`, `--color-accent-green` e os três tokens de raio.
      - `--color-muted`, `--color-success-600` e `--color-warning-600` valem os valores medidos
        do DAP; `.eyebrow` e `.nav-label` deixam de usar `text-slate-400`.
      - `grep -nE "rgba\\(110, ?86, ?207|rgba\\(33, ?161, ?121" app/globals.css` não volta nada.
      - `docs/design/one-design-system.md` existe e está citado em `docs/project-context.md`.
      - `npm run build` passa e `npm test` continua verde.
    depends_on: []
    validation: lint, web-unit-contract, build
    required_capabilities: READ web; WRITE app/globals.css e dois documentos; VALIDATE lint/test/build
    risk: Baixo. Acrescentar token não desloca utilitário existente; trocar valor de token desloca cor.
    relative_effort: S

  - id: T02
    role: builder
    goal: As três primitivas do One em `components/one/`, com consumidor real — e o wordmark
          deixando de existir duas vezes escrito à mão.
    scope: components/one/*.tsx (novo); app/DashboardClient.tsx e app/login/page.tsx apenas nos
           dois blocos de marca; app/globals.css se a primitiva precisar de classe nova.
    out_of_scope: Mover mapeamento de JSON da API para `components/` — derruba a guarda de consumo,
                  que só varre `app/`. Reescrever qualquer outra parte do DashboardClient.
    expected_areas: web
    acceptance_criteria:
      - `components/one/Brand.tsx`, `StatePill.tsx` e `Button.tsx` existem e são importados.
      - O literal do wordmark aparece em **um** arquivo; nem `DashboardClient.tsx` nem
        `login/page.tsx` o escrevem.
      - `StatePill` renderiza ícone **e** texto **e** cor nas quatro variantes.
      - Nenhum `<button>` novo sem `onClick` ou `type="submit"`.
      - `npm test` verde, inclusive as asserções de HTML renderizado.
    depends_on: [T01]
    validation: lint, web-unit-contract, build
    required_capabilities: READ web; WRITE components/ e dois blocos de marca; VALIDATE lint/test/build
    risk: Médio. `components/` entra no corpus varrido e não entra no da guarda de consumo.
    relative_effort: M

  - id: T03
    role: builder
    goal: A varredura do nome, ponta a ponta — tela, contrato publicado, e-mail, prompt, realm,
          seed e pacote — mais os ativos de marca regenerados.
    scope: app/**; public/favicon.svg e public/og.png; apps/api/src/portal_api/{main,config,seed}.py,
           ai/{prompt,service}.py, integrations/biahflow.py, __init__.py, devtools/drive_stub.py,
           seed_data/biahflow-snapshot.json; docs/api/openapi.json; docs/ai/prompt-registry.json;
           infra/keycloak/portal-local-realm.json; .env.example; docker-compose.yml;
           package.json e package-lock.json; os testes que fixam a string antiga; documentos vivos.
    out_of_scope: ADRs históricas (0008, 0009, 0021) e o histórico do ROADMAP — ADR aceita não é
                  reescrita. Qualquer mudança de comportamento de auth, RLS, rota ou policy.
    expected_areas: web, api, infra, docs
    acceptance_criteria:
      - `grep -rniE "portal ?labs|portallabs" .` (fora de node_modules/.next/.venv/.git) volta
        **apenas** prosa histórica identificada por caminho.
      - `PROMPT_VERSION` é nova e `docs/ai/prompt-registry.json` tem a entrada correspondente.
      - `python -m portal_api.openapi --write` não produz diferença depois do commit.
      - `test_seed_matches_realm.py` verde: realm e `SEED_USERS` casam `sub`, e-mail, nome e papel.
      - `marina.farias@acme.com.br` **não** muda — é cliente, não é do time.
      - `public/favicon.svg` e `public/og.png` usam o tile aprovado; nenhum deles diz o nome antigo.
    depends_on: [T01, T02]
    validation: lint, web-unit-contract, build, api-unit-integration
    required_capabilities: READ tudo; WRITE o escopo acima; VALIDATE lint/test/build/pytest
    risk: Alto por largura, não por profundidade. Erra por omissão, e o critério de aceite é `grep`.
    relative_effort: L

  - id: T04
    role: builder
    goal: A vitrine interna que prova o sistema num navegador.
    scope: app/admin/design/page.tsx e o cliente dela; app/globals.css se precisar de classe nova.
    out_of_scope: Rota nova de API. Esquema novo no contrato. Qualquer log — evento novo obriga
                  linha em `alerts.md`, e um alerta que ninguém vigia é ruído.
    expected_areas: web
    acceptance_criteria:
      - `/admin/design` responde 200 para interno e `notFound()` para quem não é, espelhando
        `app/admin/page.tsx`.
      - A página renderiza as quatro pastilhas de estado, as quatro variantes de botão com
        `disabled`, o campo com foco, os três raios e a paleta.
      - Todo controle da vitrine tem handler de verdade.
      - `npm test` verde.
    depends_on: [T01, T02]
    validation: lint, web-unit-contract, build
    required_capabilities: READ web; WRITE app/admin/design/**; VALIDATE lint/test/build
    risk: Baixo. O risco real é desenhar controle inerte, e há guarda que reprova.
    relative_effort: S

  - id: T05
    role: builder
    goal: A evidência de navegador na revisão exata, contra a pilha real.
    scope: scripts/capture-browser-evidence.mjs (novo);
           docs/features/F-025-o-nome-que-a-tela-ainda-nao-sabia/evidence/browser/**
    out_of_scope: Mudar código de produto para facilitar a captura. Alterar spec de e2e existente.
    expected_areas: web, docs
    acceptance_criteria:
      - Existe captura de shell desktop 1440×900, shell mobile 390×844, foco de teclado visível,
        dashboard/projeto, os quatro estados semânticos e o estado de revisão/decisão do cliente.
      - Cada captura declara o SHA da revisão que a produziu.
      - `npm run test:e2e` verde com a pilha de pé.
    depends_on: [T01, T02, T03, T04]
    validation: e2e, browser
    required_capabilities: READ tudo; WRITE scripts/ e evidence/; VALIDATE e2e e docker compose
    risk: Médio. Depende da pilha subir; um Keycloak lento é a causa mais provável de falha.
    relative_effort: M
```

```text
parallel_groups: nenhum.

critical_path: T01 → T02 → T03 → T05, com T04 pendurado em T02 e consumido por T05.
  T03 é `L` e domina o caminho: é a única tarefa que atravessa os quatro ecossistemas
  (web, API, infra e documentação) e a única cujo critério de aceite é uma varredura.

integration_strategy: um worktree, um Builder ativo, commits focados por tarefa na mesma branch,
  um PR. Sem merge local em `main`.

human_gates:
  - Design approval — **atravessado** em 25/08/2026, revisão 2, visual e cópia.
  - Merge do pull request. O harness comita, empurra, abre PR e observa CI; não mergeia.
  - `DONE` da feature, que exige evidência, revisão e decisão humana. Merge de PR é evidência de
    integração de engenharia, não aceitação de cliente.

planning_findings:
  - `PARALLELISM_RISK` entre T01, T02, T03 e T04: as quatro tocam `app/globals.css`, e T02 e T03
    tocam os mesmos blocos de `app/DashboardClient.tsx` e `app/login/page.tsx`. Worktree isola
    estado do Git; não prova independência semântica. **Resolução: execução sequencial**, um
    Builder ativo, na ordem do caminho crítico.
  - T03 poderia ser cortada em três (tela / backend / infra+docs), e não foi: o critério de aceite
    dela é um `grep` sobre o repositório inteiro, e um critério que só fecha quando as três partes
    estão prontas não é critério de três tarefas.
  - Nenhuma tarefa exige migração, e isso é verificável: `alembic check` sem deriva é portão.
```

## Validação do plano

`PLAN_VALID` — 25/08/2026.

| Critério | Resultado |
| --- | --- |
| IDs únicos | T01…T05, sem repetição |
| Toda dependência nomeia tarefa existente | sim |
| Aciclicidade | sim — `T01 → T02 → {T03, T04} → T05`, sem retorno |
| Critérios de aceite verificáveis | sim; cada um diz **como** é conferido |
| Validação com comando real do projeto | sim; os perfis vêm de `docs/project-context.md` |
| Toda exigência da FDD tem dono | sim |
| Paralelismo seguro | classificado `PARALLELISM_RISK` → sequencial |
| Caminho crítico com justificativa de esforço | sim |
| Estratégia de integração | sim |

## Desvios de plano

Nenhum registrado até aqui. Depois de o plano ser congelado, mudança em dependência ou em trabalho
planejado vira `PLAN_DEVIATION` com tarefa, estado planejado, estado real, impacto e resolução —
o plano congelado não é editado no lugar.
