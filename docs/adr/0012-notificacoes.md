# ADR 0012 — Notificações: fan-out por usuário, origem no sync, e-mail assíncrono

**Status:** Aceito — 04/08/2026

## Contexto

O aceite da Fase 2 diz: *"equipe interna atualiza o projeto no Biahflow; o cliente acompanha as
alterações no portal em quase tempo real."* A segunda metade estava cumprida — o dashboard lê o
read model — e a primeira não: o cliente só descobria uma mudança se abrisse o portal por conta
própria. Enquanto isso a UI já fingia o contrário, com três avisos fixos no componente
(`app/DashboardClient.tsx`), um booleano local de "já li" que um F5 desfazia, e três
interruptores decorativos em Configurações. É o mesmo tipo de dado sem lastro que a Fase 1
eliminou do dashboard.

Três restrições vindas de decisões anteriores moldam a solução:

1. **O portal não origina status** (ADR 0006/0008). Ele não *sabe* que um marco foi concluído;
   ele descobre que o read model mudou depois de um snapshot.
2. **Privilégio mora na credencial** (ADR 0010/0011). O caminho de requisição (`portal_app`) só
   escreve `pending_item`, `audit_log` e a própria linha de `user`.
3. **Toda tabela com `organization_id` sai com policy na mesma migração**, e um meta-teste
   quebra o CI se não sair.

## Decisão

### 1. Uma linha por destinatário, e não uma por evento

`notification` carrega `user_id` e `read_at`. A alternativa — uma linha por fato mais uma tabela
`notification_read` — economiza linhas e cobra em todo o resto: a leitura vira join, a RLS vira
duas policies, e a audiência precisa de mais uma coluna de qualquer jeito.

Com o fan-out:

- a policy de leitura é uma comparação de coluna: `organization_id = portal.current_org() AND
  user_id = portal.current_user_id()`;
- "marcar como lida" é um `UPDATE` na própria linha;
- a **audiência é dado**. O cliente recebe o andamento do projeto; o time interno recebe só
  `pending_opened`, porque o resto ele acabou de digitar no Biahflow — avisar alguém do próprio
  eco é como uma central de notificações morre.

O custo é duplicação proporcional ao número de membros de um projeto, que é da ordem de dezenas.

### 2. `dedupe_key` como contrato de idempotência

O webhook do Biahflow é uma **reconciliação completa**, não um delta: o mesmo payload chega mais
de uma vez por desenho, e `sync_snapshot` substitui as linhas espelhadas a cada chegada. Sem
uma chave estável, todo webhook reemitiria tudo.

`uq_notification_user_dedupe_key` fecha isso, e a chave é derivada da identidade do fato
(`milestone:<título>:done`, `document:<external_id>`, `pending:<external_ref>:resolved`) — nunca
do `id` da linha, que o sync recria. Chave longa demais para a coluna vira `<prefixo>:<sha256>`,
que continua determinística. A gravação usa `ON CONFLICT DO NOTHING ... RETURNING`, então o que
já existia não volta — e é isso que também impede o e-mail de sair de novo.

Consequência aceita: uma mudança que volta ao estado anterior e depois se repete não notifica
duas vezes. Para status e saúde do projeto, onde a repetição é informação, a data entra na
chave — mesmo status no mesmo dia é um aviso só.

### 3. O primeiro sync de um projeto não notifica

`snapshot_state` devolve `None` para um projeto que ainda não existe, e o diff de `None` é
vazio. Sem esse guarda, um projeto recém-chegado dispararia um aviso por marco, documento e
reunião que já nasceram prontos — a caixa de entrada do cliente cheia no primeiro login, de
coisas que ele nunca viu acontecer.

### 4. Quem escreve é o sync, sob `portal_system`

`portal_app` recebe `SELECT` e **`UPDATE (read_at, updated_at)`** — grant de coluna, porque a
policy decide quais *linhas*, nunca quais *colunas*. Sem isso, "marcar como lida" seria licença
para reescrever título, detalhe ou destinatário do próprio aviso. Não há `INSERT` nem `DELETE`
para o caminho de requisição.

