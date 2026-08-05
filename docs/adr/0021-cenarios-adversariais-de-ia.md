# ADR 0021 — Cenários adversariais de IA, e o que o portal pode mesmo garantir

Data: 2026-08-05 · Fase 5 · FDD 015

## Contexto

Pela quinta vez na Fase 5 a fatia não implementou uma promessa adiada e sim uma que os
documentos davam como cumprida. Desta vez foram **quatro** promessas, e a última só apareceu
quando fomos ler o runbook para escrever esta ADR.

**1. "Prompts são versionados."** É a primeira frase do `docs/ai/prompt-policy.md`, e o docstring
do `ai/prompt.py` dizia "Versioned prompt". Não havia versão nenhuma no arquivo. Havia um
`chat_prompt_version = "chat-2026-08-03"` no `config.py` — e um grep pelo repositório inteiro
mostrou que **nenhum código o lia**. Uma setting decorativa é a pior forma de um controle falhar,
porque ela produz a evidência de que o controle existe. E o defeito não é só ela não ser lida:
uma versão que mora numa variável de ambiente é uma afirmação que o deployment faz sobre um texto
que ele não contém. Podia dizer `chat-2026-08-03` enquanto o prompt dizia outra coisa, e nada no
sistema notaria. Junto disso, `conversation_message` não carimbava nada, então uma resposta
guardada não sabia qual prompt a produziu — e o `evaluation-plan.md` manda rodar o dataset antes
de alterar modelo ou prompt, o que exige exatamente essa informação.

**2. As evals adversariais eram tautológicas.** O `eval-dataset.md` listava "documento com prompt
injection" e "prompt injection dentro do trecho" entre os catorze casos, e os catorze rodavam no
`OfflineResponder` — um casador determinístico por sobreposição de tokens, que **não tem como**
obedecer a uma instrução. Provar que ele resiste a injeção é provar que uma pedra não atende ao
telefone. Nenhum teste do repositório jamais construiu um `AnthropicResponder`, jamais enviou o
`SYSTEM_PROMPT` e jamais observou o que sai para o modelo; não havia sequer costura por onde
fazê-lo, porque o `import anthropic` acontecia dentro do método.

**3. Abuso de chat não tinha controle nenhum.** O `threat-model.md` prometia "rate limit, quotas e
auditoria" com verificação por "teste de carga". Não existia limite, não existiam quotas, não
existia o teste. E a ameaça aqui não é a conta de token: **cada lacuna grava uma `PendingItem`,
uma linha de `audit_log` e enfileira uma notificação**, então um laço de perguntas sem evidência
vira enxurrada na caixa do time interno — o portal atacando os próprios operadores.

**4. O runbook mandava procurar um evento que nunca é emitido.** O `ai-provider-failure.md` dizia
`grep '"event":"http.failed"'` para falha de resposta do chat. Mas `ai/service.py` engole *toda*
exceção do provedor para cair no respondedor offline, e o `http.failed` do `TraceMiddleware` só vê
exceção que sobe — então ele nunca dispara. O `logger.warning` que existia não tinha nome de
evento e usava interpolação, de modo que o `extra` que a ADR 0018 ensinou a ler não existia. Numa
queda real da Anthropic o chat degradaria em silêncio absoluto, respondendo pior sem nada ficar
vermelho e sem o grep do runbook devolver uma linha.

Escrevendo os testes apareceram mais dois, e são os dois que estavam mais perto de doer:

**5. `max_tokens=1024` com `thinking: adaptive`.** O teto vale para pensamento **mais** texto de
resposta. Um turno que pensasse novecentos tokens devolvia JSON truncado, o `json.loads`
levantava, e o defeito 4 engolia — fallback offline silencioso. Bug vivo, no modelo configurado,
esperando a primeira pergunta difícil.

**6. A tela inventava citação, e um teste protegia isso.** `answerFor()` tinha um único call site:
o `catch` do `sendQuestion`. Devolvia data inventada, decisão inventada, contagem de pendência
inventada e **rótulos de citação inventados** a um cliente autenticado de verdade cuja chamada
falhou — e marcava `pending: true`, de modo que a tela dizia "Pendência criada para Portal Labs"
para uma pendência que ninguém gravou. O `CLAUDE.md` afirmava desde a Fase 1 que "não há mais
fallback para dado inventado"; era falso, e justamente na única tela onde a regra 3 do
`AGENTS.md` vale por escrito. E `tests/rendered-html.test.mjs` afirmava que `function answerFor`
**estava presente** — a guarda segurava o defeito no lugar, na mesma forma que a ADR 0020 achou
nas asserções de backup que pulavam em silêncio a cada push.

