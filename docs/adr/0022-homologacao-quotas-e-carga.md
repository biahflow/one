# ADR 0022 — O ambiente, a quota e a carga, nessa ordem

Data: 2026-08-05 · Fase 5 · FDD 016

## Contexto

Os dois últimos itens abertos da Fase 5, e um dependia do outro pelo argumento que o próprio
roadmap registrava: *"sem orçamento declarado, um número de carga contra o `docker compose` mede
o laptop de quem roda"*. As quotas ficaram junto porque a ADR 0021 entregou rate limit e
auditoria, **corrigiu o `threat-model.md`** para parar de prometer a terceira, e a deixou
explicitamente para cá.

Pela sexta vez na Fase 5 a fatia não implementou uma promessa adiada e sim uma que os documentos
davam como cumprida. E desta vez ela era a **causa técnica** de a carga não ser mensurável.

**1. As variáveis do chat nunca chegaram ao contêiner.** `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` e
`CHAT_RATE_LIMIT` existem no `.env.example` desde a Fase 3, são lidas pelo `config.py`, e um grep
pelo repositório inteiro mostrou que **nenhum compose e nenhum workflow as passava** ao serviço
`api`. O `AnthropicResponder` que a ADR 0021 acabou de construir, costurar e testar com um Claude
hostil **nunca rodou na pilha de pé**: o e2e, o navegador e qualquer medição local exercitavam o
casador offline, sem erro nenhum no log — porque a ausência de chave é um caminho legítimo (ADR
0007). Medir carga contra isso mediria o Postgres.

E a ADR 0021 chegou a escrever, nas consequências, "**não** baixar `CHAT_RATE_LIMIT` no compose,
ou os specs de e2e ficariam instáveis". O aviso falava de uma variável que o compose não lia.

Generalizado, o defeito pegou mais doze: `BIAHFLOW_READ_TOKEN` e `BIAHFLOW_WEBHOOK_SECRET`,
`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_STARTTLS`, `NOTIFICATIONS_FROM_NAME`,
`DOCUMENT_DOWNLOAD_TTL_SECONDS`, `LOG_LEVEL`/`LOG_FORMAT` e o
`DRIVE_TOKEN_ENCRYPTION_KEY_PREVIOUS` **de que a rotação de chave da ADR 0016 depende** — a
variável existe para que rotacionar não obrigue todo projeto a reconsentir, e ela não chegava a
lugar nenhum. Mais uma que não existe em canto algum: `MINIO_ENDPOINT`, sem setting
correspondente, documentada e morta.

**2. "custo/latência de IA" era um indicador que nada media.** `docs/observability.md` o listava
enquanto o `response.usage` que a SDK devolve em **toda** resposta era simplesmente descartado.
Não havia coluna, evento, setting ou tabela de token, gasto ou orçamento no repositório inteiro.

**3. O `docs/security.md` prometia uma seção de TLS que não existia.** A linha de controles dizia
"*(Implementado na ADR 0017, menos o TLS — ver a seção própria abaixo)*", e não havia seção
abaixo.

E ao tentar escrever o ambiente apareceu o risco que nenhum documento mencionava: **todo `${VAR}`
do `docker-compose.yml` tem default local**. `AGENT_KEY_PEPPER` cai em `agent-pepper-local-only`,
`AUTH_SECRET` em `portal_auth_local_only`, `DRIVE_TOKEN_ENCRYPTION_KEY` numa chave base64 que
está no `.env.example`. Um `.env` de homologação a que falte uma chave **sobe verde, com o
segredo do exemplo**. Nada fica vermelho, nada avisa.

## Decisão

### 1. Homologação é código e portão de CI, não infraestrutura provisionada

A fatia entrega `docker-compose.homolog.yml`, `infra/caddy/Caddyfile`, `.env.homolog.example` e
`docs/runbooks/deploy.md`. Ela **não** provisiona máquina, DNS nem backup agendado: isso é
decisão de infraestrutura que não pertence a este repositório, e escrevê-la aqui como se
estivesse feita seria o defeito que a Fase 5 inteira existiu para fechar.

