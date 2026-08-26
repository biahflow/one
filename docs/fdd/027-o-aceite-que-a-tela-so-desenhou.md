# FDD 027 — O aceite que a tela só desenhou

**Feature ID:** `F-027`

## Status

`READY_FOR_SPEC` — Feature Contract redigido; aguarda gate de Design Approval (DAP r1) e a ADR do
contrato de retorno (ver *Gates humanos*) antes de `READY_FOR_PLANNING`.

> **Classificação: `FEATURE_CHANGE` · `BROWSER_REQUIRED`.** Origem: Issue #61. Torna **real** a
> superfície de revisão/aceite do cliente que a F-025 §10 desenhou como **reservada** — "desenha,
> não entrega … vira real quando existir contrato de projeção com `approvals` chegando de verdade e
> evento `client.accepted` de volta". Concretiza o laço de aceite da ADR 0067.

## Prioridade

Selecionada por humano em 26/08/2026 (Issue #61). `[confirmar sequência com F-026/F-028 no gate]`

## Objetivo e não objetivos

### Problema

O One mostra ao cliente o que a operação entregou, mas **não tem onde o cliente aceitar ou pedir
mudança**. Hoje "concluído" é fato do lifecycle de Delivery no Biahflow; não há registro, na
fronteira do produto, de que **o cliente** revisou e decidiu. O invariante que a fatia carrega é:

```
GitHub PR merged ≠ client accepted
Engineering DONE ≠ business/client acceptance
```

A F-025 já **desenhou** a superfície (o card de revisão, os cinco rótulos de aceite, os controles
Aprovar / Pedir ajuste) e a deixou explicitamente reservada, sem renderizá-la — porque um controle
inerte é defeito, não *placeholder* (ADR 0026). Falta o que a torna real: uma identidade de
entregável que sobreviva ao sync, um registro imutável da decisão, o aviso ao time, e o evento
canônico de volta ao SoR.

### Resultado desejado

Um cliente autorizado revisa um entregável elegível em One, **aprova** ou **pede mudança** com
comentário opcional; a decisão grava ator/data/proveniência num histórico **imutável** que uma
segunda decisão não apaga (supersessão é explícita); o time é notificado; o isolamento de tenant
permanece; e o aceite de negócio fica **visivelmente distinto** do merge de engenharia. O One
registra o evento e **nunca** conclui `done` — só o lifecycle de Delivery o faz (ADR 0067).

### Escopo

- Definir uma projeção de entregável **revisável** pelo cliente, com identidade estável e
  proveniência.
- Estados mínimos: aguardando revisão (`ready_for_acceptance`), em revisão (`client_review`),
  aprovado (`accepted`), ajuste pedido (`changes_requested`), e supersessão/cancelamento onde couber.
- Registrar ator, timestamp, comentário/motivo opcional e **histórico de evento imutável**.
- Impedir sobrescrita silenciosa de decisão anterior; supersessão é explícita.
- Expor o contexto/evidência de revisão já autorizados para o projeto (links de documento/citação).
- Notificar o fluxo operacional interno quando o cliente aceita ou pede mudança.
- Manter o cliente dentro da fronteira de autorização projeto/tenant.
- Tornar a semântica de aceite explícita o bastante para o Pulse projetar o resultado **sem inventar
  status**.
- Distinguir feedback do cliente dos achados do Reviewer de engenharia.

### Fora de escopo

- Merge automático no GitHub; deploy automático em produção; assinatura eletrônica/legal.
- Mudar os gates de Reviewer/Human Merge de engenharia.
- Redesenho amplo fora das superfícies de revisão/aceite.
- Fazer o One autoritativo sobre a fase de Delivery (ADR 0067) — ele registra o evento, não a fase.

## Jornada e interface

A superfície é a da F-025 §10, agora renderizada quando há entregável elegível:

1. O cliente vê, na aba de revisão (ou no card do entregável na jornada), os entregáveis em
   `ready_for_acceptance`/`client_review`, cada um com seu contexto/evidência já autorizados.
2. Abre a revisão, lê, e escolhe **Aprovar** ou **Pedir ajuste**; comentário é opcional em Aprovar e
   esperado em Pedir ajuste.
3. A decisão vira uma linha no histórico imutável, o estado projetado do entregável muda, e um aviso
   sai para o time.
4. O histórico de decisões fica visível — uma segunda decisão **acrescenta**, não substitui; uma
   supersessão é rotulada como tal.

`done` aparece em **cinza** na escada de aceite (design decisão 9): quem o declara é a operação, não
o cliente — dar a `done` a cor de "concluído" sugeriria que o aceite do cliente encerra a entrega, e
a ADR 0067 diz o contrário. Detalhe visual, estados e cópia no DAP em
[`../features/F-027-o-aceite-que-a-tela-so-desenhou/design-approval.md`](../features/F-027-o-aceite-que-a-tela-so-desenhou/design-approval.md).

## Dados, API e permissões

**Pré-requisito medido — identidade estável do entregável.** `PhaseDeliverable` é **apagado e
recriado a cada sync** (`integrations/biahflow.py`, `delete(PhaseDeliverable)` no início do
snapshot) e **não tem** `external_ref` — o uuid de hoje não é o de amanhã. É exatamente a armadilha
que `notifications.py` documenta (ITEM_ANCHOR). Portanto o aceite **não** pode ter FK para o uuid do
read model; o entregável precisa primeiro ganhar um `external_ref` durável, populado por
`sync_snapshot`, no precedente de `PendingItem.external_ref` e `Document.external_id`.

**Tabela nova — `deliverable_acceptance` (append-only).** Forma seguindo o precedente de
`pending_item_comment` (ADR 0032), que é escopo **projeto** e existe para o outro lado ler:

- Herda `_ProjectChildMixin` → `organization_id` + `project_id` denormalizados (a policy vira
  comparação de coluna).
- Vínculo por **identidade estável**: `deliverable_external_ref` denormalizado (não FK ao uuid), mais
  `phase_name`/`deliverable_name` denormalizados — sobrevivem ao delete/recreate do sync, como
  `pending_item_comment.author_label` sobrevive à remoção do autor.
- Evento: `action` (enum `accepted` | `changes_requested`; `superseded`/`cancelled` **exigem decisão
  nova** — não estão no vocabulário visual da §10), `actor_user_id` (`ON DELETE SET NULL`),
  `actor_label` + `actor_is_internal` denormalizados, `comment`, `created_at`.
- **Imutabilidade por privilégio:** `GRANT SELECT, INSERT ... TO portal_app` e **nada de `UPDATE`/
  `DELETE`** — "quem escreve não reescreve", como `pending_item_comment`. É o que impede a sobrescrita
  silenciosa no nível do banco, não só na aplicação. O estado corrente do entregável deriva do último
  evento (ou é projetado pelo contrato, nunca escrito pelo cliente).
- Policies `TO portal_app` escopadas a org+project (cópia de `0021_pending_item_comment`). Casos novos
  em `test_rls_isolation.py` (insert cross-tenant rejeitado; app role não reescreve a linha).

**Rota.** `POST /api/v1/me/deliverables/{external_ref}/acceptance`, no molde de `add_pending_comment`
(`main.py`): `CurrentPrincipal`, `status_code=201`, resolve `user`→`project` por `access`,
**404 se sem projeto**, `_refuse_when_read_only` (409 em projeto arquivado/removido), `TenantContext`,
delega a um módulo dedicado `deliverable_acceptance.py` ("o único lugar onde o aceite é escrito"),
enfileira a notificação **fora da transação**. `responses={**CLIENT_ERRORS, **READ_ONLY_PROJECT_ERROR}`
— **404, nunca 403** (regra 6 do `AGENTS.md`), com caso em `test_authorization.py`. Schemas
`DeliverableAcceptanceIn`/`Out` em `schemas.py` com `extra="forbid"`; OpenAPI regenerado
(`test_openapi_contract.py`).

**Notificação interna.** Novo `NotificationKind` (via `ALTER TYPE ... ADD VALUE`, migração aditiva),
entrada em `AUDIENCE` = `_INTERNAL_ONLY` (precedente `onboarding_stuck`/`whatsapp_reply`) — a entrada
é **obrigatória**, senão o `.get(kind, _CLIENT_ONLY)` de `recipients` vaza o aviso ao cliente. **Fora
do `diff`** (o aceite nasce da requisição do cliente, não do snapshot), emitido por task sob
`portal_system` (padrão `queue_pending_comment_notification`), `dedupe_key` por
`(deliverable_external_ref, action, ...)`, `exclude_user_id` para não avisar o próprio autor. Linha
nova em `runbooks/alerts.md` no mesmo commit (guarda bidirecional, ADR 0034).

## Estados de erro e segurança

- **404, nunca 403** em toda a rota — a indistinção "não existe" vs "não é seu" é o produto da regra.
- **409** em projeto arquivado/removido (`_refuse_when_read_only`), depois do 404.
- Cliente distinto do Reviewer: o feedback do cliente vive em `deliverable_acceptance`, separado dos
  achados de engenharia (que nem chegam ao One).
- O termo do comentário não vira log nem `audit_log` além do necessário; sem segredo em fixture/log.

## Restrições e dependências

- **Contrato de retorno ao Pulse é lacuna verde.** A integração Biahflow é **unidirecional** hoje
  (só `httpx.get` do snapshot; nenhum `post` de volta). O `client.accepted` que a ADR 0067 e a Issue
  #61 exigem **não existe** — precisa de um **emissor outbound novo** (contrato de projeção
  versionado). Duas formas possíveis, a decidir por ADR: (a) o One faz POST ao BiahflowOS/ClickUp por
  contrato explícito; (b) o One **persiste o evento canônico** em `deliverable_acceptance` como fonte
  da verdade e o Pulse o **consome** (pull ou webhook reverso). Em qualquer forma, o evento imutável é
  a fonte do que foi devolvido, garantindo idempotência.
