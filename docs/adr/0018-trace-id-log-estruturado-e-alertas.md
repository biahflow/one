# ADR 0018 — `trace_id`, log estruturado e alertas

**Status:** aceita — 05/08/2026
**Contexto:** Fase 5, segunda fatia. Fecha a metade de observabilidade do item de
`ROADMAP.md`; backup/restore continua aberto.

## Contexto

Ao contrário da ADR 0017, esta fatia não implementa uma promessa adiada: implementa
uma promessa que os documentos já davam como **cumprida**.

- `docs/runbooks/incident-response.md` abre mandando "preservar `trace_id`". Não
  havia `trace_id` em lugar nenhum do código — a busca por essa string encontrava
  o roadmap, o próprio runbook e nada mais.
- `docs/runbooks/agent-events-failure.md` manda `docker compose logs api | grep
  agent_key.rejected` e ler os campos `reason` e `key_prefix`. Os campos existiam
  no código desde a ADR 0013 (`logger.warning("agent_key.rejected", extra={...})`)
  e **nunca chegavam ao stdout**: sem handler configurado, o `logging` usa o
  formato padrão, que imprime a mensagem e descarta `extra`. O mesmo valia para
  `auth.rejected`, que `docs/security.md` chama de "log estruturado", e para
  `keycloak.failed`, `identity.linked`, `drive.object_not_removed`.
- `app/error.tsx` dizia ao cliente "A falha foi registrada". Não havia um
  `console.error` sequer em `app/`; `app/actions.ts` engolia a exceção num
  `catch {}` mudo e `app/page.tsx` lançava sem deixar linha.

Uma promessa não cumprida é dívida. Uma promessa **descrita como cumprida** é pior:
o runbook manda alguém procurar um campo que não existe no meio de um incidente, e
o tempo gasto até descobrir isso sai do tempo de resposta.

## Decisão

### 1. O identificador nasce no BFF, e não no `proxy.ts`

Uma requisição do navegador ganha um `trace_id` em `app/lib/trace.ts`, memoizado
com o `cache()` do React — cujo tempo de vida é exatamente o de uma requisição.
Uma variável de módulo daria o mesmo id a pessoas diferentes no mesmo processo; um
`randomUUID()` por chamada daria três ids para as três `fetch()` paralelas de
`app/page.tsx`. As duas alternativas falham no teste de `rendered-html.test.mjs`.

O `proxy.ts` seria a borda mais externa e **fica intocado**. Injetar header no
caminho de passagem exigiria devolver um `NextResponse.next({request:{headers}})`
de dentro do wrapper do Auth.js — que é justamente onde o cookie de sessão
renovado é escrito. O portão de sessão não é o lugar para correr esse risco, ainda
mais com o aviso de `npm audit` do `next` em aberto.

**O preço, dito por extenso:** a negação do próprio portão — o 401 em `/api/` e o
redirect das páginas — só carrega id quando quem chamou mandou um. É a única
fronteira do portal que fica de fora, e ela é observável pelo `auth.rejected` da
API quando a requisição chega lá.

### 2. Um ponto de costura, e ele já existia

`authorizationHeader()` (`app/lib/session.ts`) passa a devolver `X-Request-ID` ao
lado do `Authorization`. Os treze call sites que falam com a API montam o header
por ali, e o `CLAUDE.md` já manda toda chamada nova sair de lá — então uma rota
futura ganha o id sem ninguém lembrar de pedi-lo, do mesmo jeito que ganha o token.

Nenhum dos treze arquivos foi tocado.

### 3. Na fila o id viaja em header da mensagem, nunca em argumento

Um par de sinais do Celery (`before_task_publish`, `task_prerun`) carimba e lê. A
alternativa — um parâmetro `trace_id` em cada task — obrigaria a mexer em todo
`.delay()` do repositório e, pior, uma mensagem publicada antes de um deploy
chegaria a um worker que espera um parâmetro a mais. Um header é ignorado por quem
não o conhece.

Task nascida do beat não tem pai: cunha o próprio id e o marca `root: "beat"`. Um
tick agendado não continua a história de ninguém, mas ainda precisa ser
encontrável por um identificador só.

### 4. Formatter da biblioteca padrão, sem dependência nova

`structlog` e OpenTelemetry ficam de fora pelo mesmo instinto que mantém o e-mail
em SMTP puro em vez de um SDK de provedor: o formato é um `json.dumps`. O que o
formatter faz de específico é derivar os campos de `extra` por diferença com os
atributos padrão de um `LogRecord` — é essa diferença que faz `reason` e
`key_prefix` aparecerem sem que nenhum call site mude de forma.

