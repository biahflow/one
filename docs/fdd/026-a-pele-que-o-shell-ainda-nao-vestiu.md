# FDD 026 — A pele que o shell ainda não vestiu

**Feature ID:** `F-026`

## Status

`READY_FOR_SPEC` — Feature Contract redigido; aguarda gate de Design Approval (DAP r1) antes de `READY_FOR_PLANNING`.

> **Classificação: `INTERFACE_CHANGE` · `BROWSER_REQUIRED`.** Origem: Issue #60. Depende do
> sistema de design aprovado na F-025 (ADR 0069, DAP r3/r4) — não é retomada dele: a F-025
> **criou** a linguagem e a aplicou à marca e a algumas superfícies; esta fatia a aplica ao
> **shell do cliente e ao dashboard primário**, que ainda estilizam com utilitários crus.

## Prioridade

Selecionada por humano em 26/08/2026 (Issue #60). `[confirmar prioridade relativa a F-027/F-028 no gate]`

## Objetivo e não objetivos

### Problema

A F-025 aprovou o sistema de design do One e extraiu a linguagem para
[`docs/design/one-design-system.md`](../design/one-design-system.md), mas aplicou os **tokens
semânticos** (`surface`, `muted`, `line`, `success/warning/danger/info`, `radius-*`, `focus`) a um
subconjunto de superfícies. O **shell do cliente real** — sidebar, topbar, status-card, grade de
métricas, painel de jornada, painel e fio de pendências — ainda pinta com **utilitários crus** no
`@layer components` de `app/globals.css`: `bg-white` (22×), `slate-*` (73×), `amber`/`rose` (7×). O
JSX (`app/DashboardClient.tsx`) já é limpo: consome as classes; o problema mora no CSS.

Isso tem duas consequências mensuráveis: (a) os três valores que a medição de contraste da F-025
**corrigiu** — `muted`, `success-600`, `warning-600` — não alcançam o shell onde ele ainda escreve
`slate-400`/`amber-800` à mão, então o pior caso de contraste que a F-025 documentou sobrevive
fora das superfícies que ela tocou; (b) as primitivas `StatePill` e `Button` que a F-025 criou em
`components/one/` existem e **o shell não as usa** — ele redesenha estado e botão à mão, que é a
duplicação que a F-025 existe para acabar.

### Resultado desejado

O shell do cliente e o dashboard primário consomem os tokens e as primitivas **já aprovados**, sem
mudar comportamento de dados, autenticação ou tenant, e sem introduzir valor visual novo: a
aparência-alvo é a que a F-025 aprovou (DAP r4, `captures-r4/`). O que muda é a **procedência** —
o mesmo pixel, agora vindo do token — e, onde o token corrige contraste, o contraste.

### Escopo

- Substituir naming provisório remanescente na superfície de cliente por "One" onde ainda houver
  (medido: a marca já está limpa; resta a palavra comum "portal" em `DashboardClient.tsx:2400`
  — "Notificações no portal").
- Remapear o `@apply` do shell em `app/globals.css` de utilitários crus para tokens semânticos:
  `bg-white`→`bg-surface`, `slate-*`→`muted`/`line`/`surface-sunken`, `amber-*`→`warning-*`,
  `rose-*`→`danger-*`, na sidebar, topbar, status-card, grade de métricas, painel de jornada e
  entrada/fio de pendências.
- Adotar as primitivas `StatePill` (estados `.state--*`/`.health-pill`/`.priority-pill`) e `Button`
  (`.ai-button`/`.text-button`) do `components/one/` no shell, no lugar do desenho à mão.
- Preservar auth, membership de projeto, isolamento de tenant, carregamento de dados e todo
  comportamento de negócio.
- Remover o estilo legado/provisório das superfícies tocadas — sem deixar um seletor cru ao lado
  do tokenizado.
- Reusar os assets/primitivas canônicos do One em vez de duplicar SVG ou valor cru.

### Fora de escopo

- Redesenhar toda tela do produto; abrir workflow de negócio novo; o laço de aceite (F-027) e a
  projeção de jornada (F-028).
- Superfícies internas `/admin/*` — herdam os tokens; nenhuma decisão visual nova.
- Redefinir a base de `--spacing` do Tailwind ou trocar as classes utilitárias de raio
  (`rounded-2xl`/`xl`/`full`) pelos tokens de raio — a F-025 fixou os tokens de raio como
  **política** sem substituir as classes nesta geração, e reabrir isso seria redesenho disfarçado.
- Tema escuro; mudanças de auth/tenant.

## Jornada e interface

Nada muda na jornada do cliente: as mesmas telas, os mesmos estados. A interface muda de
**origem de valor**, não de forma. As superfícies tocadas e seus estados (sucesso, vazio,
carregando, erro, não autorizado) são as do DAP da F-025 §06–§09, agora vestidas pelo token.
O gate desta fatia decide o **mapeamento** utilitário→token, não uma aparência nova — ver o DAP
em [`../features/F-026-a-pele-que-o-shell-ainda-nao-vestiu/design-approval.md`](../features/F-026-a-pele-que-o-shell-ainda-nao-vestiu/design-approval.md).

## Dados, API e permissões

**Nenhuma mudança.** Sem migração, sem rota nova, sem alteração de schema, contrato OpenAPI ou
GRANT. É a propriedade que `tests/api-contract.test.mjs` prova: a mudança de pele não pode alterar
nenhum campo consumido. `app/page.tsx` (auth/tenant/`?project=`) e `app/layout.tsx` não são tocados
na lógica.

## Estados de erro e segurança

Os estados vazio/carregando/erro/404 já existem (`app/loading.tsx`, `app/error.tsx`,
`app/page.tsx` `NoProject`, `.empty-state`) e já são tokenizados na F-025 (`.state-shell`/
`.state-card`/`.empty-state` usam `border-line`/`text-muted`). Esta fatia confere que continuam
corretos; não os reescreve.

## Restrições e dependências

- **Depende da F-025 aprovada** (tokens, primitivas, `one-design-system.md`). Se aquele DAP mudar,
  este é revisado.
- `app/globals.css` é a fonte executável; onde ele e `one-design-system.md` divergirem, o CSS vence.
- Não introduzir token novo sem consumidor: a guarda de consumo de `tests/rendered-html.test.mjs`
  deriva o corpus do `@theme` e reprova token órfão. Esta fatia **só consome** tokens já existentes,
  então reforça a guarda em vez de arriscá-la.

## Lacunas e riscos

- **Risco baixo, mecânico.** O maior risco é uma regressão visual silenciosa: um `slate-*` que não
  mapeava exatamente para um token (ex.: `slate-200/70` de `.progress`). Mitigação: o DAP fixa a
  tabela de mapeamento com o valor antes/depois, e a validação de navegador compara com as capturas
  aprovadas da F-025.
- `bg-white`→`bg-surface` é isovalente (`--color-surface: #ffffff`); `slate-*`→`muted`/`line` **não**
  é sempre isovalente e é aí que o contraste melhora — cada não-isovalência é uma decisão do DAP.

## Gates humanos

1. **Design Approval** (antes do planejamento): aprovar o DAP r1 — a tabela de mapeamento e a
   adoção das primitivas. Agente **produz e revisa** o pacote; **não aprova**.
2. Aprovação de plano antes de `READY_FOR_BUILD`.
3. Merge humano; `DONE` só após evidência de navegador (desktop + mobile), revisão e decisão humana.

## Telemetria e critérios de aceite

Sem telemetria nova (mudança de apresentação). Critérios de aceite (da Issue #60):

- [ ] O shell real identifica o produto como One (naming provisório remanescente removido).
- [ ] Assets/primitivas canônicos do One (do contrato de design aprovado) são usados — `StatePill`
      e `Button` adotados no shell.
- [ ] As superfícies primárias do dashboard consomem os tokens semânticos aprovados (sidebar,
      topbar, status-card, métricas, jornada, pendências).
- [ ] O comportamento de dados/permissões do cliente permanece inalterado
      (`tests/api-contract.test.mjs` verde, sem mudança de fixture).
- [ ] Existe evidência de navegador desktop **e** mobile para a revisão exata aprovada.
- [ ] Comportamento de teclado/foco validado (anel de foco da F-025 preservado; nada de
      `outline: none` cru).

## Referências

- Issue #60. Sistema de design: [`docs/design/one-design-system.md`](../design/one-design-system.md).
- F-025: [`docs/fdd/025-o-nome-que-a-tela-ainda-nao-sabia.md`](025-o-nome-que-a-tela-ainda-nao-sabia.md),
  ADR 0069, DAP em `docs/features/F-025-.../design-approval.md`.
- ADR 0067 (One como projeção client-facing) — contexto do porquê o shell é a superfície do cliente.
- Fonte executável: `app/globals.css` (`@theme` 5–45, `@layer components` 84+),
  `components/one/{Brand,StatePill,Button}.tsx`, `app/DashboardClient.tsx`.

## Testes e avaliações de IA

- `npm test` (build + `tests/rendered-html.test.mjs`): `inertButtons()` (todo `<button>` com
  `onClick`/`type="submit"` — a primitiva `Button` já satisfaz), guarda de consumo de token, guarda
  de literais hardcoded.
- `tests/api-contract.test.mjs`: rede que prova "não mexi em dado".
- Validação de navegador (`browser-runtime-validation.md`): capturas desktop + mobile 390×844 das
  superfícies tocadas, presas à revisão aprovada, comparadas às capturas da F-025.
- Sem avaliação de IA (não toca prompt, recuperador, modelo ou ferramenta).
