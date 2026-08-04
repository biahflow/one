# ADR 0015 — Persistência de conversas, citações e feedback

**Status:** Aceito — 04/08/2026

## Contexto

A ADR 0014 deu olhos ao assistente: o chat passou a citar "Documento: Contrato — página 3" em vez
de declarar lacuna. O que ficou faltando é o outro lado do mesmo turno — ele não sobrevivia ao
navegador. A conversa vivia num `useState` de `app/DashboardClient.tsx`, e um F5 apagava tudo: a
pergunta, a resposta e as fontes que a sustentavam.

Três consequências, e a terceira é a que mais dói:

1. **O cliente perde o que perguntou.** Voltar ao portal amanhã significa perguntar de novo.
2. **A citação não é auditável.** "Esta resposta citou o quê?" só tinha resposta enquanto a aba
   estivesse aberta. Para uma política que diz *resposta sem citação não existe* (AGENTS.md #3),
   guardar a resposta e jogar fora a citação seria guardar a metade errada.
3. **O corte de distância não tem como ser calibrado.** A ADR 0014 assumiu explicitamente que o
   número é delicado — generoso demais cita ruído, apertado demais declara lacuna sobre documento
   que responde — e não deixou nenhum sinal de que lado ele está errando. Sem registro do que foi
   perguntado, do que foi citado e de se serviu, calibrar é chute com etapas.

Restrições herdadas:

- **Privilégio mora na credencial** (ADR 0010/0011). `portal_app` é o caminho de requisição e
  escreve em pouquíssimas tabelas.
- **Toda tabela com `organization_id` sai com policy na mesma migração**, e um meta-teste quebra o
  CI se não sair.
- **O conteúdo da conversa é confidencial do cliente** (`docs/data-classification.md`), e o log de
  auditoria do chat registra deliberadamente *quem perguntou*, nunca *o que foi perguntado*.

## Decisão

### 1. `portal_app` ganha INSERT, e aqui isso é o desenho certo

A 0011 negou INSERT em `document_chunk` com um argumento forte: um caminho de requisição que pode
gravar trecho pode gravar a "evidência" que quer ver citada. A 0009 negou INSERT em `notification`
porque o produtor é o sync. As duas negativas têm a mesma forma — **o request path lê o que outro
produziu**.

A conversa não tem essa forma. A pergunta é do usuário; a resposta é da requisição que ele acabou
de fazer. Exigir um worker para gravar o que a própria transação já sabe trocaria uma garantia real
por uma cerimônia, e ainda abriria uma janela em que o turno foi respondido e não gravado.

### 2. O que substitui a garantia é um invariante: **a mensagem nunca é fonte de recuperação**

É a única coisa que impede o ataque óbvio — alguém afirma um "fato" num turno e pergunta por ele no
seguinte, para ver a própria invenção voltar com aparência de fonte.

A defesa não é um privilégio de banco, é o fato de `ai/retrieval.py` não conhecer
`conversation_message`: `collect_evidence` lê o read model, `collect_document_evidence` lê o índice,
e não há terceira fonte. `test_chat_ai.py` executa exatamente esse ataque e exige que a resposta
continue sendo lacuna.

A escolha assumida junto: **o assistente não vira multi-turno.** Mandar o histórico ao respondedor
mudaria o prompt e a superfície de injeção — o texto de um turno anterior passaria a ser entrada do
modelo —, e isso pede ADR própria com uma rodada de evals. Esta fase persiste e exibe.

### 3. Feedback é GRANT de coluna, como `read_at` na notificação

`portal_app` recebe `UPDATE (feedback, feedback_comment, feedback_at, updated_at)` em
`conversation_message`, e nada mais. A pessoa avalia a resposta; não reescreve o texto nem as
citações que ele mostrou.

É o que faz do histórico um **registro** e não uma alegação editável. Se "achei ruim" fosse licença
para trocar a resposta, o histórico deixaria de valer como prova do que o portal de fato respondeu —
e é justamente para isso que ele existe. Uma policy decide quais *linhas*, nunca quais *colunas*:
sem o grant, a policy de UPDATE abriria a linha inteira.

O voto é sobrescrito no reenvio, sem deduplicação: o polegar é o estado atual de uma opinião, não um
evento.

### 4. A linha tem dono

Policy = predicado de tenant (`organization_id` + `project_id`) **mais**
`user_id = portal.current_user_id()`, como em `notification`. Dois clientes do mesmo projeto não
leem a conversa um do outro — e o time interno, que alcança o projeto, também não: alcançar o
projeto não é alcançar a conversa de quem pergunta.

`user_id` é denormalizado em `conversation_message` pelo mesmo motivo que `project_id` é
denormalizado em toda tabela-filha (`db/base.TenantMixin`): a policy vira uma comparação de coluna
em vez de um `EXISTS` avaliado linha a linha.

### 5. As citações em JSONB, na mensagem, e não numa terceira tabela

Segue `audit_log.data`. Uma citação só faz sentido dentro da mensagem que a mostrou, e o produto
nunca a consulta sozinha. Cada item é `{evidence_id, source, location}`:

- `evidence_id` (`chunk-<uuid>`, `milestone-<uuid>`) é o que torna *"quais trechos são citados de
  fato"* respondível — o insumo que faltava para calibrar o corte de distância;
- `source`/`location` são o rótulo **como foi exibido**. Renomear o documento depois não muda o que
  a pessoa viu, e o registro é do que foi mostrado.

### 6. Id desconhecido abre thread nova em vez de derrubar o turno

Quando a gravação acontece, a pergunta já foi respondida. Devolver 404 por causa de um
`conversation_id` velho no cliente perderia a resposta para punir o cliente por um estado obsoleto.
Vale também para o id de outra pessoa: ele não abre porta nenhuma, apenas não é aproveitado.

É a mesma escolha de degradar em vez de derrubar que `queue_project_digests` faz com o broker morto.

## Consequências

- **`portal_app` passa a escrever em seis tabelas**, e `conversation`/`conversation_message` são as
  únicas em que ele *origina* o dado. A lista da ADR 0010 muda pela primeira vez desde a Fase 2.
- **O conteúdo da conversa passa a existir em repouso**, e é confidencial do cliente. Continua fora
  dos logs: `chat.pending_created` segue registrando o autor e não a pergunta — agora que a pergunta
  tem lugar próprio, duplicá-la na auditoria só aumentaria a superfície.
- **Retenção fica em aberto, e é dívida declarada.** Apagar conversas por organização é item da
  Fase 5; o que existe hoje é o CASCADE de projeto e de usuário, e `portal_app` não recebeu DELETE —
  quando o expurgo chegar, não será o caminho de requisição a fazê-lo.
- **O histórico corta pelo fim** (50 turnos). Uma conversa longa perde o começo, não o que acabou de
  ser dito. Não há paginação para trás; se a conversa virar longa o bastante para isso importar, é
  sinal de que multi-turno chegou antes.
- **Nenhuma dependência nova.** A migração 0012 é aditiva e o frontend usa o mesmo padrão de proxy
  BFF das rotas que já existiam.
- **O feedback ainda não tem tela de leitura.** Ele é gravado e ninguém o lê — de propósito: uma
  tela de análise sem dado acumulado mostraria zero. O que ela vai ler já está no formato certo.

## Alternativas consideradas

**Gravar sob `portal_system`, por um worker, mantendo `portal_app` sem INSERT.** Preservaria a
simetria com `document_chunk` e `notification`. Custaria uma janela entre responder e gravar — e um
turno respondido que some no reload é exatamente o problema que esta ADR existe para resolver. A
simetria também é falsa: aqui o request path origina o dado.

**Uma tabela `conversation_citation`.** Mais consultável em agregado. Custa uma terceira tabela com
policy própria e um JOIN em toda leitura de histórico, para responder uma pergunta que o JSONB
responde com um índice GIN quando (e se) ela aparecer.

**Guardar a conversa só no navegador (`localStorage`).** Zero migração, zero dado confidencial em
repouso. Não resolve nenhuma das três consequências do contexto: não atravessa dispositivos, não
torna a citação auditável e não produz sinal nenhum para calibrar a recuperação.

**Mandar o histórico ao respondedor junto do turno novo.** É o que o usuário espera de um chat, e
vai chegar. Mudaria o prompt, a superfície de injeção e o custo por turno de uma vez — três coisas
que não devem entrar na mesma mudança que introduz a tabela.
