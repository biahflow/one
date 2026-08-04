# FDD 006 — Jornada da transformação e Funcionários Digitais

O cliente abre o portal e entende, sem intermediação, **onde está** na jornada (Welcome →
Discover → Prove → Scale → Optimize), **o que já foi desbloqueado**, **quem trabalha por ele**
(os Funcionários Digitais) e **quanto isso rendeu**. Tudo em perspectiva de negócio: nenhuma
task técnica, nenhum score interno.

Escrita retroativamente: a Fase 6 do `ROADMAP.md` foi entregue sem FDD, contrariando a
convenção do `CLAUDE.md` ("every feature ships with an FDD").

## Escopo

- Barra "Você está aqui" com as fases; ao clicar numa fase, objetivo, status, previsão e
  entregáveis (entregue vs. bloqueado, com link quando houver).
- Roster de Funcionários Digitais: o que cada um faz, KPI, horas poupadas e ROI por mês.
- ROI e próxima reunião reais nos cards da Visão geral.
- Indicador de saúde amigável ("No prazo" / "Requer atenção" / "Atrasado" + cor).

## Origem dos dados

Tudo vem do snapshot do Biahflow (ADR 0006) — o portal não origina nada disso. Modelos
`ProjectPhase`, `PhaseDeliverable` e `DigitalEmployee`, mais colunas de ROI, próxima reunião e
saúde no `Project` (migrações `0003_journey_and_roi`, `0004_project_health`,
`0005_digital_employee`). Projeção em `build_dashboard` (`integrations/biahflow.py`), consumida
por `GET /api/v1/me/dashboard`.

## Critérios de aceite

- A fase ativa do Biahflow é a destacada como "Você está aqui".
- Entregável só aparece como entregue quando o Biahflow o marca assim.
- O Health Score interno **não** é exposto: só atravessam rótulo e cor.
- Sem funcionário digital cadastrado, o painel não é renderizado (nada inventado).

## Telemetria e testes

`apps/api/tests/test_biahflow_integration.py` cobre a projeção da jornada, a substituição de
fases/entregáveis sem duplicar, ROI, próxima reunião, saúde e o roster. O SSR é verificado em
`tests/rendered-html.test.mjs` ("Você está aqui", "SUA JORNADA", "Funcionários Digitais").

## Avaliações de IA

Não se aplica: esta feature não altera prompt, recuperador, modelo ou ferramenta. Fases e
Funcionários Digitais não são evidência citável do chat — a recuperação segue sobre projeto,
marcos e pendências (ADR 0007).
