# Evidência — F-026

**Estado:** baseline registrado; nenhuma implementação ainda (aguarda gate de Design Approval).

## Baseline (26/08/2026, `main`)

- Superfície de cliente já sem naming provisório de marca (medido: `grep -riE "portal ?labs|portal do cliente" app/` → vazio).
- Shell ainda estiliza com utilitários crus em `app/globals.css`: `bg-white` (22×), `slate-*` (73×),
  `amber`/`rose` (7×) — o alvo do mapeamento do DAP.
- Primitivas `components/one/{StatePill,Button}.tsx` existem e o shell **não** as usa.
- `npm test` e `tests/api-contract.test.mjs` verdes em `main` (baseline de "dado inalterado").

## A preencher na execução

- `BUILD REPORT` por tarefa (T01–T05).
- Capturas desktop + mobile presas à revisão aprovada do DAP.
- Resultado de `npm test` / `api-contract` pós-mudança (prova de não-regressão de dados).
- Desvios de plano e decisões humanas (gate de design, gate de plano, merge).