A metade de **carga** do item do roadmap continua fora: sem ambiente de homologação, um número de
carga contra o `docker compose` mede o laptop de quem roda.

## Decisão

### 1. A versão do prompt mora ao lado do texto, e o registro força o bump

`PROMPT_VERSION` passa a viver em `ai/prompt.py`, na linha acima do `SYSTEM_PROMPT`, e
`chat_prompt_version` foi apagado das settings. O arquivo que guarda o texto guarda o nome dele.

O portão é um **registro append-only** (`docs/ai/prompt-registry.json`) com três digests por
versão — o prompt de sistema, o esquema de saída e a **moldura** do prompt do usuário (o
delimitador, o formato da linha de evidência e a linha da pergunta; nunca o conteúdo, que mudaria
a cada requisição). `python -m portal_api.ai.prompt --record` grava; `test_prompt_version.py`
cobra.

Não é uma constante de digest no próprio arquivo, e a diferença é a política inteira: uma
constante quebra quando o texto muda e ela não, mas quem atualiza os dois juntos **sem trocar a
versão** continua verde — e é exatamente esse o caso que a política existe para pegar. Contra o
registro isso não vira verde regenerando, porque `--record` recusa reescrever uma versão já
gravada cujos digests mudaram. O único caminho verde é uma versão nova. É o terceiro portão de
deriva do repositório, no idioma do `alembic check` e do `docs/api/openapi.json`.

### 2. O carimbo é da linha, não do contrato

`conversation_message` ganha `prompt_version`, `responder` e `model` (migração 0016), todos
anuláveis, no bloco que a 0012 abriu para o que só existe na mensagem do assistente — a pergunta é
da pessoa e nenhum prompt a produziu.

`responder` tem **três** valores e não dois. `offline_fallback` é um fato próprio: o portal tentou
o provedor, ele falhou, e a resposta saiu do casador determinístico. Sem esse valor, "por que as
respostas pioraram na terça?" só seria respondível pelo log — que a essa altura já rodou. É a
mesma razão pela qual `last_sync_error` mora na linha da conexão do Drive e `scan_state` na linha
do documento.

E os três **não** entram no `ChatOut`. Com `extra="forbid"` (ADR 0020) todo campo novo de resposta
vira compromisso que o esquema passa a ter de manter, e dizer ao cliente qual modelo respondeu
convida a discutir com a máquina em vez de com a evidência. O caminho interno é SQL mais o evento
`chat.answered`. Nenhum GRANT novo: GRANT é de tabela, `portal_app` já tinha `INSERT` desde a
0012, e o `UPDATE` continua restrito às quatro colunas de feedback — ninguém reescreve qual prompt
produziu a resposta, pelo mesmo motivo que ninguém reescreve as citações que ela mostrou.

### 3. A janela do chat é tabela própria, sob `portal_system`, em transação anterior

`chat_rate_window` (migração 0017): uma linha por `sub` do OIDC, com `window_started_at` e
`window_count`. Vinte perguntas por minuto por padrão (`CHAT_RATE_LIMIT`), contra os 120 da API de
eventos — a assimetria é o argumento: um agente é máquina e 120/min é vazão normal de ingestão;
20/min fica muito acima de alguém formulando uma pergunta pensada e muito abaixo do que um script
precisa para inundar de pendência o time interno.

**Não são colunas em `user`**, por duas razões independentes — e a segunda decide. A primeira:
estender o GRANT de coluna que a 0009 deliberadamente estreitou daria a quem é limitado escrita
sobre o estado do próprio limite. A segunda: `identity.resolve_user` roda **dentro** da transação
do chat e, no primeiro login, escreve `external_subject` — lock na linha. Uma segunda transação
mexendo na mesma linha esperaria o chat commitar, e o chat abrange a chamada ao modelo. Seria
travamento no caminho de primeiro login, descoberto em produção e não no CI. O precedente do
`agent_api_key` não transfere: lá a linha da chave é lida e incrementada numa transação só e nada
mais a toca.

Sem tenant na tabela, também de propósito: o limite é propriedade de uma pessoa, como `user`, e
por projeto seria pior que inútil — deixaria alguém abrir N projetos de cota. RLS ligada e
**nenhuma policy `TO portal_app`**, a forma de `agent_api_key` e `project_drive_connection`: o
papel de requisição herda o SELECT das default privileges e ainda assim lê zero linhas, porque a
regra não é sobre ele. E o `consume` roda em transação própria e anterior à do chat, para nenhum
lock atravessar a chamada ao modelo. O preço, declarado: um token válido sem projeto vê 429 antes
de 404 — o que não conta nada sobre projeto nenhum, só que a pessoa está autenticada, o que ela já
sabe.