- Depende da **F-025 §10 aprovada** (o desenho da superfície) e do sistema de design (F-026 aplica a
  pele; F-027 pode usar as primitivas diretamente).
- Migração **aditiva** (ADR 0066): sem `drop`; e por tocar policy+GRANT, **cita no corpo do arquivo**
  a ADR desta feature (o portão `test_migration_rules.py` exige ADR/RFC existente e aceita).

## Lacunas e riscos

- **`superseded`/`cancelled` não estão desenhados** (§10 tem cinco rótulos; esses dois não). Entram
  só com decisão de design nova — o FDD não os assume por conta própria.
- **Elegibilidade** (o que faz um entregável entrar em `ready_for_acceptance`) vem do contrato de
  projeção (F-028 / Biahflow), não do One. Se F-028 não estiver pronta, a fonte de "elegível" é o
  campo que o snapshot já traz (estado do entregável) — a decidir no gate.
- Risco de o retorno ao Pulse virar segunda fonte da verdade; mitigado por (b) acima — One registra o
  evento, Pulse projeta, nenhum lado inventa fase.

## Gates humanos

1. **Design Approval** do DAP r1 (a superfície §10 tornada real).
2. **ADR do contrato de retorno e da nova tabela** — decisão arquitetural consequente (direção da
   integração + RLS/GRANT nova). Requer aceite humano **antes** do build; a migração não passa no
   portão sem ela.
