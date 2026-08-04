# FDD 005 — Pendências

Cliente pode abrir e acompanhar pendências. Falta de contexto no chat cria uma pendência com pergunta, fontes consultadas e responsável. Mudanças geram central de notificações e e-mail.

## Estado

- **Pendência por lacuna de contexto (Fase 3 / ADR 0007) — feito:** o chat cria uma
  `PendingItem` quando não há evidência suficiente, em vez de inventar resposta.
- **Aba Pendências (Fase 2 / ADR 0008) — feito:** a aba mostra abertas e resolvidas vindas do
  read model, com responsável (`party` do Biahflow → `owner_label`) e idade. Pendências têm
  **origem**: `biahflow` (espelhadas, substituídas a cada sync) e `portal` (abertas pela IA,
  preservadas em qualquer sync) — coluna `origin` na migração `0006_portal_sync_fields`. A
  origem `portal` é marcada na UI como "aberta pela IA". O contador do menu lateral usa a
  contagem real de pendências abertas.

  Critério de aceite coberto por teste: uma pendência criada pelo chat continua visível depois
  de um novo webhook do Biahflow (`test_sync_replaces_biahflow_pendings_but_keeps_portal_ones`).

- **Central de notificações e e-mail (Fase 2 / ADR 0012) — feito:** ver abaixo.
- **Fora de escopo:** resolução de pendência pelo cliente — o portal é read-only e a pendência é
  resolvida no Biahflow (ADR 0006). Preferência por tipo de notificação e push também não
  entram; a preferência que existe é uma só, ligar ou desligar o e-mail.

## Notificações

O cliente é avisado quando o projeto anda, sem ter que abrir o portal para descobrir. O produtor
é o sync do Biahflow: `sync_snapshot` fotografa o read model antes de escrever
(`notifications.snapshot_state`), compara depois, e grava uma linha por destinatário. O portal
continua sem originar status (ADR 0006/0008) — ele só avisa que o status mudou lá.

**O que vira aviso.** Marco concluído, fase da jornada que ficou ativa, entregável liberado,
documento novo, reunião agendada, transcrição disponível, pendência aberta ou resolvida, e
mudança de status/saúde do projeto. A audiência mora em `notifications.AUDIENCE`: o cliente
recebe tudo; o time interno, só `pending_opened`.

**Onde aparece.** O sino da barra superior mostra a contagem de não lidas vinda de
`GET /api/v1/me/notifications` (abrir marca como lidas, no banco); "Ver todas" leva à central,
com o histórico do projeto. A preferência de e-mail fica em Configurações e escreve
`PATCH /api/v1/me/preferences`.

**E-mail.** Um resumo por lote de sync, por pessoa, enviado pelo worker
(`send_project_digests`) via SMTP — Mailpit no local, provedor configurável em produção.

### Critérios de aceite

| Critério | Coberto por |
|---|---|
| Um marco que passa a concluído avisa o cliente | `test_notifications.py::test_milestone_reaching_done_notifies_the_client` |
| O mesmo webhook reenviado não duplica aviso nem e-mail | `test_the_same_webhook_replayed_does_not_duplicate`, `test_notification_email.py::test_running_twice_does_not_send_twice` |
| O primeiro sync de um projeto não notifica ninguém | `test_first_sync_notifies_nobody` |
| Pendência nova chega ao cliente e ao time | `test_a_new_pending_reaches_the_client_and_the_internal_team` |
| Quem não é do projeto não recebe | `test_a_member_of_another_project_receives_nothing` |
| Aviso de outra pessoa é invisível, mesmo no mesmo projeto | `test_rls_isolation.py::test_a_colleague_in_the_same_project_does_not_see_your_notifications` |
| Marcar como lida não permite reescrever o aviso | `test_marking_read_is_allowed_but_rewriting_the_notice_is_not` |
| O caminho de requisição não cria notificação | `test_the_app_role_cannot_create_a_notification` |
| Um e-mail por lote, não um por aviso | `test_notification_email.py::test_one_email_per_batch_not_one_per_notification` |
| Quem desligou o e-mail não recebe | `test_a_user_who_turned_email_off_gets_nothing` |
| SMTP fora não derruba nada | `test_the_smtp_being_off_is_not_an_error` |
| O sino conta o que a API disse, e o F5 não ressuscita o ponto | `tests/rendered-html.test.mjs`, `tests/e2e/notifications.spec.ts` |

### Telemetria

`send_project_digests` devolve `{sent, notifications}` e registra falha de SMTP por
destinatário; `queue_project_digests` registra quando o broker está fora. Retenção da tabela:
12 meses declarados na ADR 0012, poda na Fase 5.

### Casos de avaliação de IA

Nenhum: nada aqui passa por modelo. A única notificação que nasce de uma decisão da IA é a de
pendência por lacuna de contexto, cujos casos já vivem na FDD 002.
