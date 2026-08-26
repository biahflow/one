# Plano de execução — F-026

**Estado:** `BLOCKED_ON_DESIGN_APPROVAL`. O gate de Design Approval precede o planejamento
(`workflows/design-approval.md`): um plano que decompõe superfície não aprovada produz tarefas que
precisam ser recortadas quando o desenho muda. Este arquivo só vira DAG válido do Planner **depois**
que o DAP r1 for aprovado por humano.

## Decomposição preliminar (não-vinculante, para dimensionar)

Sujeita a mudar com o que o gate aprovar (ex.: `.nav-item` ativo em `brand-50` vs neutro; abas
longas nesta fatia ou na seguinte).

- **T01 — Naming remanescente.** Trocar "Notificações no portal" → "One" (`DashboardClient.tsx`).
  Validação: `rendered-html`.
- **T02 — Mapa §1 (sidebar/topbar).** Remapear `@apply` de `.sidebar/.topbar/.nav-item/.breadcrumb`
  em `app/globals.css`. Sem tocar JSX.
- **T03 — Mapa §2 (status-card/métricas/jornada/pendências).** Remapear os `@apply` restantes.
- **T04 — Primitivas.** Adotar `StatePill` nos estados e `Button` nos botões do shell.
- **T05 — Evidência de navegador.** Capturas desktop + mobile 390×844 das superfícies tocadas,
  comparadas às `captures-r4/` da F-025; `api-contract` verde (prova de "não mexi em dado").

Dependências: T02–T04 dependem apenas do DAP aprovado; T05 depende de T02–T04. T02 e T03 são
paralelizáveis (seletores disjuntos no mesmo arquivo — cuidar de conflito de merge, não de lógica).