O que muda entre local e homologação é um arquivo de override e um `.env`. Os três dublês locais
saem — `mailpit`, `drive-stub` e o `api-seed`, que semeia dado de demonstração —, o Keycloak
deixa `start-dev`, e **um único serviço publica porta**: o Caddy, que termina o TLS.

A API não é publicada, e isso é a ADR 0010 e não economia: o navegador nunca fala com ela, porque
o access token vive no cookie cifrado do BFF e a autorização é decidida no servidor. Publicá-la
daria à internet um caminho que o portal não usa.

### 2. `${VAR:?}` no lugar de `${VAR:-default}` — e mais uma barreira depois dele

No override, todo segredo é `${VAR:?mensagem}`: o compose **recusa** em vez de herdar. É a forma
do `BACKUP_AGE_RECIPIENT` do `scripts/backup.sh`, que prefere não fazer backup a fazer um em
texto claro, e a do `AGENT_KEY_PEPPER` vazio, que prefere não autenticar ninguém.

E `portal_api/preflight.py` recusa a **subida do processo** — na importação do módulo, não numa
rota de saúde, porque um processo que já respondeu uma requisição com a senha do exemplo não tem
como desfazer isso.

São dois mecanismos porque um só não bastava, e as razões são independentes: o compose protege
apenas quem sobe por ele, e `${VAR:?}` só sabe perguntar se a variável **tem** valor, nunca se o
valor é seu. Presença não é qualidade.

Duas escolhas de forma dentro do `preflight`:

- **A varredura por sentinela é genérica**, sobre todo valor de texto das settings, não uma lista
  de campos. Uma setting nova com default local já nasce coberta — o idioma do
  `test_openapi_contract.py`, que afirma sobre toda rota inclusive a que ninguém escreveu ainda.
  Uma lista protegeria os campos de que alguém lembrou no dia em que escreveu o módulo.
- **A recusa junta todos os problemas numa mensagem só.** Quem configura um ambiente novo erra em
  cinco variáveis, e uma recusa por vez vira cinco ciclos de deploy.

Consequência que fecha o círculo: o `.env.homolog.example` é um arquivo que o `preflight`
**recusa**. `CHANGEME` é uma das sentinelas, então o template documenta a forma de uma
configuração sem poder ser uma.

### 3. A quota guarda tokens, e o dinheiro nasce na leitura

Três tabelas (migração 0018) com papéis diferentes de propósito: `ai_usage_event` é o **razão**,
`organization_ai_quota` é a **política**, `ai_model_price` é o **preço com vigência**.

O razão guarda tokens, nunca dinheiro. O custo é calculado pelo preço vigente **no dia da
chamada**, o que é literalmente `results.py` e pelo motivo dele: reajustar o preço do modelo hoje
não pode reprecificar março. `ai_model_price` reusa o `EXCLUDE USING gist` da premissa financeira
(ADR 0013). Uma coluna `cost_cents` gravada na ingestão seria mais barata de somar e passaria a
mentir no primeiro reajuste — sem que nada notasse, porque o número já estaria lá.

**Não é um contador incrementado, e quem disse isso foi o `chat_limit.py`.** O docstring daquele
módulo declara que *"sob concorrência alta o contador subconta, o que é aceitável para um limite
de abuso e seria **inaceitável para um contador de faturamento**"*. Este é o contador de
faturamento. Um `UPDATE ... SET total = total + n` é leitura-modificação-escrita e duas perguntas
simultâneas perdem uma das somas; um `INSERT` por chamada não disputa com nada, e a soma vira um
`SUM` na leitura.

`ai_model_price` **não tem tenant**: preço de modelo é fato do mundo, e dar-lhe
`organization_id` sugeriria que se negocia por cliente. A consequência fica registrada na
migração porque quem ler depois vai procurá-la — o meta-teste de `test_rls_isolation.py` não
cobra policy dela, e não é esquecimento: ele cobra de toda tabela com `organization_id`, e esta
não tem uma. Mesma situação de `chat_rate_window`.

