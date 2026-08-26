# ADR 0077 — A porta de volta que a integração não tinha

**Status:** proposto
**Data:** 26/08/2026
**Fase:** 7

> **Rascunho pendente de gate humano.** Esta ADR é o pré-requisito arquitetural da `F-027`
> ([FDD 027](../fdd/027-o-aceite-que-a-tela-so-desenhou.md), Issue #61): a migração que cria a tabela
> de aceite escreve policy e `GRANT`, e `test_migration_rules.py` exige uma ADR **aceita** a citar
> (regra 4 do `AGENTS.md`, ADR 0066). Enquanto `proposto`, o build da F-027 não começa. Nenhum
> código foi escrito por esta ADR. É o par da [ADR 0076](0076-o-snapshot-que-precisava-de-versao-e-hora.md)
> (Pulse→One); esta trata do sentido inverso, One→Pulse.

## Contexto

A ADR 0067 decidiu que One apresenta a entrega ao cliente quando ela entra em `CLIENT_REVIEW`, e que
*"a decisão do cliente deve gerar evento canônico e retornar ao BiahflowOS/ClickUp por contrato
explícito"* — `client.accepted` pode permitir `ACCEPTED`, mas *"somente regras do lifecycle de
Delivery podem concluir `DONE`"*. A F-025 §10 **desenhou** a superfície de aceite e a deixou
reservada, com a condição escrita de que só viraria real "quando existir contrato de projeção com
`approvals` chegando de verdade e evento `client.accepted` de volta".

Duas coisas medidas (dossiê da Issue #61) impedem que isso exista hoje:

1. **A integração é unidirecional.** `integrations/biahflow.py` só tem `httpx.get` (puxa o snapshot);
   não há nenhum `post` de volta ao Biahflow. O `client.accepted` que a ADR 0067 exige **não existe** —
   é lacuna verde.
2. **O entregável não tem identidade estável.** `PhaseDeliverable` é **apagado e recriado a cada
   sync** e **não tem** `external_ref` (ao contrário de `PendingItem.external_ref` e
   `Document.external_id`). O uuid de hoje não é o de amanhã — é a armadilha que `notifications.py`
   já documenta (ITEM_ANCHOR). Um aceite com FK ao uuid do read model seria destruído no próximo
   webhook.

O invariante que a fatia carrega: **`GitHub PR merged ≠ client accepted`**; engenharia `DONE` não é
aceite de negócio. One registra o **evento** do cliente; não conclui a fase.

## Decisão

Quatro peças. A que carrega o resto é a terceira: **o evento persistido é a fonte da verdade do
aceite**, e o retorno ao Pulse é uma projeção dele — não o contrário.

### 1. Identidade estável do entregável, antes de qualquer aceite

`PhaseDeliverable` ganha um `external_ref` **durável** (o id do entregável no Biahflow), populado por
`sync_snapshot`, no precedente de `PendingItem.external_ref`. O aceite ancora nele — nunca no uuid do
read model, que o sync recria. Migração aditiva (ADR 0066).

### 2. `deliverable_acceptance` — registro **append-only**, imutável por privilégio

Tabela nova, na **forma de `pending_item_comment`** (ADR 0032): escopo **projeto** (o evento existe
para o outro lado ler), herda `_ProjectChildMixin` (`organization_id` + `project_id` denormalizados,
policy vira comparação de coluna). Colunas:

- `deliverable_external_ref`, `phase_name`, `deliverable_name` **denormalizados** — sobrevivem ao
  delete/recreate do sync, como `pending_item_comment.author_label` sobrevive à remoção do autor;
- `action` (enum `accepted` | `changes_requested` — o vocabulário desenhado na §10;
  `superseded`/`cancelled` **não** entram sem revisão de design própria);
- `actor_user_id` (`ON DELETE SET NULL`), `actor_label`, `actor_is_internal` denormalizados;
- `comment`, `created_at`.

**Imutabilidade é privilégio, não convenção:** `GRANT SELECT, INSERT ... TO portal_app` e **nada de
`UPDATE`/`DELETE`** — "quem escreve não reescreve", exatamente como `pending_item_comment`. Uma
segunda decisão **acrescenta** uma linha; a anterior aparece **superada** na tela (riscada, rotulada),
nunca apagada. Não há tela de "editar aceite" porque o banco a recusaria — seria feature errada, não
faltando. Policies `TO portal_app` escopadas a org+project (cópia de `0021_pending_item_comment`),
com casos novos em `test_rls_isolation.py`. A migração **cita esta ADR** no corpo.

### 3. O retorno ao Pulse projeta o evento; o evento não espera o retorno

A rota do cliente (`POST /api/v1/me/deliverables/{external_ref}/acceptance`, no molde de
`add_pending_comment`: `CurrentPrincipal`, **404 nunca 403**, `_refuse_when_read_only` → 409,
`TenantContext`, módulo dedicado `deliverable_acceptance.py`) grava o evento **na transação da
requisição** e responde. O envio ao Biahflow acontece **depois**, por task sob `portal_system`
(padrão `queue_pending_comment_notification`), lendo o evento já commitado.

Duas formas de retorno, e a decisão é a **(b)**:

- **(a) push** — One faz `POST` ao BiahflowOS/ClickUp por contrato explícito;
- **(b) pull/consumo** — One **persiste o evento canônico** e o expõe; o Biahflow o **consome** (o
  inverso do snapshot: como o One puxa de lá, o Biahflow puxa daqui, ou recebe um webhook reverso).

Escolhe-se **(b)** como o contrato primário porque mantém a simetria da ADR 0067 (cada lado é dono do
seu banco e projeta para o outro) e porque **desacopla o aceite da disponibilidade do Biahflow**: se
o outro lado estiver fora, o aceite do cliente **não se perde** — ele está gravado, imutável, e o
retorno reconcilia depois. Idempotência sai de graça do registro append-only: reenviar é reler a
mesma linha. Um emissor **push** pode ser acrescentado como otimização (avisar o Biahflow "há aceite
novo"), mas ele nunca é a fonte da verdade — se divergir do registro, o registro vence.

### 4. `accepted` permite `ACCEPTED`, nunca `DONE`

O evento do cliente autoriza o Biahflow a transicionar para `ACCEPTED`; **só** o lifecycle de Delivery
conclui `DONE` (ADR 0067). É por isso que `done` é cinza na escada de aceite da F-025 §10: dar a ele a
cor de "concluído" sugeriria que o aceite do cliente encerra a entrega. One registra; não conclui.

## O que esta decisão **não** faz

- **Não** faz merge no GitHub, deploy, nem assinatura eletrônica (fora de escopo, Issue #61).
- **Não** transiciona a fase de Delivery — emite o evento que **permite** a transição no outro lado.
- **Não** desenha `superseded`/`cancelled` como rótulo — exige revisão de design própria.
- **Não** decide a **elegibilidade** (o que traz um entregável para `ready_for_acceptance`): isso vem
  do contrato de projeção (ADR 0076 / F-028) ou, na ausência dela, do estado que o snapshot já traz.

## Notificação interna

O aceite gera aviso **só do time** — novo `NotificationKind` (via `ALTER TYPE ... ADD VALUE`),
entrada **obrigatória** em `AUDIENCE` = `_INTERNAL_ONLY` (precedente `onboarding_stuck`/
`whatsapp_reply`; sem a entrada, o `.get(kind, _CLIENT_ONLY)` de `recipients` vazaria o aviso ao
cliente). **Fora do `diff`** (o aceite nasce da requisição, não do snapshot), emitido pela mesma task
pós-commit, `dedupe_key` por `(deliverable_external_ref, action)`, `exclude_user_id` para não avisar
o próprio autor. Linha nova em `runbooks/alerts.md` no mesmo commit (guarda bidirecional, ADR 0034).

## Consequências

- A integração deixa de ser unidirecional: nasce o primeiro caminho One→Pulse, e ele é **de dado do
  cliente**, não de status — coerente com "o portal nunca origina status" (ADR 0006/0008), porque
  aceite **é** dado que o cliente origina, como a conversa e o comentário de pendência.
- O aceite do cliente sobrevive a uma queda do Biahflow (registro imutável + retorno reconciliável).
- Merge de engenharia e aceite de negócio ficam distintos no dado e na tela.
- Custo declarado: uma segunda porta de integração para manter; mitigado por ela ser **pull** (o
  Biahflow puxa, como o One puxa o snapshot) e pelo evento imutável ser a única fonte da verdade.

## Aberto

- **Mecanismo concreto do consumo (b)**: o Biahflow puxa por rota autenticada (chave de agente, como
  a ingestão da ADR 0013?) ou recebe um webhook reverso do One? A decidir com o lado do Biahflow.
- **`superseded`/`cancelled`** como estados/rótulos — design próprio.
- **Elegibilidade** do entregável — depende da F-028 (ADR 0076) ou do estado atual do snapshot.