A consequência aparece na pendência que a IA abre por lacuna de contexto (ADR 0007): o chat roda
sob `portal_app` e não pode criar a notificação. Ela sai por uma task Celery
(`notify_pending_created`) sob `portal_system`, depois do commit. A ausência do grant é o
desenho, não um descuido.

### 5. Preferência de e-mail: uma policy nova e um grant mais estreito no `user`

`notify_by_email` mora no `user`, e até aqui o caminho de requisição só podia tocar aquela
tabela para *reivindicar* uma linha semeada (`user_self_link`, que exige `external_subject IS
NULL`). A policy `user_self_preferences` abre o próprio registro — e, junto com ela, a migração
**aperta** o que a 0007 tinha deixado largo: `GRANT UPDATE ON "user"` valia a tabela inteira e
passa a valer três colunas (`external_subject`, `notify_by_email`, `updated_at`). Sem esse
aperto, a policy nova abriria também `email`, `full_name` e `is_internal` — o usuário se
promovendo a interno é exatamente o tipo de escrita que o caminho de requisição não deve
alcançar.

### 6. Um e-mail por lote de sync, e ele pergunta ao banco o que falta enviar

`send_project_digests(project_id)` trabalha sobre `emailed_at IS NULL` em vez de receber a lista
de ids de quem chamou. Um webhook costuma mexer em várias coisas de uma vez, e a fila pode
perder ou repetir uma task; perguntar "o que ainda não foi avisado?" faz a repetição virar
no-op e a perda virar atraso — o próximo sync varre o que sobrou.

Quem desligou o e-mail tem as notificações carimbadas assim mesmo: religar a preferência não
deve abrir uma comporta de avisos velhos.

O transporte é `smtplib` da biblioteca padrão. O requisito é "Mailpit local, provedor
configurável em produção", e todo provedor sério fala SMTP; um SDK amarraria o portal a um
fornecedor para ganhar nada.

### 7. Enfileirar não pode derrubar o webhook

Quando a API chega ao ponto de enfileirar, as notificações já estão comitadas: elas aparecem no
portal com ou sem Redis. Falhar a requisição do Biahflow por causa do e-mail trocaria uma
degradação por uma indisponibilidade, então o `.delay()` mora dentro de um `try/except` que
apenas registra.

### 8. A caixa é escopada ao projeto atual

`GET /api/v1/me/notifications` resolve o projeto por `access.default_project`, como o dashboard.
As policies leem as GUCs de organização/projeto, que só existem depois que *um* projeto foi
resolvido — uma listagem que atravessasse projetos rodaria sem contexto, e sem contexto a policy
devolve zero linhas. O comportamento estaria certo; a tela, não.

## Consequências

- Uma tabela nova com política própria, e o meta-teste de RLS passa a cobri-la automaticamente.
- O caminho de requisição ganhou seu segundo `UPDATE`, e o do `user` ficou mais estreito do que
  era antes desta ADR.
- **Retenção fica declarada e não implementada:** `notification` cresce por projeto e por
  membro, sem poda. O prazo adotado é **12 meses**, e a rotina que apaga o excedente é da Fase 5
  (retenção e exclusão por organização), junto do resto da política de dados. **Resolvido na
ADR 0017:** `notification` é podada por `created_at` segundo a janela da organização. Até lá o volume é
  irrelevante — dezenas de avisos por projeto por mês.
- A audiência é uma tabela em `notifications.py`. Mudar quem recebe o quê é editar um dicionário,
  não caçar condicionais.

## Alternativas consideradas

- **Notificação por projeto + tabela de leitura.** Recusada em 1.
- **Polling do read model pelo front.** Não distingue "mudou" de "sempre foi assim" sem guardar
  o que cada pessoa já viu — que é a tabela desta ADR, só que no cliente.
- **Celery beat com resumo diário.** Mais silencioso e atrasa o que importa (uma pendência
  atribuída ao cliente), além de somar o agendador ao compose. Um e-mail por lote de sync já
  agrupa o que precisa ser agrupado, porque o lote *é* a unidade de mudança.