Postgres e não Redis, pela razão da ADR 0013 e com mais força: a API sobe sem broker, e
`queue_pending_notification` já engole um broker morto de propósito. Uma dependência dura de Redis
no caminho de requisição deixaria o chat *menos* disponível que a notificação que ele dispara.

### 4. O respondedor ganha costura, e o teste ganha um Claude hostil

`ai/responder.py` ganha `anthropic_client(api_key)`, na forma de `google_drive.session_client`
(ADR 0016), e `apps/api/tests/anthropic_fake.py` traz um Claude de mentira que **registra o
pedido** e devolve o que um atacante escolheria. O falso emite um bloco `thinking` antes do
`text`, que é a forma real do fio com `thinking: adaptive` — um falso que devolvesse só o texto
deixaria passar um bug de `content[0].text`.

Catorze casos adversariais novos, e o primeiro é a guarda dos outros treze: *uma chave configurada
seleciona o respondedor real*. Sem ele, uma fixture quebrada faria o conjunto inteiro re-testar o
respondedor offline em silêncio — e um conjunto adversarial que não roda contra o alvo é pior que
nenhum, porque é lido como cobertura.

Continua determinístico e sem chave em CI: a chave é um literal de teste, e é uma das sentinelas
conferidas como **ausentes** do que sai para o modelo. É isso que mantém as evals como barreira de
CI e não como medição.

### 5. O que a fatia garante estruturalmente, e o que ela não pode garantir

Esta é a decisão mais importante, e é uma decisão de não fazer.

Garantido, e provado por teste contra um modelo que tenta o contrário: toda citação aponta para
evidência real e do tenant, porque `ai/service.py` descarta id desconhecido para **qualquer**
respondedor; afirmação factual sem citação real vira lacuna e pendência, nunca fato na tela; a
evidência de outro projeto não sai do processo dentro do pedido — o teste olha o que foi
*enviado*, não só o que voltou; a conversa gravada nunca é transmitida, então uma frase plantada
não pode nem ser citada nem ser parafraseada; e nenhum segredo do portal aparece no payload.

**Não** garantido: que um modelo remoto não parafraseie, dentro da própria `answer`, o texto de uma
instrução injetada numa evidência legítima. Contra isso o portal não tem garantia estrutural, e
**recusamos explicitamente acrescentar um filtro de saída**. Ele falharia na primeira paráfrase —
o atacante controla o texto e pode escrevê-lo de infinitas formas — enquanto criava a impressão de
que o problema acabou, que é a pior das duas situações. O que a conversão estrutural já remove é a
metade perigosa: uma afirmação sem citação real nunca chega ao cliente como fato, independente do
que o modelo tenha decidido dizer.

Registrar o limite é parte do controle. Um documento que promete mais do que o código faz é o
defeito que esta fatia inteira existe para fechar — não faria sentido fechar quatro e abrir o
quinto.

### 6. Os eventos passam a existir com o nome que o runbook já mandava procurar

`chat.provider_unavailable` (com `responder`, `model` e `reason`), `chat.answered` (com
`prompt_version`, `responder`, `model`, `confidence` e contagem de citações) e
`embedding.unavailable`. A mensagem **é** o nome do evento e o detalhe vai no `extra`, como a ADR
0018 estabeleceu.

`embedding.unavailable` tem nome distinto de `embedding.failed` de propósito: lá o documento fica
fora do índice até alguém reindexar, aqui o chat perdeu a metade documental de *uma* resposta e a
seguinte pode dar certo. Um nome só faria o limiar do `alerts.md` significar duas coisas, que é
como um alerta deixa de ser lido.

`ProviderRefused` separa recusa do classificador de parser quebrado: sem ela, uma recusa — que
devolve `content` vazio — chegava ao `json.loads` e o log dizia `JSONDecodeError`, mandando quem
lê o runbook procurar um bug que não existe.

### 7. A tela para de inventar, e a guarda troca de lado

`answerFor()` foi apagado. Um 429 vira uma mensagem de ritmo com os segundos do `Retry-After`
(que o proxy do BFF passou a repassar, já que `Response.json` descarta headers); qualquer outra
falha vira "não consegui falar com o assistente, nada foi registrado". Nenhum caminho fabrica
resposta ou citação, e a afirmação do `CLAUDE.md` sobre não haver mais dado inventado passa a ser
verdade.