`portal_app` ganha `INSERT` em `ai_usage_event`, o que é raro aqui e tem o precedente exato da
ADR 0015: o papel de requisição escreve quando **origina** a linha, como faz com `conversation`.
Não ganha `UPDATE` nem `DELETE` — **ninguém reescreve o que uma chamada custou**, pela mesma
razão pela qual ninguém reescreve as citações que uma resposta mostrou.

### 4. Sem preço vigente, o turno passa

É a única falha **aberta** de um repositório que falha fechado em quase tudo, e a razão é
assimetria de recuperação: o razão guardou o fato (os tokens), então um preço que falta pode ser
aplicado retroativamente amanhã; uma pergunta recusada hoje porque alguém trocou
`ANTHROPIC_MODEL` sem cadastrar o preço não volta.

A lacuna é declarada, não escondida — `ai_quota.price_missing` no log, `alerts.md` com a entrada,
e o `gaps` no corpo da rota de administração, na forma de `results.py`: base ausente devolve o
que dá para calcular **mais** a razão do que falta, nunca um zero silencioso que se lê como "não
gastou nada".

### 5. A recusa é 429, vem depois do 404, e não deixa rastro

429 e não 403, e não por preferência: `test_openapi_contract.py` reprova qualquer rota que
declare 403 (ADR 0020). 402 diria "pague", que é falso — quem pergunta não é quem contrata. O
`Retry-After` aponta para a virada do mês, e é por ele — e não pelo texto, que é opaco no resto
da API — que a tela e o harness separam esta recusa da janela de um minuto.

A checagem acontece **depois** da resolução do projeto, ao contrário do limite de taxa da ADR
0021, e a diferença de ordem é deliberada: sem projeto não há organização a que cobrar, e recusar
antes contaria a quem não tem vínculo que a organização existe.

E, como no limite de taxa, a requisição recusada não deixa rastro: sem pendência, sem mensagem e
**sem consumo**. A recusa não pode custar o que ela existe para evitar.

### 6. O harness de carga tem orçamento fail-closed e um relatório que declara o que mediu

`scripts/loadtest.py` mora em `scripts/` pela razão do backup: é operação, não aplicação (ADR
0019). Bate na API e não no BFF, porque é ali que estão a busca vetorial e a chamada ao modelo;
incluir o salto do Next.js misturaria renderização à medição, e o relatório diz isso.

**Com `ANTHROPIC_API_KEY` configurada ele recusa rodar sem `--budget-usd`.** Era esta a exigência
que o roadmap fazia ao adiar a carga, agora executável em vez de prosa. E o custo vem do razão —
o harness chama `ai/quota.py`, o mesmo código que recusa perguntas em produção — e não de uma
tabela de preços própria, que poderia discordar dele e as duas estariam erradas em silêncio.

**O relatório declara o que mediu**: `is_homologation: false` e uma nota em texto quando
`ENVIRONMENT=local`, uma nota quando não havia chave, e uma quando `offline_fallback` aparece no
`responder_mix` — nesse caso o provedor degradou no meio da execução e os percentis descrevem o
casador local, não o modelo. É a regra do `testing-strategy.md`, *um pulo não é um teste que
passou*, aplicada a uma medição: um número sem a condição em que foi obtido é pior que nenhum,
porque alguém o cita depois.

### 7. O passo é por conta, e isso foi medido e não deduzido

`CHAT_RATE_LIMIT` são 20 perguntas por minuto **por pessoa**, então a carga é distribuída entre N
contas e a vazão honesta é `N × 20/min`.

A primeira execução do harness rodou sem passo e devolveu **12.839 recusas para 62 respostas**:
mediu o limitador com muita precisão e o sistema com nenhuma, porque os percentis saíram de 62
amostras. Um gerador de carga que ignora o controle de admissão do alvo não está medindo o alvo.

