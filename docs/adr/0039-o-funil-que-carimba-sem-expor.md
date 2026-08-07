# ADR 0039 — O funil que carimba sem expor

**Status:** aceito
**Data:** 07/08/2026
**Fase:** 7 — implementa o passo 1 da RFC 001 (FDD 020)

## Contexto

Primeiro item construído da Fase 7. O produto sabe se um projeto está no prazo e **não sabe se o
cliente está engajando**: um projeto verde cujo cliente parou de logar é churn silencioso, e só
aparece quando ele reclama ou some. A RFC 001 descreve o funil inteiro; esta ADR registra o
recorte que foi construído e as decisões que a construção obrigou a tomar.

**O recorte é da própria RFC**, e o argumento é uma cicatriz deste repositório: *"carimbar sem
expor — primeiro os degraus e as datas, sem tela e sem alerta"*, porque a ADR 0033 achou
`/admin/assistente` publicando um painel sobre um campo que nunca teve escritor. Aqui a ordem é a
inversa, de propósito: **escritor primeiro, leitor depois**.

## Decisão

### Uma tabela por organização, com carimbo imutável

`onboarding_step` usa `TenantMixin` sem `project_id`, na forma de
`organization_retention_policy`: a pergunta é sobre a relação do cliente com o produto, e um
cliente pode ter mais de um projeto. `UniqueConstraint (organization_id, step)` mais
`ON CONFLICT DO NOTHING` fazem a segunda ocorrência não ter efeito, e **nenhum papel recebe GRANT
de `UPDATE`** — nem o sistema. Primeira vez é primeira vez; reescrever destruiria a única métrica
que interessa, o *time-to-first-value*. É o mesmo argumento que impede reescrever o que uma
chamada de IA custou (ADR 0022) e as citações que uma resposta mostrou (ADR 0015).

### `portal_app` sem policy nenhuma

O papel de requisição herda o `SELECT` das default privileges e lê **zero linhas**, porque nenhuma
policy é `TO portal_app` — a forma de `agent_api_key` e `project_drive_connection`. Escrita ele não
tem: **um caminho de requisição capaz de escrever o próprio degrau é um caminho capaz de falsear o
próprio engajamento**. Quem carimba é o sistema, em transação própria, no precedente do
`chat_limit.consume`.

O cliente também não deve *ler* o funil, e a FDD 020 diz por quê: ele não deve saber que está
sendo medido, e não há nada que ele possa fazer com essa informação.

### Seis degraus, e o sétimo declarado ausente

Cinco nascem aqui — login, documento aberto, pendência respondida, turno de chat, ROI visto — e um
vem afirmado pelo Biahflow (primeiro entregável fora de `pending`). Todos são momentos em que o
cliente **recebeu** algo; nenhum mede esforço.

**`artifact_accepted` não existe no enum**, embora a RFC o liste: `grep artefato` em
`integrations/biahflow.py` devolve zero — o snapshot não carrega nada de artefato. Declará-lo agora
criaria um degrau que nada carimba, que é a forma exata do painel sem escritor. Ele entra quando o
outro lado o afirmar.

### O login é carimbado no dashboard, e não em `identity.py`

A RFC aponta o `external_subject` deixando de ser nulo, mas **ali ainda não há organização
resolvida** — o próprio `identity.py` diz isso ao explicar por que não grava `audit_log`. No
dashboard há, e o degrau fica melhor definido: "aceitou o convite" passa a significar que a pessoa
**entrou e viu o projeto**, não que um token foi validado. A idempotência não depende de saber que
é a primeira vez, porque o `ON CONFLICT` decide isso.

### Falha em silêncio, com traceback

Um carimbo que falha não derruba a requisição: medir engajamento não pode custar um download ao
cliente. Sai `onboarding.stamp_failed` com `exception`, porque ninguém repara na falta de uma
linha — e o par `step_reached`/`stamp_failed` entra em `NOT_AN_ALERT` com o motivo escrito, já que
o alerta que importa é o de cliente **travado**, e esse é o passo 3.

### Retenção e apagamento alcançam os degraus

Família nova `onboarding_days` (padrão 1095 dias, o mais longo dos quatro: o *time-to-first-value*
só significa algo comparado com o de coortes anteriores). A purga vai pelo `reached_at`, que é a
data do **fato** — o degrau do entregável chega pelo sync e pode ser carimbado depois.

**E o apagamento por decisão precisou de linha própria.** `retention._erase` apaga a árvore do
projeto por CASCADE e a `membership` à mão, e o docstring dizia que a `membership` era "a única
exclusão que precisa ser escrita à mão". Isso vale para tabela **de projeto**: o funil é escopado
por organização, e a linha `organization` fica de propósito — então o CASCADE não o alcança por
caminho nenhum. Sem o `delete` explícito, o funil sobreviveria ao apagamento do tenant, com o dado
mais sensível que o portal guarda. Agora são duas exclusões manuais, e a regra que as une está
escrita: **o que é escopado por organização não vem no CASCADE do projeto**.

## O defeito que só apareceu ao executar

`bool(result.rowcount)` **não** diz se a linha nasceu. Medido: para `INSERT ... ON CONFLICT DO
NOTHING` o driver devolve `rowcount = -1` nos dois casos, e `bool(-1)` é `True` — de modo que todo
carimbo se declarava "primeira vez" e o evento sairia a cada download e a cada pergunta, que é
exatamente o ruído que a linha do `alerts.md` promete não existir. A resposta confiável é
`RETURNING`: com `DO NOTHING`, ele não devolve linha quando pula. O teste de imutabilidade é o que
pegou.

De quebra, um segundo: o `except` que engole a falha chamava `step.value` na linha de log, então um
`step` inesperado estouraria **dentro** do bloco que existe para não estourar. O caminho de erro
não pode ter erro próprio.

## Consequências

- O funil nasce **sem leitor**, e é a ordem que a RFC exige. Nenhuma guarda reprova (a da ADR 0033
  é sobre campo de contrato, e não há rota nova), então fica registrado aqui para não ser lido como
  esquecimento.
- `first_roi_seen` e `first_login` são carimbados numa **leitura**. Um `GET` que provoca escrita é
  incomum aqui; fica em transação própria sob `portal_system`, fora da transação da requisição.
- Degrau de quem é interno não conta: o funil é sobre o cliente.

## O que fica em aberto

O **alerta de cliente travado** (passo 3) e a **vigília da IA** (passo 4), nesta ordem e só depois
de haver histórico. E `artifact_accepted`, que depende do Biahflow afirmar o aceite no snapshot —
fatia do outro lado, na forma da ADR 0037.