3. Aprovação de plano; merge humano; `DONE` só após evidência, revisão e decisão humana. O One nunca
   marca `done` de Delivery — nem a feature, nem o produto.

## Telemetria e critérios de aceite

Telemetria: eventos de log `deliverable.accepted` / `deliverable.changes_requested` (nome de evento
sem interpolação, detalhe em `extra` — ADR 0018/0034), com linha em `alerts.md`. Critérios (Issue #61):

- [ ] Cliente autorizado revisa um entregável elegível em One.
- [ ] Cliente aprova ou pede mudança explicitamente.
- [ ] Toda decisão grava ator/timestamp/proveniência e preserva histórico.
- [ ] Uma segunda decisão não apaga a primeira; supersessão é explícita.
- [ ] Acesso cruzado entre projetos permanece impossível (RLS + `test_rls_isolation`/`test_authorization`).
- [ ] Estado de merge de engenharia e aceite do cliente são visivelmente distintos.

## Referências

- Issue #61; **ADR 0077** (contrato de retorno One→Pulse + tabela `deliverable_acceptance`; o
  pré-requisito arquitetural desta FDD, `proposto`); ADR 0067 (laço de aceite); F-025 §10
  (`design-approval.md`), rótulos em
  `one-dap-r4.html`. Precedentes: `pending_item_comment` (ADR 0032, migração 0021),
  `conversation_message.feedback` (ADR 0015, migração 0012), `notifications.py`/`AUDIENCE`,
  `add_pending_comment`/`pending_comments.py` (molde de rota+módulo). `test_rls_isolation.py`,
  `test_authorization.py`, `test_migration_rules.py` (ADR 0066).

## Testes e avaliações de IA

- `test_rls_isolation.py`: insert cross-tenant rejeitado; app role não reescreve `deliverable_acceptance`.
- `test_authorization.py`: a rota nova nega 404 (nunca 403) ao trocar de ator.
- `test_openapi_contract.py`: schema publicado, sem campo com nome de segredo, 404 declarado.
- Testes de fluxo: aprovar; pedir ajuste; segunda decisão **acrescenta** (não sobrescreve);
  supersessão explícita; notificação interna sai e **não** vai ao cliente (guarda de `AUDIENCE`).
- Sem eval de IA (não toca prompt/recuperador/modelo/ferramenta).
