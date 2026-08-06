# ADR 0030 — O sinal do assistente, sem a pergunta do cliente

**Status:** aceita — 06/08/2026
**Contexto:** Fase 2/4, fechando o item que a ADR 0015 adiou. O time interno passa a ler como o
assistente está indo — e o GRANT de coluna é o que garante que ele não leia o que foi perguntado.

## Contexto

A ADR 0015 gravou o feedback do chat e adiou a tela com um argumento condicional: *"uma tela de
análise sem dado acumulado mostraria zero. O que ela vai ler já está no formato certo."*

**O dado acumulou.** No banco local, hoje: 143 respostas do assistente, 6 avaliadas, e as 6
`not_helpful` — 100% de reprovação entre quem se deu ao trabalho de clicar. Mais 5 turnos que
declararam lacuna. Nada disso era alcançável: o único caminho até uma avaliação era o histórico
da própria pessoa que a deixou.

Um produto cujo único sinal de qualidade da IA é unanimemente negativo, e invisível, é o caso
que a tela existe para pegar.

## O problema real: a fronteira estava no lugar errado

`conversation_message` é uma das duas tabelas cuja linha pertence a uma **pessoa** (a outra é
`notification`). Todas as suas policies são `TO portal_app` com
`user_id = portal.current_user_id()`, então a tela leria zero linhas — era preciso uma policy
`TO portal_admin`.

Só que dar a policy dá a tabela inteira, e a pergunta do cliente é conteúdo confidencial dele
(`docs/data-classification.md`). `ai/service.py` já se recusa a pôr essa pergunta no
`audit_log` exatamente por isso.

**E medindo, descobriu-se que o privilégio já estava concedido.** `roles.sql` faz
`ALTER DEFAULT PRIVILEGES ... GRANT SELECT ON TABLES TO portal_admin`, então o papel nascia com
SELECT de tabela em tudo — `text` e `citations` inclusive. O que impedia a leitura **não era o
privilégio, era a ausência de policy**. Consequência: qualquer policy `TO portal_admin` criada
nestas tabelas abriria a pergunta do cliente no mesmo commit, sem que ninguém escrevesse um
`GRANT`.

## Decisão

### 1. A policy decide as linhas; o GRANT de coluna decide as colunas

O idioma que `notification` e `user` já usam nesta base, aqui carregando o produto inteiro. A
policy é `TO portal_admin` pela GUC de terceiro estágio, como o resto de `admin.py`.

### 2. O `REVOKE` vem antes do `GRANT`, e sem ele nada disto restringe

`GRANT SELECT (colunas)` é **aditivo**: por cima do SELECT de tabela que o default privilege já
dava, não tira nada. A migração revoga o SELECT de tabela primeiro. É a ordem que transforma a
lista de colunas num teto em vez de um enfeite.

### 3. O que entra, e o que não

Entra: `confidence`, `feedback`, `feedback_comment`, `feedback_at`, `responder`, `model`,
`prompt_version`, `pending_item_id` e as chaves.

Não entra: **`text`** (a pergunta e a resposta) e **`citations`**.

E não entra **`conversation.title`** — a exclusão que quase passou. O título da thread é derivado
da *primeira pergunta* (`conversations._title_from`), então barrar `text` e conceder `title`
entregaria a pergunta pela porta dos fundos. A coluna óbvia de barrar era uma; a que teria
vazado assim mesmo era a outra.

O `feedback_comment` entra porque é a única frase do cliente **endereçada ao time**. A pergunta
foi endereçada ao assistente.

### 4. A rota nunca seleciona a entidade

`select(ConversationMessage)` expande para todas as colunas e falha. Isso não é teoria: a
primeira versão desta rota fez exatamente isso e respondeu 500 no primeiro clique — o GRANT
funcionando como projetado. **Um `select()` distraído aqui falha em vez de vazar**, e falha na
hora em vez de num incidente.

## Consequências

- **O sinal existe e é lido.** A tela mostra o agregado antes da lista, porque um polegar isolado
  não diz nada e 6 em 6 diz muito.
- **A privacidade é do banco, não da tela.** Se alguém reescrever o componente amanhã, continua
  sem conseguir mostrar a pergunta — o papel não a alcança. É a diferença entre um controle e uma
  convenção.
- **Quatro asserções, e as três negativas são o ponto:** o admin lê o sinal; **não** lê `text`;
  **não** lê `title`; e não vê a organização vizinha. As duas do meio reprovam se o `REVOKE` for
  removido — verificado restaurando o GRANT de tabela à mão.
- **Um risco latente ficou nomeado:** o default privilege do `roles.sql` faz *toda tabela nova*
  nascer legível para `portal_admin`. Combinado com o meta-teste que exige policy para toda
  tabela com `organization_id`, a próxima tabela de conteúdo do cliente terá o mesmo problema —
  e desta vez está escrito onde alguém procura.
- **Sem coluna, sem tabela, sem migração de schema.** `alembic check` limpo: a migração 0020 é só
  policy e privilégio.

## Alternativas recusadas

**Conceder a tabela e filtrar na aplicação.** Funciona até o primeiro `select()` distraído — e
esta fatia produziu um, no seu próprio primeiro rascunho. O controle tem de estar onde o erro é
impossível, não onde ele é improvável.

**Mostrar a pergunta "só quando o cliente reclamou".** Soa razoável e é a mesma leitura, com um
`if` no meio. O consentimento de escrever um comentário não é consentimento de mostrar a
conversa.

**`citations` na tela.** Seria útil para calibrar (quais trechos foram mostrados), e é
justamente por isso que fica fora: "quais trechos aquela pessoa viu" é a pergunta dela de novo,
por outro ângulo. Se a calibragem precisar, é outra ADR — não um GRANT a mais.

**Agregar por projeto sem lista nenhuma.** Perde o `feedback_comment`, que é o campo mais
informativo do conjunto: o polegar diz que errou, o comentário diz o quê.
