# ADR 0032 — Comentários na pendência, e o escopo que inverte

**Status:** aceita — 06/08/2026
**Contexto:** Fase 2, último dos três itens nomeados. A única das três fatias com schema novo.

## Contexto

A pendência é o único ponto da tela onde se espera que o cliente **aja**, e ele não tinha como
dizer nada ali. Quando precisava responder "já enviei a planilha", respondia por e-mail — fora do
portal, fora do registro, e invisível para quem abriu a pendência.

Ao contrário das ADRs 0030 e 0031, aqui não havia nada meio-feito para descobrir: comentário não
existia em lugar nenhum. É por isso que esta fatia carrega uma decisão de produto em vez de um
achado.

## Decisão

### 1. Escopo de **projeto**, e a inversão é o centro da fatia

`conversation` e `conversation_message` são as duas tabelas que o caminho de requisição já
originava, e as policies das duas exigem `user_id = portal.current_user_id()`: a conversa pertence
a quem perguntou. A ADR 0030, da mesma semana, chegou a **revogar** privilégio de coluna para
manter isso de pé.

Um comentário inverte: a policy é a de tenant simples (organização + projeto), como
`pending_item`, e "quem escreveu" fica na coluna em vez de no `WHERE`.

**As duas conclusões opostas têm o mesmo critério — a quem o texto foi endereçado.** A pergunta do
cliente foi endereçada ao assistente, e por isso o time interno não a lê. O comentário é
endereçado à outra parte, e um comentário que só o autor lê não serviria para nada. Há um teste
que fixa cada lado, e eles são o espelho um do outro:
`test_a_colleague_in_the_same_project_does_not_see_your_conversation` e
`test_a_colleague_in_the_same_project_does_see_the_comment`.

### 2. Escreve quem participa; ninguém reescreve

Cliente **e** equipe interna. Se só um lado escreve, vira formulário de recado sem resposta, e o
outro responde por fora — que é o estado que a fatia existe para tirar.

`portal_app` recebe **só `INSERT`** na migração 0021. O `SELECT` já vem do
`ALTER DEFAULT PRIVILEGES` do `roles.sql`, e `UPDATE`/`DELETE` não vêm de graça — o que aqui é o
controle e não um esquecimento, pelo argumento da ADR 0015. Não há `REVOKE` a fazer, ao contrário
da 0020: o default privilege concede leitura, não escrita.

`author_user_id` é `SET NULL` e não `CASCADE`, e `author_label`/`author_is_internal` são
denormalizados na escrita: revogar o acesso de alguém não pode reescrever a história da pendência
apagando o que foi dito, e alguém que deixa de ser interno não muda o lado de quem falou naquele
dia.

### 3. O comentário não volta para o Biahflow, e o custo fica escrito

A integração é unidirecional — webhook fino + snapshot puxado —, e não há rota de escrita do outro
lado. O portal já origina conversa e feedback (ADR 0015), então originar comentário não abre
categoria nova.

**O custo, declarado:** o time interno ganha uma **segunda caixa de entrada**. O que impede que
ela seja ignorada é a notificação, e é por isso que ela não é opcional nesta fatia.

### 4. A notificação avisa o outro lado, não quem escreveu

`NotificationKind.pending_commented`, audiência `_EVERYONE` — como `pending_opened`, o outro fato
que pede ação dos dois lados.

`fan_out` derivava destinatários só de `recipients()`, que responde pelo **tipo** do aviso.
`exclude_user_id` é deste **evento**, e é por isso que ele entra no `fan_out` e não em
`recipients`: juntá-los faria o `AUDIENCE` deixar de ser uma tabela que se lê. Receber aviso do
próprio comentário é o ruído que ensina a ignorar o sino.

O caminho é o precedente exato de `notify_pending_created`: a rota roda sob `portal_app`, que não
tem `INSERT` em `notification`, e **enfileira** — o worker faz o `fan_out` sob `portal_system`.
Nenhum GRANT novo, e `queue_*` continua engolindo broker morto: o comentário já está commitado, e
derrubar a resposta por causa do aviso faria a pessoa achar que não escreveu.

### 5. `ALTER TYPE` — o `alembic check` não cobraria isso

`notification.kind` é um enum **do Postgres** (migração 0009). Acrescentar o valor no Python não
basta, e o gate de deriva não acusa: ele compara tabelas e colunas, não rótulos de enum. Sem o
`ALTER TYPE ... ADD VALUE`, o primeiro comentário gravaria e o aviso estouraria no worker, longe
da causa.

### 6. O fio fica atrás de um clique, e a contagem é o que faz decidir

Oito pendências com todos os fios abertos viram mural. `PendingOut` ganhou `comment_count` — o que
acionou sozinha a guarda da ADR 0029, obrigando o BFF a consumi-lo — e é ele que diz se vale
abrir.

De quebra, `PendingOut` ganhou **`id`**: a tela precisava endereçar a pendência para abrir o fio, e
até aqui a chave de render era o título, que ninguém garante ser único.

## Consequências

- **O cliente responde no portal, e o registro fica.** A pendência deixa de ser um mural de avisos
  de mão única.
- **Quatro asserções nascem vermelhas** (`INSERT` sim / `UPDATE`-`DELETE` não; comentário do
  vizinho invisível; colega do mesmo projeto **visível**; o autor não recebe aviso; e o expurgo
  leva o comentário).
- **O expurgo por organização o alcança pelo `CASCADE` de `project`**, e há teste que afirma isso
  em vez de assumir — era a pergunta aberta do plano.
- **Sem poda por idade.** `conversation` é podada porque é histórico de consultas; um comentário é
  parte do registro da pendência, e a pendência não sai por aniversário.
- **A terceira escrita do caminho de requisição**, e a primeira de escopo de projeto. Vale
  registrar que a lista está crescendo: cada uma precisou de justificativa própria, e a próxima
  também precisará.
- **Fora de escopo, declarado:** anexo em comentário (o caminho de arquivo é
  `/admin/conhecimento`, com varredura — ADR 0017 —, e um upload por aqui contornaria essa
  fronteira); menção a pessoa; e e-mail imediato, porque o resumo por lote já é o canal.

## Alternativas recusadas

**Empurrar o comentário para o Biahflow.** Manteria uma fonte da verdade só, e é a opção
arquitetonicamente mais limpa. Exige rota de escrita no outro repositório, que não existe — a
integração é unidirecional por desenho (ADR 0006). Bloquearia a fatia por tempo indeterminado.

**Só o cliente escreve.** Superfície menor e intenção clara, e reproduz exatamente a assimetria
que o comentário existe para resolver: o time responderia no Biahflow e o cliente não veria.

**Só a equipe interna escreve.** Vira nota de acompanhamento, não conversa, e não atende "o
cliente precisa poder dizer algo".

**Permitir editar dentro de N minutos.** É a exceção que dissolve a regra: `UPDATE` concedido é
`UPDATE` concedido, e a janela viveria na aplicação, onde a ADR 0030 acabou de mostrar que um
`select()` distraído passa. Um comentário errado é corrigido por outro comentário.

**Reusar `conversation_message` com um `pending_item_id`.** Tentador porque a tabela já existe e já
tem autor. Custaria o escopo: aquelas policies são de pessoa, e afrouxá-las para acomodar o
comentário reabriria a leitura da conversa — desfazendo a ADR 0030 três dias depois.