Ele também **redige** campos cujo nome denuncia segredo (`token`, `secret`,
`password`, `authorization`, `cookie`, `key`), com `key_prefix` numa allowlist
obrigatória: o prefixo é a parte pública da credencial, é o que já fica em claro no
banco, e é do que o runbook depende para dizer *qual* chave foi recusada. A regra 5
do `AGENTS.md` ("não inclua segredos em logs") passa a ser cumprida pelo código, e
não pela disciplina de quem escreve o próximo `extra={}`.

Métrica e exporter **não** entram aqui. Eles pertencem ao item de homologação do
roadmap, que é quando existirá para onde mandá-las; um `/metrics` sem coletor seria
outra promessa escrita sem implementação, que é o defeito que esta ADR corrige.

### 5. O `trace_id` entra no `audit_log.data`

Sem migração: a coluna já é JSONB. Um helper `audit_data(**fields)` carimba, para
um `AuditLog` novo não conseguir esquecer. É o que torna verdadeira a primeira
linha do runbook de incidente: da linha de auditoria se chega ao log, e do log se
volta à linha.

### 6. Alerta é evento nomeado, limiar escrito e algo que possa ficar vermelho

`docs/runbooks/alerts.md` lista evento → limiar → runbook, e separa
explicitamente o que **não** é alerta: `drive.rejected` e `auth.rejected` são o
controle funcionando, e tratá-los como incidente ensina a equipe a ignorar o
painel.

Nasce `GET /health/ready`, que toca o Postgres e o Redis, separado do `/health`
estático porque "o processo respondeu" e "dá para mandar tráfego" são perguntas
diferentes com consequências diferentes. **O corpo é sim/não**: sem versão, sem
hostname, sem DSN e sem dizer qual dependência caiu — a rota é pública, e um `down`
é indistinguível de outro pela mesma razão que o 401 da `auth.py` é opaco. O motivo
vai inteiro para o log, agora com um id para ser encontrado.

`api`, `worker` e `web` ganham healthcheck no compose; nenhum dos três tinha, e por
isso o `/health` nunca era consultado por ninguém. O **`beat` fica sem, de
propósito**: o tick mais curto é de 15 minutos e o mais longo é diário, então
qualquer sonda barata responderia "saudável" para um beat que parou de agendar. Um
check que sempre passa é pior que nenhum — é a regra do `skipped` da ADR 0017
aplicada à saúde. O sinal de verdade é a **ausência**: nenhum `task.started` com
`root=beat` dentro de duas vezes o intervalo.

## Consequências

- Todo log de API e worker vira uma linha JSON. `LOG_FORMAT=text` devolve o formato
  legível do dia a dia — e **também** imprime os campos de `extra`, porque
  descartá-los era o defeito, não o formato.
- Uma requisição pode ser reconstruída ponta a ponta: navegador → BFF → FastAPI →
  Celery, e de volta à linha de `audit_log`.
- `app/error.tsx` mostra o `digest` como "Código". `instrumentation.ts` registra
  esse mesmo `digest` junto do `trace_id`, que chega até lá dentro de um
  `TracedError` — o `onRequestError` recebe o objeto lançado antes de o Next o
  sanear para o cliente. Sem isso os dois só se juntariam por horário.
- Dois defeitos de configuração de logging apareceram ao implementar isto, e os
  dois silenciavam a aplicação inteira, não só a telemetria nova:
  - `alembic/env.py` chamava `fileConfig` com o padrão
    `disable_existing_loggers=True`, que marca `disabled` em todo logger
    `portal_api.*` já criado. Quem roda a migração no mesmo processo da aplicação
    ficava sem log depois dela.
  - O `setup_logging_subsystem` do Celery faz o mesmo por cima da configuração do
    worker. Um receptor conectado ao sinal `setup_logging` faz o Celery pular a
    configuração inteira, que é o contrato documentado dele.

## Alternativas descartadas

- **OpenTelemetry com exportador OTLP.** É o destino provável, e continua
  disponível: `trace_id` num contextvar é exatamente o que um `SpanProcessor`
  consumiria depois. Adotá-lo agora significaria escolher coletor, endpoint e
  amostragem antes de existir um ambiente que os hospede.
- **Middleware `BaseHTTPMiddleware` do Starlette.** Executa o resto da aplicação
  dentro de um task group do anyio, o que põe uma camada entre onde a
  `ContextVar` é escrita e onde é lida, e obrigaria a depender do `starlette` pelo
  nome. O middleware é ASGI puro, em trinta linhas.
- **Cunhar o id no `proxy.ts`.** Ver a decisão 1 e o preço declarado ali.
- **Trocar a cópia de `app/error.tsx`** para deixar de prometer registro, em vez de
  passar a registrar. Seria honesto e mais barato, e deixaria o portal sem a única
  coisa que o cliente pode dizer ao suporte além de "não funcionou".
