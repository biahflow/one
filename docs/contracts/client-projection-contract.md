# One — Client Projection Contract

## Objetivo

Definir a projeção client-facing recebida pelo One. O One não é fonte da verdade de CRM, Delivery ou Engenharia; ele materializa uma visão segura e orientada a valor para o cliente.

## Fontes

- Pulse: contexto de cliente/projeto e estados de negócio autorizados.
- ClickUp: estado de Delivery projetado pelo BiahflowOS.
- GitHub: somente sinais derivados necessários à experiência, nunca detalhes internos por padrão.
- BiahflowOS: eventos, resultados e estados consolidados.

## Projeção mínima

```json
{
  "project_id": "...",
  "project_name": "...",
  "current_phase": "prove",
  "progress": 68,
  "status": "client_review",
  "milestones": [],
  "deliverables": [],
  "approvals": [],
  "dependencies": [],
  "outcomes": [],
  "roi": {},
  "next_steps": [],
  "updated_at": "..."
}
```

## Regras

- ClickUp IDs, GitHub issue/PR IDs, traces, agent state, prompts e custos internos não são expostos por padrão.
- valores comerciais internos, custo, margem e dados operacionais sensíveis não atravessam a fronteira.
- toda projeção deve ser idempotente e versionável.
- o One pode persistir a projeção para leitura eficiente, mas isso não transforma seu banco em SoR de Delivery.
- estados de Client Review/Acceptance devem carregar evidência suficiente para o cliente entender o que está aprovando.
- mudanças de projeção devem preservar isolamento por organização/projeto.

## Acceptance

Quando uma entrega exige homologação, o One deve permitir distinguir pelo menos:

- `ready_for_acceptance`;
- `client_review`;
- `accepted`;
- `rejected` ou `changes_requested`, quando aplicável;
- `done` somente quando informado pelo lifecycle operacional.

A aprovação deve registrar ator, timestamp e referência da entrega, e emitir o evento correspondente ao BiahflowOS.

## Evolução

Mudanças incompatíveis requerem versão de contrato. Campos novos opcionais podem ser adicionados de forma retrocompatível.
