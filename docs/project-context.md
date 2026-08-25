# Contexto do projeto — One

## Finalidade e autoridade

Este é o ponto de entrada operacional do projeto na Engineering OS. Ele referencia fontes
canônicas existentes; não substitui PRD, FDD, ADR, RFC, runbook ou configuração executável.

A ordem de regras é: Engineering OS global → [AGENTS.md](../AGENTS.md) → contrato da tarefa.
O contexto global está disponível em `/Users/danielcampos/workspace/engineeringOS/` e inclui os
princípios, guardrails, definição de pronto, contratos de Planner/Builder/Reviewer e workflows.

## Fontes de verdade

| Responsabilidade | Fonte canônica | Regra de uso |
| --- | --- | --- |
| Trabalho planejado e descoberta | [ROADMAP.md](../ROADMAP.md) | Índice canônico; nenhum agente escolhe prioridade. |
| Contrato e estado detalhado da feature | [docs/fdd/](fdd/) | Para uma feature com FDD, a FDD prevalece sobre a linha resumida do roadmap. |
| Requisitos de produto | [PRD.md](../PRD.md) | Define problema, usuários e limites do MVP. |
| Decisões de arquitetura | [docs/adr/](adr/) | ADR aceita não é reescrita; mudança consequente exige nova ADR. |
| Contexto/propostas transversais | [docs/rfc/](rfc/) | RFC não é fonte de status de implementação. |
| Arquitetura atual | [docs/architecture.md](architecture.md) | Visão de módulos, fronteiras e implantação. |
| Regras de segurança e IA | [docs/security.md](security.md), [docs/ai/](ai/) | Aplicação obrigatória conforme escopo. |
| Instruções de agente | [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md) | Devem permanecer compatíveis com a Engineering OS. |
| Sistema de design (tokens, contraste, política de raio) | [docs/design/one-design-system.md](design/one-design-system.md) | `app/globals.css` é a fonte executável; diverge, o CSS vence. |

Não existe `STATUS.md` independente: o estado é uma visão derivada de ROADMAP e FDDs.

## Ciclo de vida e artefatos

As novas features usam os estados da Engineering OS: `BACKLOG`, `READY_FOR_SPEC`,
`SPEC_IN_PROGRESS`, `READY_FOR_PLANNING`, `PLANNING`, `READY_FOR_BUILD`, `IN_PROGRESS`,
`READY_FOR_REVIEW`, `READY_FOR_HUMAN_REVIEW`, `DONE`, `BLOCKED` ou `CANCELLED`.

A convenção é prospectiva. FDDs históricas permanecem em `docs/fdd/`; uma FDD nova usa o
template atualizado, recebe o ID estável `F-<número>` e é o Feature Contract. Para a execução,
use o layout descrito em [docs/features/README.md](features/README.md). Não converta trabalho
técnico em feature de produto sem uma feature-pai explícita.

## Perfis de validação

| Perfil | Estado | Fonte/comando |
| --- | --- | --- |
| `lint` | KNOWN | `npm run lint` |
| `web-unit-contract` | KNOWN | `npm test` |
| `api-unit-integration` | KNOWN | `PYTHONPATH=apps/api/src pytest apps/api/tests` com Postgres e papéis locais quando aplicável |
| `backup-restore` | KNOWN | `PYTHONPATH=apps/api/src pytest apps/api/tests/test_backup_restore.py -v` com Postgres, MinIO e credenciais de teste |
| `e2e` | KNOWN | `docker compose up -d --build` seguido de `npm run test:e2e` |
| `build` | KNOWN | `npm run build`; `docker compose build` |
| `infra-quality` | KNOWN | `.github/workflows/ci.yml` executa `terraform fmt` e `terraform validate` sem backend |
| `security` | KNOWN | `npm run audit` |
| `supply-chain-pins` | KNOWN | `PYTHONPATH=apps/api/src pytest apps/api/tests/test_supply_chain_pins.py` — roda dentro do perfil `api-unit-integration`, sem rede e sem banco; `npm run pins` imprime o inventário |
| `codeql` | NOT_APPLICABLE | Requer `CODE_SCANNING_ENABLED=true` em configuração de repositório; não é gate atualmente |

O contrato da tarefa seleciona apenas os perfis aplicáveis e registra ambiente, baseline e
qualquer validação indisponível. A CI em [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
é a fonte executável dos comandos completos.

## Gates humanos

- Seleção de prioridade e início de implementação de feature.
- Aprovação de plano antes de `READY_FOR_BUILD` quando aplicável.
- Produção, mudanças destrutivas de dados, exceções de segurança e decisões arquiteturais
  consequentes.
- `DONE` só após evidência, revisão aplicável e decisão humana.

## Estado de adoção

`ENGINEERING_OS_COMPLIANT` em 17/08/2026. A adoção resolveu a ambiguidade de status das RFCs,
preservou artefatos históricos e não criou uma fonte de trabalho paralela.