A asserção de `rendered-html.test.mjs` que exigia a existência de `answerFor` virou
`doesNotMatch`, e ao lado dela entrou uma guarda sobre a **forma** e não sobre os rótulos: um
array de literais atribuído a `sources` no cliente do chat só pode ser citação inventada
localmente, porque toda citação verdadeira vem da API. Os mesmos nomes continuam em
`app/demo-overview.ts` como dado de dashboard, o que é legítimo e vive atrás do portão de
`demoShellEnabled()` — a guarda é do arquivo do chat, e o teste diz por quê.

### 8. Dois defeitos de parâmetro, corrigidos de passagem

`max_tokens` sobe de 1024 para 4096 e `output_config` ganha `effort: "low"`. Extrair citação de
alguns KB de evidência não é tarefa sensível a inteligência, e esse é o freio certo — desligar o
pensamento tem falhas próprias em modelos desta geração. O modelo padrão passa a `claude-opus-5`.

## Consequências

- **O prompt não pode mais mudar em silêncio.** Editar o `SYSTEM_PROMPT` sem trocar a
  `PROMPT_VERSION` reprova no CI, e regravar o registro não resolve. O custo é uma linha de diff a
  cada mudança de prompt, que é exatamente onde alguém deve olhar.
- **Uma resposta guardada passa a saber quem a produziu**, inclusive quando quem a produziu foi o
  fallback. É o que torna reexecutável uma eval sobre histórico real.
- **O chat pode responder 429.** É a segunda recusa não opaca do portal. A tela sabe explicá-la; o
  `openapi.json` a declara; e um teste prova o que importa — a requisição recusada não grava
  pendência nem mensagem.
- **Um teste existente precisou de teto maior.** O que exercita o corte do histórico faz 26
  perguntas seguidas e passou a esbarrar no limite. Levantar o teto ali é honesto: o que está sob
  teste é o truncamento, não o limite, que tem arquivo próprio. Vale como aviso — **não** baixar
  `CHAT_RATE_LIMIT` no compose, ou os specs de e2e que compartilham a mesma pessoa ficariam
  instáveis.
- **As evals deixaram de ser tautológicas** e passaram a custar um arquivo de falso a manter. Em
  troca, o `AnthropicResponder` deixou de ser código que nenhum teste executa — o que também
  revelou os defeitos 5 e 6.
- **A degradação do provedor deixou de ser silenciosa**, e o runbook passou a poder ser seguido ao
  pé da letra.
- **Continua sem quotas.** O `threat-model.md` foi corrigido para parar de prometê-las em vez de
  seguir prometendo; elas pertencem ao item de homologação.

## Alternativas descartadas

- **Colunas em `user` para a janela.** Descartada pelo lock: `resolve_user` escreve na linha
  dentro da transação do chat, que abrange a chamada ao modelo. Seria travamento no primeiro
  login, invisível no CI.
- **Redis para a janela.** Descartada pela ADR 0013 e reforçada aqui: tornaria o chat menos
  disponível que a notificação que ele dispara.
- **Cota por projeto.** Deixaria uma pessoa multiplicar a cota abrindo projetos — o oposto do que
  o controle quer.
- **Expor o carimbo no `ChatOut`.** Widening de contrato sob `extra="forbid"` sem audiência: o
  cliente não tem o que fazer com a versão do prompt, e saber o modelo convida a discutir com a
  máquina em vez de com a evidência.
- **Constante de digest no lugar do registro.** Deixaria passar exatamente o caso que a política
  quer pegar — texto e constante atualizados juntos, versão intacta.
- **Filtro de injeção na saída.** Argumentado na decisão 5: brittle, infalsificável e ativamente
  enganoso.
- **Spec e2e do limite de taxa.** Exigiria 21 idas ao modelo ou baixar o limite no compose, o que
  deixaria os outros specs de chat instáveis. A propriedade que vale provar no nível web é "um
  chat que falhou nunca vira resposta fabricada", e apagar `answerFor` com a guarda invertida
  prova isso com mais força que um navegador: prova que o código de fabricação não existe mais.
- **Unificar `agent_auth._check_window` e `chat_limit` num `rate_limit.py`.** Chaveiam coisas
  diferentes, vivem em transações diferentes por razões diferentes, e fundi-los faria "o que
  autentica um agente" deixar de caber num arquivo. Vinte e cinco linhas duplicadas são o erro
  mais barato.