A segunda, já com passo, ainda deu 4 recusas em 20 requisições a 90% do teto agregado — porque 4
workers sobre 3 contas sobrecarregam uma delas enquanto a vazão total ainda está abaixo do teto.
Daí o passo ser calculado **por conta** e a concorrência padrão ser o número de contas. A
terceira execução deu 18 respostas em 18 requisições.

## Consequências

- **O `AnthropicResponder` passa a poder rodar na pilha.** Preencher `ANTHROPIC_API_KEY` no
  `.env` agora muda o comportamento do compose, o que até esta fatia não acontecia. Um teste
  parametrizado exige as cinco variáveis no serviço `api`, e outro proíbe qualquer variável do
  `.env.example` que não chegue a contêiner nenhum — a generalização do defeito.
- **O segredo do exemplo não atravessa a fronteira.** O CI afirma as duas metades: o override
  recusa sem segredos, e valida com o template.
- **A conta de IA passa a ter dono e teto.** `docs/observability.md` deixa de listar um indicador
  que nada media, e o `threat-model.md` deixa de dizer "quotas não existem".
- **O chat pode responder 429 por um segundo motivo**, e a tela os distingue pela ordem de
  grandeza do `Retry-After`. Um teste prova o que importa: a requisição recusada não grava
  pendência, mensagem nem consumo.
- **A carga tem ferramenta, mas ainda não tem linha de base**, e o relatório é explícito sobre
  isso. A primeira execução contra o ambiente real é que abre a série; comparar um p95 de laptop
  com outro seria pior que não ter nenhum.
- **As imagens deixaram de ser de desenvolvimento.** A da API instalava `requirements-dev` e
  copiava `tests/` para dentro; as duas rodavam como root. A imagem web caiu de 1,86 GB para
  955 MB.
- **`directAccessGrantsEnabled` passou a `true` no realm local**, e só nele. Ali não custa nada —
  todas as senhas daquele realm são `portal_local_only` e estão versionadas —, e o
  `deploy.md`/`load-test.md` dizem por que o realm de homologação **não** deve segui-lo.

## Alternativas descartadas

- **Provisionar a homologação nesta fatia.** Escolha declarada de quem pediu, e a certa: a
  entrega é o ambiente como código com portão de CI, e provisionar sem host, domínio e orçamento
  reais teria produzido documentação de algo que ninguém subiu.
- **Reaproveitar `chat_rate_window` com janela mensal.** O docstring dele proíbe: aquele contador
  subconta por desenho, e para uma conta isso é inaceitável.
- **Gravar `cost_cents` no razão.** Mais barato de somar, e passa a mentir no primeiro reajuste
  sem que nada acuse. É a decisão que a ADR 0013 já tinha tomado para o ROI.
- **Quota por projeto.** Deixaria uma pessoa multiplicar a cota abrindo projetos — a ADR 0021 já
  havia recusado pelo mesmo argumento, e aqui vale mais, porque quem paga é a organização.
- **Recusar o turno quando falta preço vigente.** Falha fechada seria coerente com o resto do
  repositório e errada aqui: derrubaria o chat de todo mundo no dia em que alguém trocasse o
  modelo, para proteger um número que os tokens gravados permitem recalcular depois.
- **Retry com recuo no 429 do provedor.** Transformaria uma recusa de ritmo numa latência que
  ninguém explica; a decisão de esperar pertence a quem paga a conta.
- **Expor consumo ou custo no `ChatOut`.** Widening de contrato sob `extra="forbid"` sem
  audiência, pela razão exata que a ADR 0021 usou para não expor a versão do prompt.
- **Habilitar `directAccessGrants` no client de login de homologação.** Uma senha vazada passaria
  a valer um token sem passar pelo navegador. O `load-test.md` traz as duas saídas honestas.
- **Rodar a carga em CI como medição.** Mediria o runner. O que roda lá é um smoke de quinze
  segundos cujo objetivo declarado é a ferramenta não apodrecer — a lição que a ADR 0021 aprendeu
  do jeito caro com o respondedor que nenhum teste executava.
