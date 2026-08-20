# Roadmap — Portal Labs

Este documento acompanha o plano de entrega. Itens concluídos permanecem aqui para dar visibilidade ao que já existe; cada nova funcionalidade deve ter FDD, testes e atualização deste roadmap.

> **13/08/2026 — o portal do cliente está fora do ar, por decisão de produto.** A jornada do
> cliente passa a ser conduzida no WhatsApp, e o portal volta quando houver quem o opere
> (ADR 0053). Saíram da GCP `portal-web`, `portal-api`, `keycloak`, `portal-worker`, `portal-beat`
> e `portal-migrate`, com o state `ambientes/hml-portal` e os vinte segredos que eram deles; o
> `deploy-hml.yml` perdeu o gatilho de push e continua sendo a receita de como o portal sobe.
> **Nada abaixo foi revogado:** as Fases 1 a 6 seguem entregues, testadas e verdes no CI — elas só
> não estão servindo cliente. Isto muda o que cada `[x]` deste arquivo significa, e é por isso que
> está no topo.

## Operação na Engineering OS

Este arquivo é o índice canônico de descoberta de trabalho. Para funcionalidades com FDD, a FDD
é o contrato detalhado e dona do estado do ciclo; ADRs registram decisões e RFCs preservam
contexto e trade-offs. O histórico abaixo é preservado. A convenção prospectiva, inclusive planos,
contratos de tarefa e evidências, está em [`docs/features/README.md`](docs/features/README.md).

## Trabalho ativo

| Feature | Prioridade | Estado | Contrato | Dependência ou condição |
| --- | --- | --- | --- | --- |
| `F-020` — Funil de onboarding: vigília de IA | Não selecionada | `BLOCKED` | [FDD 020](docs/fdd/020-funil-de-onboarding.md) | Histórico suficiente para priorização segura da IA. |
| `F-022` — Pesquisa de satisfação por evento | Não selecionada | `BLOCKED` | [FDD 022](docs/fdd/022-pesquisa-de-satisfacao-por-evento.md) | Laço de ação do funil fechado de verdade. |

`Não selecionada` não é prioridade implícita: exige seleção humana antes de especificação,
planejamento ou execução.

E as duas carregam, desde 13/08/2026, um bloqueio a mais que **não é de negócio**: os dois sinais
da Fase 7 medem engajamento de cliente no portal, e não há portal no ar para medir. A condição
escrita na tabela continua valendo; esta se soma a ela.

## Concluído — Fundação local

- [x] Interface responsiva do dashboard e chat demonstrável.
- [x] Docker Compose com web, API, worker, PostgreSQL + pgvector, Redis, MinIO, Keycloak e Mailpit.
- [x] Documentação de produto, arquitetura, segurança, IA, ADRs, RFCs, FDDs e runbooks.
- [x] Contratos iniciais de API para dashboard, chat e eventos de agentes.
- [x] Pirâmide inicial: testes web renderizados, testes de API, lint e CI com build Docker e
      dependency review. *Corrigido em 05/08/2026 (ADR 0023): esta linha dizia "e CodeQL", e o
      `codeql` está **desligado por variável** desde sempre — ele não passa até que code scanning
      seja habilitado nas configurações do repositório, que é ajuste de conta privada e não de
      workflow (`ci.yml` explica). A varredura de dependências que de fato reprova chegou só na
      Fase 5, no job `dependency-audit`.*

## Concluído — Migração do runtime web (04/08/2026)

- [x] **Frontend passou a ser Next.js de verdade.** O build era `vinext` (React 19 RSC sobre
      Vite) empacotado como Cloudflare Worker; agora é Next.js 16 servido por `next start` em
      Node, no mesmo Docker Compose dos demais serviços. Saíram `worker/`, `vite.config.ts`,
      wrangler e a camada Drizzle/D1 (que estava vazia e desligada). Ver `docs/adr/0009`.
      *Pré-requisito da Fase 1: destrava `proxy.ts`, `cookies()` e Auth.js v5 com Keycloak, em
      vez de escrever PKCE e cookie de sessão à mão sobre Web Crypto.*
- [x] **Tailwind v4 como camada de estilo.** Estava instalado e importado, mas quase sem uso —
      o visual eram ~200 linhas de CSS artesanal com `font-family: Arial`. Agora os tokens
      vivem em `@theme` e os componentes em `@layer components`. Marca roxa preservada,
      tipografia Inter, conteúdo e layout inalterados.

## Fase 1 — Dados, identidade e acesso

- [x] Criar modelos, migrações Alembic e repositórios para organização, projeto, membros, marcos, entregas, pendências, documentos, reuniões, decisões, métricas e auditoria. *(Concluído: além da fatia inicial, documentos, reuniões, decisões e eventos de agentes — tabela idempotente por `external_event_id` — na migração `0002_knowledge_and_events`. Só a camada de dados; o cálculo de ROI sobre os eventos fica na Fase 3.)*
- [x] Aplicar Row-Level Security no PostgreSQL e contexto de tenant por transação.
      *(Migração `0007_rls_tenant_context`: 15 tabelas com policy, contexto em GUCs por
      transação e três papéis no Postgres — sem separar credencial as policies seriam
      decorativas, porque superusuário ignora RLS. ADR 0010, FDD 007.)*
- [x] Integrar Keycloak ao BFF Next.js e à API FastAPI com OIDC/PKCE e sessão segura.
      *(Realm com client confidencial e mapper de audiência; Auth.js v5 no BFF com `/login`,
      `proxy.ts` e o access token só no cookie cifrado; a API valida o JWT contra o JWKS e o
      `X-Portal-User` não existe mais. ADRs 0003 e 0010, FDD 007.)*
- [x] Convite e verificação de e-mail via Mailpit.
      *(`POST /api/v1/admin/projects/{id}/members` cria a conta no realm e pede ao Keycloak o
      e-mail de definir senha + verificar endereço — `UPDATE_PASSWORD` e `VERIFY_EMAIL` numa
      ação só. O `tests/e2e/invite.spec.ts` lê a mensagem na caixa do Mailpit e completa o
      fluxo. ADR 0011, FDD 008.)*
- [x] Implementar papéis `internal_admin`, `internal_member` e `client_member`, com associação
      explícita por projeto. *(`access.require_project` sobre a `membership`; o realm role é só
      indício. Eventos de agente exigem `internal_admin`; negação é 404, nunca 403.)*
- [x] Substituir os dados de demonstração do dashboard por consultas reais e dados seed versionados para desenvolvimento.
      *(O BFF manda `Authorization: Bearer` e projeta `GET /api/v1/me` + o dashboard. 401 leva a
      `/login`, 404 diz "sem projeto atribuído" e falha de rede vira painel de erro — nenhum
      caminho leva a dado inventado, e há teste que prova. O seed (`portal_api.seed`) entra pelo
      `sync_snapshot()` com um snapshot versionado, alinhado por `sub` ao realm.)*
- [x] Criar UI de administração **de acesso**: membros de cada projeto, convite e revogação
      (`/admin`). *(Organizações e projetos ficaram deliberadamente de fora: eles vêm do
      snapshot do Biahflow, e originá-los aqui dividiria a fonte da verdade — mesma razão da
      ADR 0008 para status. Escrita em `membership` só pelo papel `portal_admin`, com policies
      próprias e a GUC de terceiro estágio; ADR 0011.)*
- [x] **A corrida do primeiro login.** *(Defeito 7 da ADR 0052, corrigido em 12/08/2026 no commit
      `58a831a`.)* `identity.resolve_user` seleciona e depois insere, e o BFF busca `/me` e o
      dashboard **em paralelo** — é o desenho, e está escrito no `CLAUDE.md`. No primeiro login de
      quem o banco não conhece, as duas requisições chegam a `_provision` com o mesmo `sub`: uma
      ganha, a outra bate em `uq_user_email`, a tela diz "não conseguimos carregar seu projeto" e
      recarregar resolve — porque aí a linha existe. **Ninguém tinha visto porque o compose semeia
      os usuários**, então o caminho exercitado é sempre o de reivindicar linha semeada; "primeiro
      login de quem o banco não conhece" só acontece contra banco de verdade sem seed, e foi a
      primeira subida em HML (ADR 0052) que o produziu. `test_identity_concorrente.py` é a
      regressão.

**Aceite:** um cliente autenticado só consegue consultar os projetos aos quais pertence;
tentativas de acesso cruzado falham na API, no banco e na busca. *Atendido nas três camadas.
API e banco desde a própria Fase 1 (`test_authorization.py`, `test_rls_isolation.py`, e o e2e de
login em `tests/e2e/`). **A busca só passou a existir na Fase 6** (ADR 0024): esta linha dizia
"chega com o RAG da Fase 4, e o filtro por organização/projeto é requisito dela", a Fase 4 veio
e passou, o RAG chegou — e alimentou o **chat**, que é outra coisa. O campo da lupa continuou
sendo um `<input>` sem handler prometendo "buscar no contexto do projeto" por mais duas fases.
Hoje `test_search.py::test_a_term_only_the_other_project_uses_finds_nothing` executa a tentativa
cruzada, e o que a torna significativa é a segunda metade: o dono do outro projeto acha o mesmo
termo pela mesma rota.*

## Fase 2 — Jornada do projeto

- [x] ~~Implementar CRUD interno de status, entregas, cronograma, decisões e documentos.~~
      **Superado pela ADR 0006:** o Biahflow é a fonte da verdade e o portal nunca origina
      status. A digitação continua só no Biahflow e chega aqui por snapshot/webhook — um CRUD
      no portal dividiria a fonte da verdade. Ver também `docs/adr/0008`.
- [x] Implementar pendências com responsável, estados e histórico (abertas/resolvidas), com
      distinção de origem: espelhadas do Biahflow vs. abertas pela IA por lacuna de contexto,
      que sobrevivem ao sync (`PendingItem.origin`, migração `0006_portal_sync_fields`).
      **Comentários feitos em 06/08/2026 (ADR 0032)** — a única das três fatias com schema novo,
      porque aqui não havia nada meio-feito: comentário não existia em lugar nenhum. Cliente e
      time escrevem no fio da pendência; ninguém reescreve (`portal_app` só recebeu `INSERT`, e o
      `SELECT` já vinha do default privilege); e a decisão que carrega a fatia é o **escopo**: a
      policy é de tenant simples, e não de pessoa como a da conversa — o mesmo critério que a
      ADR 0030 usou para decidir o oposto, a quem o texto foi endereçado. Não volta para o
      Biahflow (a integração é unidirecional), e o custo declarado é uma segunda caixa de entrada
      para o time, contra a qual a notificação `pending_commented` é o remédio — e ela **não avisa
      quem escreveu**, o que exigiu `exclude_user_id` no `fan_out`. De quebra, dois campos que
      faltavam no payload: o `id` da pendência (a chave de render era o título) e o
      `comment_count`, cobrado sozinho pela guarda da ADR 0029. **Vínculo a conversas feito em 06/08/2026 (ADR 0031),
      e ele também não estava "pendente":** o FK `conversation_message.pending_item_id` existia
      desde a ADR 0015 e era lido **como booleano** (`pending_created`), então o cliente via
      "aberta pela IA" e não tinha volta à pergunta. A implementação mudou de desenho ao medir:
      as pendências da IA vivem em conversas antigas e o chat carrega só a corrente, então a
      primeira versão abria o painel sem nada a destacar — foi preciso levar a *thread* no payload
      e uma rota para abri-la. **Prioridade feita em 06/08/2026
      (ADR 0029), e ela não estava "pendente":** havia coluna com enum desde a Fase 1, campo no
      `PendingOut`, chave no payload e até declaração no tipo `ApiPending` do BFF — que a
      **descartava** no mapeamento. E a causa era mais funda: `sync_snapshot` nunca lia
      `priority`, o snapshot do Biahflow não carregava o campo, e nenhum documento o mencionava.
      Quatro camadas presentes e nenhum produtor.
- [x] Criar central de notificações e e-mails via Mailpit local/provedor configurável em produção.
      *(O produtor é o sync: `sync_snapshot` compara o read model antes e depois do snapshot e
      grava uma linha por destinatário — o portal continua sem originar status. Sino com
      contagem real, central com histórico e um e-mail de resumo por lote de sync, com
      preferência por conta. `dedupe_key` é o que faz o webhook reenviado não repetir aviso nem
      e-mail. ADR 0012, FDD 005.)*
- [x] Implementar página de reuniões: título, data, link de gravação e indicação de transcrição,
      espelhados do snapshot. *O texto da transcrição não atravessa o snapshot, e
      `transcript_text` nunca teve escritor: medido na ADR 0049, o portal nunca teve o texto.
      As decisões extraídas nascem no Biahflow, onde a transcrição existe (FDD 032 de lá), e
      chegam aqui publicadas.*
- [x] Exibir detalhes e histórico em todas as abas do projeto — Cronograma (com responsável
      vindo do `party`), Documentos (tipo, autor e link), Reuniões e Pendências passam a ler
      `GET /api/v1/me/dashboard` no lugar dos dados de demonstração. *Filtros feitos em
      06/08/2026 (ADR 0029): um componente de chips com contagem nas quatro abas longas, do lado
      do cliente sobre o payload que já veio — filtrar no servidor exigiria parâmetro, esquema
      novo e caso negativo de permissão para responder o que o navegador tem em mãos. Quando a
      lista não couber numa resposta, a decisão muda, e aí é paginação.*

**Aceite:** equipe interna atualiza o projeto **no Biahflow**; o cliente acompanha as alterações
no portal em quase tempo real — e é avisado delas, no sino e por e-mail, sem precisar abrir o
portal para descobrir. *Atendido: `tests/e2e/notifications.spec.ts` sincroniza um marco
concluído, confere o sino no navegador e lê o resumo na caixa do Mailpit.*

## Fase 3 — Resultados e API dos agentes

- [x] Autenticar a API de eventos com chave por projeto, hash, escopo, expiração, rotação e rate
      limiting. *(`X-Agent-Key`, e só ela: um agente não tem sessão de usuário, então o Bearer
      humano deixou de valer nesta rota. O tenant é propriedade da chave, o que permite conferir
      o `projectId` recebido em vez de confiar nele. Só o prefixo fica em claro; o segredo vira
      HMAC sob pepper de servidor. Rate limit em janela na própria linha da chave — sem trazer o
      Redis para o caminho de requisição. ADR 0013, FDD 004.)*
- [x] Persistir eventos idempotentes e configurar investimento/valor-hora com vigência — **e a
      tela para mantê-la**, que veio do item de administração da Fase 1: o número financeiro só
      faz sentido junto do cálculo de ROI que vive aqui. *(`AgentEventRepository.ingest` existia
      desde a Fase 1 e não era chamado; agora é. `project_financial_assumption` tem vigência com
      `EXCLUDE USING gist`, e premissa não se edita no lugar: fecha uma, abre outra. A tela é
      `/admin/resultados`, sob `portal_admin` como a de acesso.)*
- [x] Calcular horas poupadas, custos evitados e ROI líquido por período, com premissas auditáveis.
      *(`results.py`. Nada é derivado na escrita — o evento guarda os inteiros que o agente
      reportou, e o dinheiro nasce na leitura pela premissa vigente **no dia do evento**, para um
      aumento de valor-hora hoje não reprecificar março. Investimento rateado por dia;
      investimento zero declara lacuna em vez de virar ROI infinito.)*
- [x] Criar relatórios e detalhamento que expliquem cada valor exibido no dashboard.
      *(`GET /api/v1/projects/{id}/results` devolve indicador, premissas vigentes e `gaps`; a aba
      Resultados ganhou o bloco "Como calculamos" com período, contagem, valor-hora e fórmula.)*
- [x] Dar fonte real aos três cards ainda de demonstração na aba Resultados — transações
      automatizadas, precisão do fluxo e exceções tratadas (marcados no código em
      `app/DashboardClient.tsx`). São os únicos números sem lastro na tela do cliente.
      *(Saíram, junto do fallback de `roiValue()` que devolvia um percentual fixo. O evento passou
      a carregar `outcome` e `human_intervention` — sem desfecho não haveria como sustentar
      precisão nem exceções. O ROI projetado do Biahflow e o apurado dos eventos convivem
      rotulados. A guarda de `rendered-html.test.mjs` não pegava esses cards, porque eram um array
      local e não um `const` de módulo; agora os literais estão proibidos.)*

**Aceite:** reenvio do mesmo evento não duplica resultado; o cliente vê a origem e a premissa de
todo indicador. *Atendido: `test_agent_events.py` prova a idempotência linha a linha e o par
`accepted`/`duplicate`, e `tests/e2e/results.spec.ts` percorre a corrente inteira — a pessoa
interna abre a vigência e emite a chave no navegador, um agente publica por HTTP (com um reenvio),
e o cliente vê o número ao lado da premissa que o produziu.*

## Fase 4 — Conhecimento e IA contextual

- [x] Implementar conector Google Drive OAuth somente leitura, uma pasta permitida por projeto e
      sincronização idempotente. *Deliberadamente depois do índice: o conector é uma forma de
      **encher** o índice, e fazê-lo primeiro faria a primeira prova de que o chat cita documento
      depender de credencial de um provedor externo que o ambiente local não tem (ADR 0014).*
      *(Feito na ADR 0016. Três decisões carregam o resto: o refresh token é o **primeiro segredo
      reversível** do repositório — HMAC não serve para o que precisa ser reapresentado ao Google
      —, então é AES-256-GCM com o tenant no dado associado e uma chave anterior para a rotação
      não obrigar todo projeto a reconsentir; o callback mora no BFF porque não existe endereço da
      API que o navegador alcance, e **fora de `/api/`** porque o `proxy.ts` responde JSON ali; e
      `document.origin` ganha `drive` para o sync do Biahflow e o do Drive não apagarem o que é do
      outro. A fronteira da pasta é conferida duas vezes, atalho não é seguido, e remoção só
      acontece sobre listagem completa — falha do Google não vira perda de índice. O `beat` é o
      primeiro agendador do projeto, e o `drive-stub` do compose é o que permite provar tudo isso
      no navegador sem credencial do Google. FDD 010.)*
- [x] Armazenar arquivos no MinIO/S3, validar upload, extrair texto e manter metadados de fonte,
      página e data. *(`portal_api/storage.py` fala S3 — MinIO local, S3 em produção — e a chave do
      objeto carrega o tenant inteiro. A porta de entrada é `/admin/conhecimento`, sob
      `portal_admin`, ao lado das chaves e premissas: o cliente pergunta, não envia. `document`
      ganhou `origin`, senão o sync do Biahflow apagaria todo arquivo enviado no snapshot seguinte
      — a mesma coluna que `pending_item` ganhou na Fase 2, pelo mesmo motivo. ADR 0014, FDD 009.)*
- [x] Implementar chunking, embeddings, `pgvector` e recuperação estritamente filtrada por
      organização/projeto. *(O trecho **nunca cruza a virada de página**: é o que faz "página 3" na
      citação ser verdade e não estimativa. Quem escreve o índice é o worker sob `portal_system` —
      `portal_app` fica SELECT-only em `document_chunk`, porque um caminho de requisição que pode
      gravar trecho pode gravar a "evidência" que quer ver citada. Índice HNSW por distância de
      cosseno, com corte que permite à recuperação dizer "não há evidência".)*
- [x] Conectar o provedor de IA por adaptador, prompts versionados e saídas estruturadas validadas.
      *(O respondedor veio na Fase 3, ADR 0007; a Fase 4 acrescentou o adapter de **embeddings** na
      mesma forma — Voyage com chave, projeção determinística por hashing sem ela, na mesma
      dimensão da coluna. O corte de distância pertence ao adapter e não à recuperação: são dois
      espaços vetoriais diferentes, e um número só serviria mal aos dois.)*
- [x] Persistir conversas, citações, feedback e pendências geradas por lacuna de contexto. *(A
      conversa deixou o `useState` do navegador: o turno guarda pergunta, resposta, `confidence`, a
      pendência que a lacuna abriu e as citações **como foram exibidas**. `portal_app` ganha INSERT
      pela primeira vez numa tabela que ele *origina* — e o que impede alguém de plantar uma frase e
      vê-la citada depois não é privilégio de banco, é `conversation_message` não ser fonte de
      recuperação, com um eval que executa o ataque. O feedback é GRANT de coluna, como o `read_at`
      da notificação: avalia-se a resposta, não se reescreve. ~~Falta a tela que lê esse sinal — sem
      dado acumulado ela mostraria zero.~~ ADR 0015, FDD 002.)* **A tela chegou em 06/08/2026
      (ADR 0030), e o adiamento era condicional:** o dado acumulou — 143 respostas, 6 avaliadas,
      **as 6 negativas**, e ninguém conseguia ver. O que a fatia decidiu não foi a tela e sim a
      fronteira: `portal_admin` teve o `SELECT` de tabela **revogado** em `conversation_message`
      e `conversation` e recebeu GRANT de coluna sem `text`, sem `citations` e sem `title` — o
      privilégio já vinha do default privilege do `roles.sql`, e só a **ausência de policy**
      escondia a pergunta do cliente, de modo que qualquer policy nova a teria aberto no mesmo
      commit. O título ficou de fora por ser derivado da primeira pergunta: era a coluna que
      teria vazado depois de barrar a óbvia.
- [x] Criar dataset de avaliação e bloquear regressão em citações, isolamento, lacunas e prompt
      injection. *(`docs/ai/eval-dataset.md` deixou de ser um parágrafo e virou a lista dos casos
      que `test_chat_ai.py` executa — agora incluindo página correta na citação, documento de outro
      projeto e prompt injection dentro do trecho. Roda determinístico em CI, sem chave nenhuma.)*

**Aceite:** perguntas sobre produção, decisões financeiras e pendências retornam fontes corretas;
falta de evidência cria uma pendência, sem resposta inventada. *Atendido, e a fase está fechada:
`tests/e2e/documents.spec.ts` sobe um arquivo com um termo inédito pela tela de administração,
espera a indexação e vê o cliente receber a citação daquele documento; `tests/e2e/chat.spec.ts`
recarrega a página e encontra a mesma resposta com a mesma citação, que é como se prova que ela
existe fora do navegador; e `tests/e2e/drive.spec.ts` conecta uma pasta pelo consentimento OAuth,
sincroniza e vê a citação chegar ao cliente — provando junto que o arquivo de fora da pasta e o
atalho **não** entraram no índice.*

## Fase 5 — Segurança e produção

- [x] Implementar antivírus/validação assíncrona de documentos, URLs temporárias e política de
      retenção/exclusão por organização. *(ADR 0017, FDD 011. Três decisões carregam o resto: um
      **scanner ausente devolve `skipped`, nunca `clean`** — o embedder offline é uma resposta
      pior à mesma pergunta, um antivírus offline seria uma resposta inventada, e não há por que
      o portal se permitir em segurança o que a regra 3 do `AGENTS.md` proíbe da IA; a varredura
      é **eixo próprio** e não mais um valor de `ingest_state`, porque "é seguro" e "virou texto
      citável" podem ter respostas opostas no mesmo documento; e o **expurgo é um pedido
      gravado** que o worker cumpre, como a ADR 0015 já tinha determinado. `queue_document_scan`
      virou a porta única, então o arquivo do Drive passa pela mesma fronteira do que foi enviado
      na tela; a indexação recusa por conta própria o que não passou. A citação virou link — o
      cliente abre a página 3 em vez de confiar nela — por URL assinada de vida curta, que não
      existe para documento não varrido. E a poda nunca toca em documento: ele é a evidência que
      sustenta uma citação já dada. O EICAR é o que permite provar tudo isso sem antivírus, como
      o `drive-stub` provou o conector sem o Google.)*
- [x] Adicionar alertas e telemetria com `trace_id`. *(ADR 0018, FDD 012. Esta fatia não
      implementou uma promessa adiada: implementou três que os documentos já davam como
      cumpridas — o `incident-response.md` mandava "preservar `trace_id`" e não havia
      `trace_id`; o `agent-events-failure.md` mandava ler `reason` e `key_prefix` de um log
      que, sem formatter configurado, **descartava todo `extra`**; e o `app/error.tsx` dizia
      ao cliente "A falha foi registrada" sem que houvesse um `console.error` sequer em
      `app/`. O id nasce no BFF e **não** no `proxy.ts` — o portão de sessão não é lugar para
      injetar header por dentro do wrapper do Auth.js —, entra na API por um ponto de costura
      que já existia (`authorizationHeader()`, e nenhum dos treze call sites foi tocado),
      atravessa a fila como **header da mensagem** para nenhuma assinatura de task mudar, e é
      carimbado em `audit_log.data` sem migração. Alerta virou evento nomeado com limiar
      escrito (`runbooks/alerts.md`) em vez de stack de métrica, que pertence ao ambiente de
      homologação; `/health/ready` e healthchecks no compose são o que pode ficar vermelho, e
      o `beat` fica **sem** healthcheck de propósito, porque um check que sempre passa é pior
      que nenhum. De quebra, dois defeitos que silenciavam a aplicação inteira: o `fileConfig`
      do Alembic e o `setup_logging` do Celery, os dois desabilitando todo logger
      `portal_api.*` já criado.)*
- [x] Adicionar backup/restore testado para PostgreSQL e MinIO. *(ADR 0019, FDD 013.
      Pela terceira vez na Fase 5 a fatia não implementou uma promessa adiada e sim
      uma que os documentos davam como cumprida: o `backup-restore.md` mandava
      "testar backup criptografado em ambiente isolado" e as ADRs 0010 e 0011
      **delegavam a ele** rodar o `roles.sql` antes do restore — sem que existisse
      `scripts/`. O que carrega o resto foi medido, não deduzido: `pg_dump` com a
      credencial de requisição **recusa** ("query would be affected by row-level
      security policy"), e a correção óbvia — `--enable-row-security` para calar a
      recusa — devolve um backup limpo, bem-sucedido, cifrável e **vazio**. Daí as
      duas decisões: o dump sai sob o papel dono, e o **censo de linhas sai sob
      credencial diferente da do dump**, senão os dois erram na mesma direção e o
      manifesto confirma que zero virou zero. Restaurar de verdade revelou ainda
      dois defeitos que só apareceriam no dia do desastre: o `btree_gist` veio da
      migração 0010 e nunca entrou no bootstrap (e um restore não roda migrações),
      e as duas extensões nasciam sem `WITH SCHEMA public` — o que punha o
      `btree_gist` dentro de `portal` e fazia o `DROP SCHEMA` do restore falhar por
      dependência. O restore afirma, com código de saída, que `portal_app` continua
      sem `BYPASSRLS` e que as policies voltaram: um restore que traz as linhas e
      perde a RLS devolve um portal onde todo cliente vê todo projeto, e nada na
      tela denuncia. E, porque a linha do pedido de expurgo sobrevive ao próprio
      expurgo (ADR 0017), o restore consegue listar o que ele mesmo desfez.)*
- [x] Cobrir contratos OpenAPI, testes de integração com serviços reais e Playwright E2E. *(ADR
      0020, FDD 014. Pela quarta vez na Fase 5 a fatia implementou uma promessa que os documentos
      davam como cumprida — e desta vez o documento não estava vazio, estava **errado**: o
      `api-contracts.md` encerrava dizendo que "contratos completos serão publicados
      automaticamente pelo OpenAPI do FastAPI" enquanto as dezesseis rotas de cliente devolviam
      `dict` cru e publicavam esquema vazio, e a mesma página documentava camelCase para uma API
      que responde snake_case. `responses=` não aparecia uma vez no repositório, então o "404,
      nunca 403" — a regra mais repetida do projeto — não existia em lugar que uma ferramenta
      pudesse ler. A decisão que carrega o resto é `extra="forbid"`: o padrão do `response_model`
      **filtra em silêncio** o campo que o modelo não declara, e tipar as respostas *acrescentaria*
      esse defeito ao repositório — um dado sumindo da tela com a rota respondendo 200. O esquema
      virou artefato versionado com gate de deriva, como o `alembic check`, e o teste afirma as
      regras sobre toda rota, inclusive a que ainda não existe. A outra metade foi o verde do CI:
      as três asserções que dão sentido ao backup (ADR 0019) **pulavam em silêncio a cada push**
      por falta de duas variáveis, e o `e2e` era `continue-on-error` com quatro specs que se
      auto-pulavam. Hoje um pulo que o CI deveria cobrir **falha**, o par backup/restore tem job
      próprio — que foi o que revelou as outras quatro senhas e o MinIO que ninguém sabia que
      faltavam — e o e2e pode reprovar. De quebra, a fixture do teste de SSR do web deixou de ser
      livre para mentir.)*
- [x] Cobrir cenários adversariais de IA. *(ADR 0021, FDD 015. Pela quinta vez na Fase 5 a fatia
      implementou promessas que os documentos davam como cumpridas — quatro delas, e as duas
      últimas só apareceram ao escrever os testes. O `prompt-policy.md` dizia "prompts são
      versionados" e o que existia era um `chat_prompt_version` nas settings que **ninguém lia**;
      agora a versão mora ao lado do texto, com registro append-only de digests como portão de
      deriva — não uma constante, porque quem atualiza texto e constante juntos sem trocar a
      versão continuaria verde, que é justamente o caso que a política quer pegar. As catorze
      evals rodavam no respondedor offline, um casador que **não tem como** obedecer a uma
      instrução: a eval de injeção provava que uma pedra não atende ao telefone. Abriu-se a costura
      (`anthropic_client`, na forma do `session_client` do Drive) e entraram catorze casos com um
      Claude hostil que cita fonte inventada, cita fonte de outro tenant, afirma sem citar e
      obedece à injeção — metade das asserções olhando o **pedido enviado**, que é a única forma
      de afirmar que segredo e texto de outro projeto não saem do processo. O chat ganhou limite
      de taxa por pessoa, em tabela própria sob `portal_system` e em transação anterior à do chat:
      colunas em `user` travariam o primeiro login, porque `resolve_user` escreve naquela linha
      dentro de uma transação que abrange a chamada ao modelo. **E os dois defeitos que os testes
      revelaram:** `max_tokens=1024` com `thinking` adaptativo truncava a resposta e virava
      fallback offline silencioso; e o `answerFor()` da tela devolvia data, decisão e **rótulos de
      citação inventados** ao cliente autenticado cuja chamada falhou — com um teste que exigia
      sua existência, segurando o defeito no lugar como a ADR 0020 achou nas asserções de backup.
      A afirmação do `CLAUDE.md` de que "não há mais fallback para dado inventado" só passou a ser
      verdade agora. O limite estrutural ficou declarado, não escondido: o portal não impede um
      modelo remoto de parafrasear a injeção dentro da resposta, e um filtro de saída foi recusado
      com argumento — falharia na primeira paráfrase enquanto criava a impressão contrária.)*
      **E em 11/08/2026 a ADR 0047 achou, entre cinco e2e vermelhos parados desde 07/08, um
      defeito que não era de teste:** o título da pendência que o assistente abre por lacuna
      carrega a pergunta do cliente, e `collect_evidence` recolhia **toda** pendência aberta como
      evidência — de modo que a pergunta de ontem casava a de hoje, o respondedor offline dava
      `sufficient=True`, e a resposta citava a *própria lacuna anterior* como fonte. É o inverso
      exato da regra 3 do `AGENTS.md`: em vez de declarar a lacuna, ela virava a evidência da
      resposta seguinte — e vale em produção sempre que a Anthropic cair e o `offline_fallback`
      assumir. A correção olha a **coluna** (`origin=biahflow`) e não o texto do título, porque só
      dois sítios criam pendência e eles já se distinguem por ela. As outras duas causas eram de
      teste, e a segunda tinha nascido assim: um ator `internal_member` abrindo uma tela que exige
      `internal_admin` desde o commit que a criou — **nunca** tinha passado.
- [x] Definir ambiente de homologação, variáveis/segredos de produção, domínio, TLS,
      observabilidade e plano de incidentes. *(ADR 0022, FDD 016. Entregue como **código e portão
      de CI**, não como infraestrutura provisionada: `docker-compose.homolog.yml`,
      `infra/caddy/Caddyfile`, `.env.homolog.example` e `docs/runbooks/deploy.md`. A decisão que
      carrega o resto é `${VAR:?}` no lugar de `${VAR:-default}` — todo `${VAR}` do compose base
      tem default local, então um `.env` de homologação a que falte uma chave **subia verde com a
      senha do exemplo**, que é a forma mais cara de um controle falhar. E são dois mecanismos, não
      um: `preflight.py` recusa a subida do processo ao encontrar sentinela de exemplo, segredo
      vazio, `DEMO_MODE` ligado ou endereço em texto claro, porque `${VAR:?}` só sabe perguntar se
      a variável **tem** valor, nunca se o valor é seu. O template é ele próprio um arquivo que o
      `preflight` recusa. TLS termina no Caddy, o único serviço que publica porta — a API não é
      publicada porque o navegador nunca fala com ela (ADR 0010) —, fechando a seção que o
      `docs/security.md` prometia com "ver a seção própria abaixo" e que não existia. De quebra, as
      duas imagens deixaram de ser de desenvolvimento: a da API instalava `requirements-dev` e
      copiava `tests/` para dentro, e as duas rodavam como root.)*
- [x] Cobrir carga de IA. *(ADR 0022, FDD 016. Pela sexta vez na Fase 5 a fatia implementou uma
      promessa que os documentos davam como cumprida — e desta vez ela era a **causa técnica** de a
      carga não ser mensurável: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` e `CHAT_RATE_LIMIT` existiam
      no `.env.example` desde a Fase 3, eram lidas pelo `config.py`, e **nenhum compose e nenhum
      workflow as passava** ao contêiner. O `AnthropicResponder` que a ADR 0021 acabou de construir
      e testar com um Claude hostil nunca rodou na pilha de pé, e a própria ADR 0021 chegou a
      avisar para "não baixar `CHAT_RATE_LIMIT` no compose" — uma variável que o compose não lia.
      Generalizado, o defeito pegou mais doze, inclusive o `DRIVE_TOKEN_ENCRYPTION_KEY_PREVIOUS` de
      que a rotação da ADR 0016 depende, e uma que não existe em canto nenhum: `MINIO_ENDPOINT`.
      Junto vieram as **quotas** que o `threat-model.md` prometia desde a Fase 1: razão de tokens
      por organização, teto mensal e custo que **nasce na leitura** pelo preço vigente no dia da
      chamada — literalmente `results.py`, e pelo motivo dele. Não é um contador incrementado, e
      quem disse isso foi o docstring do `chat_limit.py`: aquele contador "subconta sob
      concorrência alta, o que seria inaceitável para um contador de faturamento". Sem preço
      vigente o turno **passa** e a lacuna é declarada — a única falha aberta do repositório, por
      assimetria de recuperação: os tokens gravados tornam o custo recalculável, uma pergunta
      recusada não volta. O `docs/observability.md` listava "custo/latência de IA" entre os
      indicadores enquanto o `response.usage` de toda resposta era descartado; agora não. E o
      harness (`scripts/loadtest.py`) recusa rodar com chave e sem `--budget-usd`, tira o custo do
      mesmo razão que a quota usa para cobrar, e **declara no próprio relatório o que mediu** — que
      não é homologação, que o respondedor foi o offline, ou que o provedor degradou no meio. O
      passo por conta não foi deduzido e sim medido: a primeira execução devolveu 12.839 recusas
      para 62 respostas, medindo o limitador com precisão e o sistema com nenhuma.)*
- [x] Revisar dependências vulneráveis apontadas pelo `npm audit` antes de produção. *(ADR 0023,
      FDD 017. Pela sétima vez na Fase 5 a fatia implementou promessas que os documentos davam
      como cumpridas — cinco, e as três últimas só apareceram porque alguém finalmente executou a
      ferramenta. **A instrução escrita levava ao lugar errado:** "corrigido em 16.2.11" valia
      para os nove avisos do próprio `next`, e a linha 16.2.x repinava `postcss` (path traversal
      lendo `.map` arbitrário) e `sharp` (CVEs de libvips) nas versões vulneráveis — parar ali
      fecharia o item deixando três pacotes de severidade alta em pé, com um `[x]` afirmando o
      contrário. Só a **16.3.0** zera. **A frase que tranquilizava estava invertida:** Turbopack
      **é** o bundler deste repositório — padrão do Next 16, e o build imprime `(Turbopack)` —;
      o que não se aplica é a outra pré-condição, e não existe `config.i18n` em canto nenhum. A
      conclusão seguia certa pelo motivo errado, que é o tipo de frase que sobrevive à revisão
      seguinte por soar resolvida, e sobreviveu a duas. **E o `dependency-review` parecia
      varredura e não era:** ele olha o *diff* de um PR, então o que já estava no lockfile
      passava verde a cada push — somado ao `codeql` desligado, `npm audit` não rodava em lugar
      nenhum. **O lado Python era o ponto cego maior e nenhum documento o mencionava:** primeira
      execução do `pip-audit`, dezesseis avisos em três pacotes — seis no `python-multipart`, que
      sustenta a única rota multipart do produto, e sete no `starlette`, que é a camada HTTP da
      API inteira. O roadmap dizia "falta só o `npm audit`". **De quebra, dois defeitos que só
      apareceram por executar aquilo:** subir o FastAPI não conserta o Starlette em toda parte —
      a faixa nova é `>=` sem teto, então uma instalação limpa resolve para o 1.4.1 e um ambiente
      que já tinha o 0.46.2 continua nele, o mesmo commit produzindo versões diferentes em
      lugares que se dizem iguais (daí o pin direto, com o precedente e o argumento que o
      `cryptography` já tinha no arquivo); e o FastAPI 0.141 passou a **ecoar o corpo da
      requisição** em todo 422, sendo que `DriveCallbackIn` carrega o authorization code do
      Google — a fatia teria *introduzido* o vazamento do segredo que a ADR 0016 sela com
      AES-256-GCM. Agora o portão é `scripts/audit.mjs`, sem limiar de severidade porque um corte
      seria um segundo mecanismo de exceção e silencioso; aceitar um risco é escrever linha com
      motivo e prazo em `docs/security/advisories.json`, que **vence** e cuja entrada obsoleta
      também reprova — quarto gate de deriva do repositório, e o único que deliberadamente **não**
      é append-only, ao contrário do `prompt-registry.json`.)*

**Aceite:** pipeline bloqueia regressões de qualidade e segurança; backups são restauráveis e incidentes seguem runbook testado.
*Atendido, e **a Fase 5 fecha**: o ciclo de vida do documento fechou (`test_document_scan.py`, `test_retention.py` e o
EICAR barrado no navegador em `tests/e2e/documents.spec.ts`), a telemetria também
(`test_telemetry.py`, e o `X-Request-ID` exigido pelo stub em `tests/rendered-html.test.mjs`),
o backup passou a ser restaurável com prova (`test_backup_restore.py` roda os dois scripts de
verdade contra um banco descartável e confere policies, GRANTs de coluna e isolamento) — e agora
ele roda **a cada push**, no job `backup-restore`, com as três asserções que vinham pulando em
silêncio. O contrato passou a existir como artefato (`docs/api/openapi.json`,
`test_openapi_contract.py`, `tests/api-contract.test.mjs`) e o `e2e` passou a poder reprovar. E os
adversariais de IA fecharam (`test_chat_ai.py` com o respondedor real e um modelo hostil,
`test_prompt_version.py`, `test_chat_rate_limit.py`) — com eles saiu o último caminho do portal
que devolvia dado fabricado ao cliente. E carga, quotas e o ambiente de que as duas dependiam
fecharam por último (`test_homolog_config.py`, `test_ai_quota.py`, `test_loadtest_harness.py`, com
o CI afirmando que o override de homologação recusa sem segredos e que o harness ainda roda ponta
a ponta) — junto com a descoberta que explicava por que a carga não era mensurável: as três
variáveis do chat nunca chegavam ao contêiner, e o respondedor real nunca havia rodado na pilha.
E as dependências fecharam por último (`tests/audit-harness.test.mjs`,
`test_main.py::test_a_422_says_what_is_wrong_without_echoing_what_was_sent`, com o job
`dependency-audit` reprovando em `push` e em `pull_request`) — trazendo a mesma descoberta uma
última vez: o lado que nenhum documento mandava olhar, o Python, tinha dezesseis avisos contra
os catorze do lado que o roadmap nomeava. **Nada bloqueia o lançamento externo.***

## Fase 6 — Jornada da transformação e experiência (metodologia)

Adicionada em 04/08/2026 ao alinhar o portal com a arquitetura de produto do documento
(duas jornadas, "cérebro" compartilhado, dois portais com perspectivas diferentes). Hoje o
dashboard é uma casca de demo (`app/DashboardClient.tsx`, dados hardcoded); esta fase o torna
**real**, projetando o lado do cliente a partir do estado do projeto que vive no Biahflow.

- [x] **Estender o read-model com a jornada.** Modelos `ProjectPhase` e `PhaseDeliverable`
      (sob `TenantMixin`, padrão não-qualificado do `search_path`) + colunas de ROI/próxima
      reunião no `Project`, na migração `0003_journey_and_roi`. Ver `models/project.py`.
- [x] **Ampliar `sync_snapshot()` e `build_dashboard()`** (`integrations/biahflow.py`): upsert
      "replace" das fases/entregáveis e projeção de jornada + entregáveis + ROI + próxima
      reunião em `GET /api/v1/me/dashboard`. Testes em `tests/test_biahflow_integration.py`.
- [x] **Barra "Você está aqui"** com as fases (Welcome → Optimize); ao clicar numa fase, ver
      objetivo, status, previsão e entregáveis — **perspectiva de negócio, sem task técnica**.
      Componente `JourneyPanel` em `app/DashboardClient.tsx`; estilos em `app/globals.css`.
- [x] **Entregáveis que "desbloqueiam" por fase** (entregue vs. bloqueado, com link quando há).
- [x] **ROI/próxima reunião reais** vindos do snapshot nos cards da Visão geral (no lugar dos
      valores fixos). `page.tsx` mapeia `journey`/`roi`/`next_meeting`.
- [x] **Roster de Funcionários Digitais** — card por agente (o que faz, KPIs, horas e ROI/mês),
      alimentado pelo snapshot. Modelo `DigitalEmployee` (migração `0005`), `sync_snapshot`/
      `build_dashboard` e o painel `DigitalEmployees` na Visão geral e em Resultados.
- [x] **Indicador de saúde amigável** ("No prazo"/"Requer atenção"/"Atrasado" + cor) derivado
      do Health Score do Biahflow, sem expor score/sinais internos. Snapshot leva `health`
      {label, level}; colunas `health_label`/`health_level` no `Project` (migração `0004`);
      selo no `status-card` do `DashboardClient.tsx`.

- [x] **A busca do projeto.** *(ADR 0024, FDD 018. A lupa do topbar abria um popover com um
      `<input>` sem `onChange`, sem handler e sem resultado, embaixo da frase "Comece a digitar
      para buscar no contexto do projeto" — o último controle de demonstração na tela do
      cliente, e o único cuja promessa não estava num documento e sim onde quem paga pelo
      produto a encontra sozinho. *Corrigido em 06/08/2026 (ADR 0026): "o último" estava errado,
      havia mais onze — dois deles apontando para abas que já existiam. A segunda metade da
      frase é que era o achado, e vale para os doze.* Fecha junto o critério de aceite da Fase 1 acima. Duas fontes:
      as linhas do read model por título e os **trechos** de documento por full-text, porque sem
      as segundas "buscar no contexto do projeto" entregaria uma lista de títulos — a versão do
      controle que parece funcionar e não responde à pergunta que alguém faz. Sem extensão nova
      de Postgres: `unaccent` é objeto de **banco** e teria de nascer no bootstrap, no init e na
      migração, que é o defeito que a ADR 0019 encontrou no `btree_gist` no dia do restore, e
      ainda é `STABLE`, o que exigiria uma função `IMMUTABLE` própria para o índice; a dobra sai
      de `translate()`, e que o índice GIN é usado foi verificado no `EXPLAIN`, não deduzido. O
      termo digitado **não** vai para o log nem para a auditoria. De quebra, um defeito de
      empilhamento anterior a esta fatia: `.topbar` tem `backdrop-filter`, que cria contexto de
      empilhamento sozinho, então o `z-60` de qualquer popover do topo valia só dentro da barra
      e o `.menu-backdrop` ficava por cima — enquanto aqueles popovers eram só leitura ninguém
      notou, e o primeiro conteúdo clicável dentro de um deles esbarrou nisso na hora. O "Ver
      todas" da caixa de avisos e o menu de perfil do topo estavam igualmente mortos.)*

- [x] **Os controles que não faziam nada.** *(ADR 0026, FDD 001. Segunda repetição do padrão da
      ADR 0024, e desta vez a promessa quebrada era **a própria ADR 0024**: ela encerrou dizendo
      que a lupa era "o último controle de demonstração na tela do cliente", este roadmap
      repetiu e o `CLAUDE.md` repetiu de novo — e havia mais **onze** botões inertes em
      `app/DashboardClient.tsx`. Dois deles, "Ver cronograma" e "Ver todas as pendências",
      apontavam para abas que existiam desde a Fase 2, com um `goTo()` que existia: eram uma
      linha cada. Os outros nove saíram, com o argumento: "Editar" no perfil promete o que o
      GRANT de coluna de `portal_app` em `user` recusa **por desenho** (ADR 0010/0011/0012) —
      feature errada, não feature faltando —, os seis `⋯` só poderiam oferecer ações que
      originam status, que o portal não faz (ADR 0006/0008), e "Salvar alterações" ficava sob
      três constantes do produto. O motivo de terem sobrevivido é o que dá a fatia: **toda
      guarda deste repositório é sobre dado, e nenhuma era sobre affordance** — um `<button>`
      sem `onClick` renderiza HTML byte a byte idêntico a um que funciona, então nem as
      asserções sobre o SSR nem o Playwright os alcançavam, e o array de Idioma/Fuso/Tema
      escapou até da guarda de literais por ser array local e não `const` de módulo, que é a
      fuga que o comentário daquele teste já documentava. Agora `inertButtons()` exige `onClick`
      ou `type="submit"` de todo botão sob `app/` e `components/`, e nasceu vermelha listando os
      onze — o regex ingênuo não serviu, e isso foi medido: o `>` dentro do
      `aria-label={unreadCount > 0 ? …}` do sino fecha a tag cedo e produz falso positivo. De
      quebra, o "Atualizado há 2 dias" que o status-card mostrava fora do caminho `live`: um
      carimbo de frescor inventado no único lugar onde o demo é permitido.)*

- [x] **A tela da organização, e o id que nenhuma resposta devolvia.** *(ADR 0027, FDD 011/016.
      Terceira repetição do padrão, e a mais funda: seis rotas de administração por
      **organização** — retenção, teto de IA e apagamento — existiam completas, testadas e sob
      `portal_admin` desde as ADRs 0017 e 0022, e não estavam apenas sem tela: `grep
      organization_id` no `schemas.py` não devolvia nada. As seis são chaveadas por um UUID que
      **nenhuma resposta da API entregava** (`MeOut.organization` é o *nome*), de modo que eram
      inalcançáveis por qualquer coisa que não consultasse o Postgres à mão — a forma da ADR
      0022, onde faltava uma linha de YAML, só que aqui faltava uma rota. **E o desenho sabia da
      tela que não veio:** `RetentionPolicyOut` devolve prazo escolhido *e* efetivo porque "a
      tela precisa distinguir escolhido de herdado", e o `confirm_slug` existe para "obrigar quem
      **clica** a olhar qual tenant está **na tela**". Duas instruções de runbook mandavam usar o
      que ninguém conseguia usar — o `load-test.md` mandava subir o teto pela rota, e o
      `alerts.md` falava em "sem abrir a tela" apontando para um `deploy.md` que não menciona
      nada disso. O caso mais caro era o expurgo: obrigação contratual que só se cumpria por
      `curl` com um token que o portal nunca emite. Agora há `GET /api/v1/admin/organizations` —
      lista vazia com **200**, a única rota de `admin.py` que não é 404 na ausência, porque ali
      não há recurso nomeado a vazar — e `/admin/organizacao`. Documento **não** entra na tela,
      de propósito: é a evidência de uma citação já dada e não sai por idade (ADR 0017). O
      argumento que adiava a quota estava trocado: valia para o painel de gasto, não para o
      controle de teto, que mostra número no primeiro dia. **De quebra, o defeito que só apareceu
      ao subir a pilha:** `seed._upsert_membership` casava a linha por `user_id` + `project_id IS
      NULL` **sem filtrar organização** — correto com uma organização só, e desde o bootstrap da
      ADR 0025 quem administra duas acumula um vínculo org-wide por organização, então o
      `scalar_one_or_none` estourava `MultipleResultsFound` e o `api-seed` saía com 1 a cada
      `docker compose up`.)*

- [x] **O expurgo que falha, e o alerta que o denunciaria.** *(ADR 0028, FDD 011. O
      `alerts.md` promete `erasure.failed` para "qualquer ocorrência", com o argumento na
      própria linha: apagamento não cumprido é obrigação contratual, e o pedido fica no banco
      "mas ninguém olha uma tabela sem motivo". **O código nunca emitiu esse evento**, porque o
      caminho de falha não existia — em `_run_erasure` só a metade do *storage* tinha `except`.
      Uma exceção na metade do banco revertia a transação, deixava a linha em `running` **para
      sempre** (o claim e o filtro do tick só olhavam `pending`), não registrava nada, e — desde
      a ADR 0027 — fazia a tela responder "já existe um pedido em execução" indefinidamente,
      deixando o tenant inapagável pela interface. Dar tela à rota não criou o defeito; tornou-o
      alcançável. **Duas assimetrias mostram que foi lapso:** `purge_expired_data`, dez linhas
      acima, envolve cada organização em `try/except` e emite `retention.purge_failed`; e o
      docstring de `_claim_erasure` diz que ele reivindica "como o sync do Drive" — copiou o
      `UPDATE` condicional e não a janela de `stale`, que existe lá para um processo morto não
      prender a linha. Agora a metade do banco carimba `failed` com o motivo em sessão nova (a
      que falhou reverteu, e é isso que garante que `failed` nunca descreva meia remoção), emite
      o evento, e **não** retenta sozinho: quem decide é uma pessoa pela tela, e um `failed` já
      libera pedido novo. `erasure_stale_after_seconds` cobre o worker que morreu no meio, com um
      predicado único usado no filtro e no claim — separá-los daria um laço que escolhe o que não
      consegue pegar. De quebra, o mesmo runbook nomeava `drive.rejected` para atalho e arquivo
      fora da pasta: o segundo sempre teve evento com outro nome, e o **atalho não tinha
      nenhum**, então metade da fronteira que a ADR 0016 confere duas vezes passava por "nada
      aconteceu".)*

- [x] **A guarda que parecia cobrir o contrato.** *(ADR 0033, FDD 014. Quarta repetição do
      padrão, e desta vez a promessa quebrada era **uma guarda de CI** — o mecanismo que existe
      para as promessas não serem quebradas. A ADR 0029 criou a asserção de que "o contrato tem
      de ser consumido, não só casado" e encerrou dizendo que a allowlist "está **vazia**, e a
      meta é que continue"; ela era um `for` sobre **oito nomes escritos à mão** lendo **um
      arquivo**, num contrato com **56 esquemas de resposta**. A allowlist seguia vazia porque
      nada a consultava — a forma exata da ADR 0023, em que o `dependency-review` parecia
      varredura e olhava só o diff de um PR. Generalizada, nasceu vermelha com catorze campos e
      uma rota. **Os três que importam não eram campo faltando, eram a tela afirmando o que não
      é:** a linha "Fórmula do ROI" imprimia um **literal** que nem casava com a fórmula que a
      API devolve — no bloco "Como calculamos", aberto na Fase 3 justamente para o cliente
      conferir a conta, de modo que a frase do `CLAUDE.md` sobre não haver dado fabricado valia
      para a resposta e a citação, mas não para a **explicação** do número; `feedback_comment`
      **não tinha escritor**, e `/admin/assistente` renderizava um painel intitulado "O que os
      clientes disseram" sobre um campo sempre nulo, três dias depois de a ADR 0030 chamá-lo de
      "o campo mais informativo do conjunto"; e `last_sync_stats`, cujo produtor nomeia a tela
      para a qual foi feito, deixava uma sincronização truncada indistinguível de uma completa.
      Mais `confidence` descartado no chat, `currency` ignorado com `BRL` fixo — uma premissa em
      outra moeda saía **errada**, não incompleta —, `scanned_at`, `rotated_from_id` e os quatro
      campos da apuração. **A decisão que carrega o resto foi medida e não deduzida:** a primeira
      versão usava um corpus único sobre todo `app/`, ficou verde, e ao neutralizar o mapeamento
      de `.priority` **não reprovou** — porque aquele nome também é o campo da *view*. A guarda
      generalizada nasceria verde em cima do defeito exato que a ADR 0029 existe para pegar. O
      corpus passou a ser por esquema, com dois elos explícitos (`import` relativo e
      `fetch("/api/…")`), porque as rotas de `app/api/**` são **passagem** e o consumidor de
      verdade é quem as chama. De quebra, uma segunda asserção um nível acima — toda rota do
      contrato tem chamador — que achou o `GET /api/v1/projects/{id}/results` sem consumidor e o
      `GET /api/v1/dashboard/demo`, que **saiu**.)*

- [x] **O evento nomeado, e o runbook que o conhece.** *(ADR 0034, FDD 012. Quinta repetição do
      padrão, e desta vez o argumento não é que a promessa foi quebrada — é que **ela já tinha
      sido consertada à mão e voltou a quebrar**. A ADR 0028 achou o `alerts.md` citando
      `drive.rejected`, evento que o código nunca emitiu, e escreveu a linha certa; o conserto não
      deixou guarda, e em dois dias o arquivo divergiu de novo pelo outro lado, com **doze**
      eventos emitidos que nenhum runbook conhecia. **Quatro defeitos, todos medidos.** O
      `alerts.md` mandava vigiar `scan_state=skipped` em produção para saber que o antivírus caiu —
      e isso é impossível: `get_scanner` só devolve o scanner offline quando `CLAMAV_HOST` está
      **vazio**, e o `ClamavScanner` responde `clean`, `infected` ou `error`, nunca `skipped`. Quem
      seguisse a instrução vigiava um contador pinado em zero exatamente enquanto o antivírus caía,
      e `error` não tinha linha em runbook nenhum. Pior, o único sinal de clamd fora era prosa
      interpolada — que é o segundo defeito: **dez sítios punham a mensagem já interpolada no campo
      `event`**, de modo que `"Objeto %s não removido do storage"` gerava um valor novo por
      ocorrência, e o `document-ingestion-failure.md` mandava procurá-lo por substring, única
      instrução do repositório que não se cumpria com `grep '"event":"…"'`. O docstring do
      `JsonFormatter` **abençoava** a prosa, e era a frase que permitia os dez. Terceiro:
      "anomalias de autorização" era indicador do `observability.md` **sem emissor** — `access.py`
      tinha quatro caminhos de negação e zero logs, as 23 negações de rota só viravam 404, e um
      cliente autenticado percorrendo ids alheios não deixava rastro com ator, de modo que as duas
      primeiras linhas do `threat-model.md` não tinham como ser contadas por pessoa. E quarto, os
      órfãos — entre eles `document.infected_object_kept`, que é malware confirmado **ainda no
      bucket** e era anônimo enquanto o caso mais brando já acordava alguém. **A guarda achou mais
      do que a investigação que a motivou:** `http.failed` (todo 500 da API) e
      `health.broker_unavailable` (irmão exato do `health.database_unavailable`, mesmo endpoint,
      mesmo 503, e só metade alertava) não estavam no levantamento manual — apareceram porque a
      máquina perguntou por todos. A guarda é bidirecional porque as duas direções já falharam, e
      **ignora as notas históricas** (`*Corrigido em …*`): sem isso ela cobraria que o repositório
      apagasse o registro do próprio erro, que é a memória que impede a terceira repetição.)*

- [x] **A guarda escrita à mão, e a regra que ninguém verifica.** *(ADR 0035, FDD 012/014/015.
      Sexta repetição do padrão, e desta vez o alvo é o mecanismo inteiro: **as guardas que
      carregam as regras inegociáveis eram, elas próprias, listas digitadas** — o defeito que a
      ADR 0033 nomeou, sobrevivendo em quatro lugares, três deles a única prova executável de uma
      regra do `AGENTS.md`. **A regra 2** ("nunca envie segredos ao modelo") era provada por
      **seis sentinelas fixas contra dezesseis campos de segredo**, e o segundo casador mostra por
      que uma lista não bastava: doze batem o nome, e quatro escondem a credencial **dentro do
      valor** — as `database_*_url` são DSN completo e não casam `_SECRET_HINTS`, porque o casador
      do log pergunta pelo nome, que no log é a chave do `extra` e ali está certo. Ficavam de fora
      a chave **anterior** da rotação do Drive, que abre todo ciphertext ainda não resselado, e a
      senha do `portal_admin`, que escreve `membership`; medido injetando o vazamento, a guarda
      nova reprova e a antiga **passa verde**. **A regra 6** — caso negativo de permissão, a
      disciplina mais invocada do repositório — não tinha portão nenhum: 30 funções à mão contra
      46 pares rota+método publicados. `GET` e `PUT .../ai-quota`, que definem o teto de gasto de
      IA de uma organização e têm tela desde a ADR 0027, **não tinham teste de espécie alguma** —
      as catorze asserções de `test_ai_quota.py` fixam o teto escrevendo no banco pela fixture,
      nunca pela rota. A guarda nasceu vermelha com cinco pares, e o mais caro não era o teto:
      `GET /projects/{id}/results` é a **única** rota de cliente que recebe id de projeto no
      caminho — o caso literal da regra 1 — e ninguém a exercitava. O predicado sai do artefato
      publicado (**quem promete 404 prova o 404**), e é isso que dispensa allowlist: sondas,
      webhook e as duas rotas `/me` sem identificador não declaram 404 e se isentam sozinhas. **E
      o elo foi medido, como na ADR 0033:** com a ligação frouxa, `POST /chat` aparecia coberto
      por um teste em que o chat só monta a conversa e o 404 é da rota de feedback — a guarda
      nasceria verde sobre rota sem negativo. Mais **o pulo que escapou** do `skip_unless_ci`
      (`test_backup_restore.py:432`, o único `pytest.skip` cru do arquivo, e justo sobre a decisão
      6 da ADR 0019 — restaurar bytes corrompidos é pior que falhar) e **a guarda de eventos que
      só via metade do repositório**: o BFF emite quatro eventos com logger próprio e nenhum tinha
      linha em runbook, com a evidência dentro da própria guarda, um `elsewhere` que descrevia o
      ponto cego em vez de fechá-lo. De quebra, o que fecha o círculo: **a numeração que todo
      mundo cita não existia.** O `AGENTS.md` tinha cinco princípios e o `CLAUDE.md` publicava
      seis "from `AGENTS.md`", promovendo uma convenção e um item de checklist a princípio e
      **descartando** o princípio 5, o dos segredos; a numeração da cópia é que circulava, com
      seis lugares citando uma "regra 6" inexistente e "regra 5" querendo dizer coisas diferentes
      em duas ADRs. Agora a regra 6 existe, as listas são a mesma e uma guarda cobra as duas
      coisas — e ela também achou mais do que o levantamento manual, uma sexta citação em
      `test_main.py`. **A regra 4 fica declaradamente sem guarda**, e é a única: "migração aditiva"
      não é verificável por `alembic check` e "exige ADR/RFC" é julgamento.)*

- [x] **O projeto encerrado, e o 404 que não distingue.** *(ADR 0036, FDD 019. Sétima repetição do
      padrão, e a primeira achada por **alguém usando o produto** em vez de por uma varredura: o
      tropeço (e) do `integracao-biahflow.md`. Arquivar um projeto no Biahflow emite webhook — o
      `archive()` de lá é um `save()` —, mas a rota de snapshot filtrava `archived_at__isnull=True`,
      então o portal vinha buscar o estado novo e levava **404**, que ele não tem como distinguir
      de "este id nunca existiu". O webhook respondia 500, nada era gravado, e a tela do cliente
      seguia mostrando como **ativo** um projeto encerrado, por todo o tempo que o arquivamento
      durasse — cada webhook seguinte batia no mesmo 404. Agora a fonte declara o fato
      (`archived_at` no snapshot, com 200), o portal tem **coluna própria** e não um valor de
      `ProjectStatus` (encerrado e "em implementação" são ortogonais: um projeto encerrado tinha um
      andamento quando acabou, e pôr os dois na mesma coluna perderia um deles ao restaurar), a
      tela marca "Projeto encerrado" ao lado da saúde — um projeto pode terminar No prazo — com o
      histórico inteiro, e `POST /chat` e `POST /me/pendings/{id}/comments` respondem **409**. Não
      404: neste contrato ele significa uma coisa só, é a única resposta que a regra 6 verifica em
      toda rota escopada, e corrompê-lo faria um cliente legítimo receber a mesma resposta de um
      estranho. O precedente é o 429 da quota (ADR 0022) — o código sai do motivo, e o motivo aqui
      é o estado do recurso. **Esta linha faltou por um dia**, e é a única vez em que uma fatia não
      atualizou este arquivo desde que ele existe.)*

- [x] **O que o Biahflow não conta ao portal.** *(ADR 0037, FDD 023, mais emenda na ADR 0003 de
      lá. Oitava repetição, e a promessa quebrada estava escrita **no outro repositório e em
      negrito**: "o que entra no snapshot precisa de emissor, sob pena de o portal exibir um estado
      que já mudou". `digital_employees` entrava no snapshot e não tinha emissor nenhum — cadastrar,
      mexer no KPI e **arquivar** um funcionário digital não avisavam ninguém, e arquivar era o
      pior dos três, porque tira a linha do snapshot: o roster do cliente exibia alguém que a fonte
      da verdade já tinha tirado. O roster é, pelo docstring do próprio modelo, o produto central.
      **A medição corrigiu o diagnóstico que a ADR 0036 deixou:** ela escreveu que "`retention.py`
      apaga documentos de vez, e exclusões em cascata idem", e a parte alarmante não se sustenta —
      o `DELETE` da API de lá **arquiva** (os nove viewsets são `ArchiveModelViewSet`), o Django
      admin não registra entidade de projeto nenhuma, e a retenção só alcança linha já arquivada,
      que a essa altura já saiu do snapshot e já foi propagada. Sobrava **um** caminho real, e ele
      é total: `Project.delete()` por shell, com o portal ficando com um projeto morto marcado como
      ativo **para sempre**, porque nenhum evento sai e não haverá evento seguinte daquele projeto.
      Agora há `post_delete` de `Project` — o único do repositório de lá, e a cascata inteira sai
      como **um** aviso, porque um por filho agendaria dezenas de buscas de snapshot (todas 404)
      antes do aviso que interessa. Deste lado, `event` ganhou **o primeiro leitor que já teve**:
      o Biahflow manda `event` e `object_type` desde a ADR 0006 e o portal nunca olhou nenhum dos
      dois — é a forma da guarda da ADR 0033 na direção de **entrada**, onde não há guarda porque o
      produtor mora noutro repositório. `source_deleted_at` é coluna separada de `archived_at`
      porque as duas chegam por portas diferentes: arquivamento vem no snapshot e o sync o reescreve
      a cada passagem (é assim que restaurar funciona), exclusão chega só pelo webhook, e numa
      coluna só o sync apagaria o fato. O portal **não apaga nada** — documento é evidência de
      citação já dada, e apagar tenant é decisão de pessoa executada pelo worker (ADR 0017), com um
      webhook não sendo exceção a isso.)*

- [x] **A citação sem data.** *(ADR 0038, FDD 024. Nona repetição do padrão, num documento de
      **três linhas** que nenhuma fatia jamais visitara: o `context-contract.md` prometia desde a
      Fase 3 que "toda citação aponta para fonte, localização e **data**", e nenhuma citação tinha
      data — `Evidence.citation` era `fonte — local` e `CitationOut` tinha `label` e `document_id`.
      A evidência já estava no banco sem consumidor: `Document.source_updated_at` (o `modifiedTime`
      do Drive), `indexed_at`, e o `PendingItem.created_at` que o sync carimba com o `opened_at` do
      Biahflow. **A ponta afiada é o turno guardado:** o `drive_sync` reindexa a **mesma linha**
      quando o arquivo muda, enquanto `conversation_message.citations` congela o rótulo — de modo
      que a citação clicável que a ADR 0017 criou *justamente para o cliente conferir* abre, meses
      depois, uma versão diferente daquela em que a resposta se apoiou, com rótulo idêntico. **E a
      medição impôs um limite à promessa:** marco e status **não** ganham data, porque a linha do
      marco é apagada e recriada a cada sincronização e o `created_at` dela diz quando o portal
      copiou, não quando o fato aconteceu — falsa precisão, que é o que `results.py` recusa quando
      falta premissa. O documento foi corrigido para dizer isso, com a retificação registrada. De
      quebra, **dois portões nasceram cegos e foram medidos**: o `template_sha256` do
      `prompt-registry.json` **não mudou** ao acrescentar a data à linha da evidência, porque a
      sentinela do digest não tinha data e percorria só o ramo antigo — a cobertura de um portão é
      a dos ramos que a amostra percorre, e a amostra é parte do portão; e o campo, chamado `date`,
      passava verde na guarda de consumo da ADR 0033 **sem consumidor nenhum**, porque aquela
      guarda casa nome por substring e `date` aparece em `new Date`, `dateStyle` e `due_date` — é o
      `.priority` daquela ADR outra vez, e renomear para `dated_at` foi o que tornou o elo
      verificável.)*

- [x] **A aba que esperava um escritor.** *(ADR 0049, FDD 003/018, mais emenda na ADR 0003 do
      `biahflow-portal`.)* O padrão outra vez, e desta vez com a espera mais longa que ele já
      teve: `Decision` tem modelo, RLS e `GRANT SELECT` desde a migração `0007` da Fase 1 e
      **nunca teve uma linha** — `DecisionRepository` com corpo vazio, nenhum chamador, e
      `build_dashboard` sem projetá-la. A terceira origem possível estava morta junto:
      `transcript_text` aparece só no modelo e na migração `0002` e nunca teve escritor, porque o
      texto da transcrição não atravessa o snapshot. O escritor nasceu **do outro lado** (FDD 032
      de lá), e o que fez a aba valer a pena foi o `rationale`, que o snapshot cortava de
      propósito. Duas decisões carregam o resto: a proveniência chega como pk e é projetada como
      rótulo (`meeting_title`), porque `Meeting` é recriada por inteiro a cada sync e não guarda
      id externo; e o `delete(Decision)` roda
      **antes** do `delete(Meeting)`, com o mapa de ids montado depois do `flush()` — sem isso o
      `ON DELETE SET NULL` apagaria a proveniência das decisões antigas "sem erro, sem log e sem
      exceção", e o teste afirma sobre ela **depois de dois syncs**. De quebra, fechou a única
      exceção que a regra 1 da busca carregava desde a ADR 0024 ("só entra o que alguma aba
      mostra"): a decisão virou sexta fonte, casando `title` **e** `rationale`.

**Aceite:** o cliente abre o portal e vê a jornada com "Você está aqui", clica numa fase e vê
objetivo e ROI, os entregáveis desbloqueados e os funcionários digitais — tudo vindo da API,
não de dados de demonstração. *E acha qualquer um deles pela lupa: `tests/e2e/search.spec.ts`
digita, clica e cai na aba, e sobe um documento com termo inédito para achá-lo **dentro** do
texto.*

## Fase 7 — Saber se o cliente engaja, e puxá-lo de volta (histórico e trabalho em curso)

Adicionada em 07/08/2026. As seis fases anteriores construíram o que o cliente **encontra**
quando abre o portal. Esta é sobre o que ele **não** faz: hoje o produto sabe se um projeto
está no prazo e **não sabe se o cliente está engajando**. Um projeto verde cujo cliente parou
de logar é churn silencioso, e só se descobre quando ele reclama ou some.

São três sinais que respondem perguntas diferentes sobre o mesmo cliente: ele **usa** (funil),
ele **ganha** (saúde e ROI, que já existem), ele **gosta** (satisfação). O princípio que rege
os três é **medir para agir, não para reportar** — se a medição não dispara ação, ela não
entra, e um painel sem dono é dívida, não ativo.

**A ordem é parte do conteúdo.** Um sinal de cada vez, com o laço de ação fechado de verdade
antes do seguinte. O gargalo nunca foi construir sinal: é a capacidade do time de responder a
ele, e três radares tocando para um time que não dá conta de agir em um é pior que um radar
que ele respeita.

- [ ] **Funil de onboarding medido — passos 1, 2 e 3 feitos e os sete degraus de pé, passo 4 aberto** *(RFC 001, FDD 020, ADR 0039, ADR 0040, ADR 0041)*: os degraus
      foram carimbados **antes** de qualquer leitor, que é a ordem que a RFC exige — escritor
      primeiro, leitor depois, porque a ADR 0033 achou um painel publicado sobre um campo sem
      escritor.
      Tabela por organização com carimbo **imutável** (nenhum papel tem `UPDATE`), `portal_app`
      **sem policy nenhuma** — um caminho de requisição capaz de escrever o próprio degrau é um
      caminho capaz de falsear o próprio engajamento —, seis degraus escritos pelas rotas de
      verdade, e a purga e o apagamento alcançando-os (este último precisou de exclusão à mão: o
      funil é escopado por organização e **não** vem no CASCADE do projeto, que o docstring do
      `_erase` dava como a única exceção). `artifact_accepted` ficou **fora do enum** porque o
      snapshot do Biahflow não carrega artefato — declarar degrau sem produtor seria o mesmo
      defeito. De quebra, o que só apareceu ao executar: `bool(rowcount)` não diz se a linha
      nasceu, porque `ON CONFLICT DO NOTHING` devolve **-1** nos dois casos e `bool(-1)` é `True` —
      todo carimbo se dizia "primeira vez", e o evento sairia a cada download.
      **O passo 3 chegou em 07/08/2026 (ADR 0040)**, com o leitor, a lista em `/admin/funil` e o
      alerta em dois canais — evento nomeado com limiar e notificação **só para o time**, a
      primeira do repositório a usar o `_INTERNAL_ONLY` que a ADR 0012 definiu e nunca usou. Três
      decisões carregam o resto. O degrau atual é o **mais baixo em aberto** e não o mais alto
      alcançado, porque o degrau do Biahflow chega retroativo e "mais alto alcançado" diria que
      completou o funil um cliente que nunca entrou. A rota **autoriza sob `portal_admin` e computa
      sob `portal_system`**, e o motivo foi encontrado do lado de dentro: `pending_item` não tem
      policy `TO portal_admin`, então o `EXISTS` de "há pendência aberta?" responderia "não" para
      **toda** organização e todo cliente do produto apareceria rotulado *travou em nós* — o desenho
      que a ADR 0039 escolheu de propósito para `portal_app`, visto pelo avesso. E o alerta toca uma
      vez porque a memória dele **já existia**: é o `dedupe_key` da notificação, o que dispensou a
      tabela que a ausência de `UPDATE` no funil tornaria inevitável. **De quebra, o defeito que só
      apareceu ao executar, e ele quase fez a medição nascer cega:** a regra de lacuna juntava duas
      perguntas, e ao separá-las ficou claro que no primeiro dia da instrumentação *toda*
      organização é anterior a ela — a tela nasceria mandando ligar para todo cliente do produto
      para dizer que ele nunca entrou no portal. A saída foi a evidência que a própria RFC apontava
      e ninguém lia: `user.external_subject`, o único degrau com corroboração fora do funil.
      **E o sétimo degrau chegou no mesmo dia (ADR 0041), com o adiamento cumprindo a própria
      condição:** o critério (3) da FDD 020 dizia que `artifact_accepted` não existia no enum
      "porque o snapshot do Biahflow não carrega artefato", e terminava com *"ele entra quando o
      outro lado o afirmar"*. Lá o dado estava inteiro desde a FDD 016 — `Artifact` com
      `sent → accepted`, `decided_at` carimbado no `save()`, o e-sign fechando o contrato sozinho —
      e o docstring do modelo dizia para que ele serve: *"permite medir onde a jornada trava entre
      uma etapa e a seguinte"*, que é esta RFC. Faltava **atravessar**: `build_snapshot` não levava
      artefato e `signals.py` não tinha receiver, a forma da ADR 0037 um degrau antes. Agora
      atravessa **só a data** (nem `kind`, nem `title`, nem `content`), com a linha "nenhum dado
      comercial é exposto" de lá **qualificada em emenda** em vez de contornada. **E o que a fatia
      destrava não é um item de lista, é a régua:** o `_anchor` nunca teve o *ganho* — contava do
      convite —, de modo que dezoito dias entre fechar o contrato e convidar a pessoa, que é demora
      **nossa**, encurtavam o número em vez de aparecer nele. O degrau entra **primeiro** na escada,
      é sempre `Blame.us` (o portal não hospeda aquela aprovação nem tem como coletá-la), e ganhou a
      mesma corroboração do login, desta vez prevista: **projeto vivo significa negócio fechado**,
      senão toda organização anterior à fatia apareceria mandando registrar um contrato assinado há
      meses. Na prática ele nunca é o degrau travado, e isso é a resposta certa — "não registraram o
      artefato" é higiene de cadastro, não desengajamento. **De quebra, um defeito da ADR 0039 que
      só apareceu ao construir o sétimo degrau:** `sync_snapshot` **cria** a organização e chamava
      um `stamp` de sessão própria, então no primeiro snapshot de um cliente novo a chave
      estrangeira barrava o `INSERT` e o carimbo se perdia em silêncio, saindo como
      `onboarding.stamp_failed` — que o `alerts.md` diagnostica como indisponibilidade do banco.
      Valia para o entregável desde sempre (medido), era raro lá e é o caso **central** aqui.
      `stamp_within` carimba dentro da transação que já é do sistema, com `SAVEPOINT`, porque um
      `IntegrityError` deixa a transação abortada e engolir a exceção sem ele trocaria um degrau
      perdido por um snapshot perdido. Falta o passo 4 (a vigília da IA), que segue condicionado ao
      histórico que ainda não existe.
      *A régua continua sendo o **time-to-first-value**, e as duas travas da proposta seguem
      valendo: instrumentar **degraus de valor, não vaidade** — o enum não tem nenhum degrau de
      esforço — e separar "travou no cliente" de "travou em nós", que agora é estrutura da tela
      (dois painéis, três contadores, nenhum total) e não convenção. A IA vigia e escreve o
      sinal ao time; **não conversa**.*
- [x] **Teto de frequência de contato — a primitiva que as duas features pediam pelo nome**
      *(FDD 021, FDD 022, ADR 0042)*: entregue em **fatia própria**, e o combinado era outro —
      ele sairia junto da FDD 022. O acordo não sobreviveu ao calendário: a FDD 022 está
      bloqueada por uma condição que **não é código** (o laço de ação do funil), e a FDD 021 não
      tem bloqueio nenhum, de modo que mantê-lo entregaria o canal **sem teto** — justamente o
      que as duas FDDs chamam de "o mais fácil de queimar" — ou prenderia o canal atrás de uma
      condição que não é dele. Pôr o teto *dentro* da FDD 021 parecia o barato e é o caro: um
      teto que mora num consumidor não é compartilhado, é o teto daquele consumidor com um nome
      maior, e nasceria com a forma de "aviso" enquanto a pesquisa dispara por evento de jornada.
      **Razão e não contador**, contra o precedente mais próximo e pelo argumento que o próprio
      `chat_limit.py` já tinha escrito: um contador subconta sob concorrência, o que no chat
      deixa passar uma pergunta a mais num limite de abuso e aqui deixa passar **uma mensagem a
      mais para uma pessoa** — o dano exato que o teto existe para impedir. O preço está pago,
      não contornado: a razão guarda comportamento de pessoa identificada, então carrega tenant,
      tem policy, é podada e é a **terceira** exclusão escrita à mão no apagamento — desta vez
      sem susto, porque a regra da ADR 0039 já existia quando a tabela nasceu. Duas decisões
      carregam o resto. A **chave de dedupe** não é higiene: sem ela a task de envio, que retenta
      sobre `whatsapp_sent_at IS NULL`, encontraria na segunda passagem o orçamento gasto **por
      ela mesma** na primeira, e uma indisponibilidade de minutos do fornecedor viraria silêncio
      **permanente** naquele canal, sem deixar rastro. E a **policy nega por escrito**
      (`USING (false)`) em vez de negar por omissão como as três tabelas anteriores sem leitor:
      a omissão reprovaria o meta-teste de RLS, e a saída fácil — conceder `SELECT` ao admin
      "para a tela que virá" — é o defeito da ADR 0033 escrito ao contrário. **De quebra, o que a
      fatia mediu e a FDD 022 não sabia:** o teto global **não** satisfaz sozinho o critério de
      aceite (2) de lá — "um segundo evento na mesma semana não gera segundo convite" é
      afirmação sobre a **espécie**, não sobre o volume, e com três por semana dois convites
      passam. Falta intervalo mínimo por espécie, que entra junto de `survey_invite`; ficou
      escrito na emenda daquela FDD em vez de virar dívida redescoberta no meio da implementação.
      *O valor padrão não tem medição por trás — a primeira virá do próprio `contact.suppressed`
      —, e é por isso que ele é setting e não constante de módulo. ~~**Aberto:** teto de
      horário.~~ *Fechado em 19/08/2026 (ADR 0055).*
- [x] **Canal de WhatsApp — e o link que não existia** *(RFC 002, FDD 021, ADR 0043)*: aviso
      1:1 por template ao lado do sino e do digest, no ponto de extensão que a ADR 0012 já
      descreve, com opt-in revogável como coluna da pessoa. **Nunca grupo** e **nunca IA**: o
      corpo é um template de dois parâmetros, e a razão de existir de um grupo é conversa de
      muitos para muitos, que é o que não se quer fora do portal.
      **Metade da fatia não era o canal, e isso só apareceu ao construir.** O critério de
      aceite (4) exige que o link caia "na coisa exata, nunca na home", e **não havia link
      nem URL que o suportasse**. `Notification.link` existe desde a Fase 2 e o sino o
      renderiza como `<a>` quando preenchido — e as dez ramificações do `diff` **nunca o
      preencheram**, de modo que todo aviso de cliente chegava sem link desde então: a
      ADR 0033 outra vez, na direção que ninguém tinha olhado, porque lá era um painel sobre
      campo sem escritor e aqui é um **controle** sobre campo sem escritor (a guarda de
      consumo não o pega — ela pergunta se há consumidor, e há; faltava produtor). E a
      navegação por abas era estado de React, sem URL que a alcançasse, então nem havia o que
      escrever. As duas coisas vieram primeiro, e **o sino ganhou links de carona**.
      O rótulo da aba virou identificador em três arquivos e por isso virou módulo
      (`tabs.py`, a forma do `textfold.py`), com guarda que lê o TSX e compara — a divergência
      ali não deixa nada vermelho: o cliente clica na mensagem e chega no lugar errado.
      Três decisões carregam o resto. **A mensagem não tem campo livre**: `send_notice` recebe
      título e URL e monta o corpo sozinho, e o `detail` do aviso — o campo de texto livre do
      modelo — não entra, o que faz "nenhum trecho de documento sai" ser estrutural em vez de
      disciplina; o teste semeia uma cláusula e um valor de propósito e afirma sobre **o corpo
      enviado**. **O consentimento é conferido no envio**, não no formulário, e é isso que faz
      a revogação alcançar o que já está na fila sem varrer fila nenhuma — nasce desligado, ao
      contrário do e-mail, porque um canal que chega no bolso da pessoa exige que ela diga sim,
      e ligá-lo sem número é 422 em vez de um interruptor sobre coisa nenhuma. E **duas colunas
      de carimbo**, não uma: num carimbo só o SMTP fora do ar cancelaria o WhatsApp.
      A resposta do cliente vira aviso do **time** com link para as pendências, nunca thread no
      canal: spoke, e um spoke que hospeda conversa vira hub sem ninguém decidir. Sem tabela de
      entrada — a idempotência é o `dedupe_key` carregando o id do evento do fornecedor.
      **De quebra, três guardas cobraram e as três estavam certas:** o `phone_hint` reprovou na
      guarda de contrato por ter nome de segredo (a resposta foi a allowlist, como o
      `key_prefix` — renomear passaria pela guarda sem mudar o dado); a guarda de consumo
      mostrou que a tela **recalculava** o `phone_hint` em vez de ler o do servidor, duplicando
      a normalização; e a de allowlist obsoleta cobrou a linha que dizia que aquele campo era
      "eco que a tela já sabe", frase que deixou de ser verdade no mesmo commit.
      *A retentativa depois de uma queda do fornecedor **não** gasta uma segunda unidade do
      teto, porque a reserva é pela chave do aviso — sem isso, uma indisponibilidade de minutos
      viraria silêncio permanente naquele canal, e sem rastro. Está em regressão.*
      *~~**Aberto:** o link em granularidade de item (hoje cai na aba, a mesma resolução que a
      busca estabeleceu).~~ Fechado em 19/08/2026 (ADR 0056). O teto de horário, que esta linha
      também dava como aberto, foi fechado no mesmo dia (ADR 0055).*
- [x] **Teto de horário — e quem volta buscar o que ele adiou** *(FDD 021, ADR 0055)*: a mesma
      ponta que as ADRs 0042 e 0043 deixaram nomeada com as mesmas palavras — *"é decisão do
      remetente, não do orçamento, e **entra com o canal**"* — e que não entrou com o canal. O teto
      que existia conta contatos e não sabe que horas são: três por semana permitidas continuavam
      sendo três às três da manhã. **E metade da fatia não era o teto**, o que só apareceu ao
      medir: não havia entrada de `beat_schedule` para a task de envio, que só rodava no fim de um
      sync do Biahflow — de modo que **adiar não tinha quem voltasse buscar**, e num projeto quieto
      o "depois" não chegava. Uma guarda de horário sem varredura seria descarte com outro nome, e
      pior que o descarte honesto, porque ninguém procura o aviso que o documento diz que saiu.
      Três decisões carregam o resto. A guarda de horário é a **primeira que não carimba**: as três
      do laço carimbam porque o que as motiva é definitivo, e o relógio não foi gasto, só ainda não
      chegou. Ela vem **antes** do `claim`, senão o aviso voltaria de manhã já suprimido pelo teto
      que ele mesmo consumiu de madrugada. E o **fuso é constante** enquanto as **horas são
      setting**, cada um pelo critério que já existia — o fuso porque a ADR 0026 decidiu que ele
      não é configurável neste produto, as horas porque não têm medição por trás, que foi o
      argumento da ADR 0042 para os três contatos por semana. **De quebra, a varredura conserta o
      que já estava quebrado:** a retentativa depois de uma queda do fornecedor dependia de um sync
      que podia não vir, e o `alerts.md` afirmava o contrário — a linha foi retificada com nota
      datada. E, com dois produtores, duas passagens podiam mandar a mesma mensagem duas vezes: o
      `claim` não protege disso, porque é idempotente pela chave do aviso e responde `True` para as
      duas de propósito. A resposta é `FOR UPDATE SKIP LOCKED` dentro do banco, pelo precedente da
      guarda de sobreposição do sync do Drive — e o que a medição mostrou é que **sem ela a
      regressão não fica vermelha, fica pendurada**, porque a passagem bloqueia em vez de enviar;
      daí o teste de concorrência ter prazo e afirmar *ter terminado*. *Fica aberto: feriado e fim
      de semana, que são calendário e não horário, e o teto de horário do e-mail do digest,
      deliberadamente fora.*
- [x] **O link que cai no item** *(FDD 021, ADR 0056)*: a última ponta que a ADR 0043 deixou
      nomeada. O aviso caía na **aba** — a mesma resolução da busca —, e o critério de aceite (4)
      da FDD 021 pede "a coisa exata, nunca na home"; a FDD abria afirmando que os seis critérios
      estavam de pé, e os dois documentos não podiam estar certos ao mesmo tempo. Agora o link
      carrega `&item=<namespace>:<rótulo>`, e a tela destaca a linha e rola até ela.
      **A âncora é o rótulo, e o porquê foi medido:** só `PendingOut` publica `id` entre os seis
      esquemas de lista, e nem ele serviria — o sync do Biahflow apaga e recria essas linhas, e o
      link do canal é assíncrono por desenho, então um link por uuid **nasceria apontando para uma
      linha que vai deixar de existir**. O rótulo é o identificador que a tela já usa como chave
      React; é a terceira vez que o repositório decide isso (ADR 0024 na busca, ADR 0043 nas abas).
      A pergunta "que tela?" continua sendo por espécie e fica no `LINK_TAB`; "qual linha?" é por
      **evento** e vai em `Change.item`, com o namespace escrito uma vez por espécie no
      `ITEM_ANCHOR` e a composição num lugar só. Quem não aponta para linha nenhuma tem frase
      assinada em `ANCHORLESS`, na forma do `NOT_AN_ALERT`.
      **O teto de tamanho dropa a âncora em vez de truncar** — âncora truncada não casa com nada
      *parecendo* que casou —, e a ADR registra que **nenhum limite de caracteres do fornecedor foi
      medido**: `_MAX_LINK` é sanidade, e o que sustenta a escolha é a queda ser monotônica (sem
      âncora, o link é o de antes). **A jornada tem dois níveis** e é onde o link seria correto e
      inalcançável: o painel só desenha os entregáveis da fase selecionada, então a fase passa a ser
      derivada da âncora — o que também dispensa âncora composta e o escape do separador. E o
      seletor do efeito **não interpola** o valor, que vem da barra de endereço: uma aspa no título
      quebraria o `querySelector`, então a varredura compara `getAttribute` em JavaScript.
      **As duas guardas que ligam os deployables nasceram vermelhas, e isso é o ponto:** foram
      escritas antes do TSX e vistas falhando, acusando os seis namespaces "só no Python" e as nove
      espécies com o componente certo de cada uma — o achado da ADR 0033 aplicado antes do fato, e
      não depois. A varredura de `Change` é por AST e alcança as **quatro** origens, que é o ponto
      cego que deixou dez ramificações sem `link` até a ADR 0043. *De quebra: a fixture do SSR
      trazia `link: null` nas duas notificações, contradizendo a garantia da ADR 0043 sem que nada
      pegasse — o ramo `<a>` da Central era código morto nos testes. ~~Fica aberto e nomeado: o
      popover do sino, cuja linha é `<div>` e não `<a>`, e a âncora na busca.~~ **As duas foram
      fechadas em 19/08/2026 (ADR 0057), no mesmo dia.***
- [x] **A âncora nas duas superfícies internas, e a que não morria** *(FDD 021, FDD 018, ADR 0057)*:
      as duas pontas que a ADR 0056 deixou nomeadas, e um defeito dela. O link do WhatsApp caía na
      **linha** e a navegação de dentro do portal ainda caía na **aba** — o cliente que recebia a
      mensagem chegava melhor no assunto do que o cliente que já estava com o portal aberto, o que
      inverte a ordem de esforço que justifica o canal. Agora o popover do sino é `<a>` com o mesmo
      componente da Central, e a busca manda `item_anchor` junto do `tab`.
      **O popover foi nomeado como ponta aberta duas vezes e sobreviveu às duas**, e a causa virou
      guarda: toda asserção sobre a âncora era sobre **dado**, e um `<div className="popover-row">`
      renderiza HTML indistinguível de um `<a>` — é o `inertButtons()` da ADR 0026 num controle que
      aquela guarda não alcança, porque ali o defeito é um `<button>` sem handler e aqui é uma linha
      que nunca chegou a ser controle.
      **A interceptação recusa em três casos e cai no `href`**, e a recusa do meio é a que importa:
      o `link` carrega `?project=`, e um `goTo(tab, item)` puro o descartaria em silêncio. É a
      defesa contra a ponta aberta abaixo, e a queda é monotônica — recusar devolve o comportamento
      de antes da fatia, nunca um clique morto. A Central perdeu o `target="_blank"` junto: abrir
      aba nova para chegar a uma lista já aberta era resto de quando o link era só URL a copiar.
      **O nome do campo foi medido, não escolhido:** chamado `item`, ele passa **verde** na guarda
      de consumo do `api-contract.test.mjs` **sem consumidor nenhum**, porque ela casa por substring
      e `DashboardClient.tsx` contém `notifications.items` — `".items"` contém `".item"`. É o
      achado `date`→`dated_at` da ADR 0038, na mesma guarda e pelo mesmo mecanismo; renomear para
      `item_anchor` foi o que tornou o elo verificável. A âncora da busca é **derivada** (`Hit.title`
      *é* o rótulo nas seis espécies, ao contrário do rótulo do aviso, que é do evento), o namespace
      é explícito por espécie e nunca derivado do `kind` — derivá-lo daria a `chunk` um namespace
      inexistente e a `decision` um que a ADR 0056 recusou —, e `decision` tem frase assinada em
      `ANCHORLESS_HITS`. Os seis espaços de nomes mudaram de casa para `anchors.py` ao ganhar o
      terceiro consumidor, **sem mudar de valor**, como os rótulos de aba na ADR 0043.
      *De quebra, um defeito **da ADR 0056**: a barra lateral chamava `setActiveNav` direto e não
      passava pelo `goTo`, de modo que a âncora sobrevivia à navegação — a nota "O item deste aviso
      não está mais nesta lista." seguia o cliente por todas as abas e o efeito de rolagem
      re-destacava uma linha já dispensada. A promessa estava escrita no comentário da função que
      deveria cumpri-la, e não tinha teste em nível nenhum: as asserções de HTML renderizado veem um
      render, e o defeito só aparece no segundo.*
      **Toda guarda nova foi vista falhando antes do código**, com a mutação que a prova registrada
      na ADR — e a mais cara: a igualdade de espaços de nomes virou **união** e não subconjunto,
      porque a versão antiga passa verde com `HIT_ANCHOR["milestone"]="marco"` (medido).
      *Fica aberto e nomeado: **`GET /me/search` e `GET /me/notifications` não aceitam `?project=`**
      e respondem pelo projeto mais recente da pessoa, enquanto o dashboard ao lado vem por id — um
      cliente com dois projetos, vendo B, recebe os avisos e os resultados de A. A FDD 018 e o
      docstring de `my_notifications` afirmavam o contrário, e as duas foram corrigidas com a
      medição escrita.*
- [x] **O verde que dependia da hora** *(ADR 0058)*: defeito da ADR 0055, achado ao rodar a
      bateria de madrugada. Aquela fatia fez o worker consultar a janela de silêncio de verdade e
      criou o `_freeze`, usando-o **só nos testes que ela mesma acrescentou** — os anteriores
      chamavam um `_run` que não congelava nada, de modo que a hora da máquina passou a decidir se
      sete testes passam. O custo não era local: 21h–08h em São Paulo é **00:00–11:00 UTC**, então o
      job `api-quality` ficava vermelho onze horas por dia, para qualquer branch, por motivo que não
      tem a ver com o código empurrado. A ADR 0055 passou por ter sido commitada às 17h13.
      Medido nas duas direções — de madrugada reprovam os sete; com a janela desligada por variável,
      passam os sete e reprovam os cinco que afirmam sobre a janela.
      Agora `_run` exige a hora **na assinatura** (padrão resolveria os sete de hoje e deixaria o
      oitavo nascer errado amanhã), e `PRODUCT_TIMEZONE` mudou de casa para `clock.py` sem mudar de
      valor, com `product_hour` e `product_date` — folha pela razão de `textfold.py` e `anchors.py`,
      e havia **dois** lugares respondendo "que dia é hoje", já divergentes.
      *De quebra, a mesma classe no código de produto: `_results_projection` decidia "marco
      atrasado" com `date.today()` — a data da máquina, UTC no contêiner —, o que adiantava o corte
      em três horas em relação ao dia que o cliente vê; e o teste de vigência de preço comparava
      data local com um razão que conta em UTC.*
      **A guarda nasceu vermelha com oito funções, e não com sete**: uma delas aciona o envio sem
      declarar a hora e o relógio nunca a pegou. E o **elo é com a ordem**, medido: com a versão que
      só perguntava "existe um `_freeze` aqui?", um `_freeze` **depois** do envio passa verde — a
      frouxidão que a ADR 0035 mediu ao dar `POST /chat` como coberto por um 404 de outra rota.
      *~~Fica declarado, e não corrigido: dois testes reprovam por resíduo do banco de
      desenvolvimento (passam isolados e em banco novo), e `_settings()` ainda deixa a variável de
      ambiente da janela entrar nos testes que afirmam sobre ela.~~* **As duas pontas fechadas em
      20/08/2026 (ADR 0060) — e a primeira estava diagnosticada errado: não era resíduo.**
- [x] **O projeto que a tela mostra, e o parâmetro que ninguém mandava** *(FDD 018, FDD 021,
      ADR 0059)*: o item F1 que a ADR 0057 mediu, nomeou e não corrigiu. `access.default_project`
      devolve a membership **mais recente**, e onze rotas de cliente resolviam o projeto assim
      enquanto o dashboard ao lado vinha de `/projects/{project_id}/dashboard` com o `?project=` da
      URL — de modo que um cliente com dois projetos, vendo B, tinha o sino e a busca de A e recebia
      **404** ao abrir os comentários de uma pendência de B, porque o item era procurado sob o
      tenant de A. Agora nove rotas aceitam `?project=` (a décima não: o dashboard já tem caminho
      por id, e um segundo caminho para a mesma coisa é sedimento), ausente continua sendo o padrão,
      e projeto alheio é **404 e nunca queda silenciosa no padrão** — que devolveria a lista de
      outro projeto com 200, o `.get(kind, _CLIENT_ONLY)` da ADR 0040 na mesma forma.
      *De quebra, o achado que carrega a guarda: `POST /chat` **já** aceitava `project_id` no corpo
      e o honrava desde a Fase 3, e o BFF **nunca o mandou** — campo de **entrada** publicado sem
      remetente, o espelho exato do painel sobre campo sem escritor da ADR 0033, que a guarda de
      consumo não pega porque ela pergunta pelos campos de resposta.*
      **A guarda nova nasceu vermelha sobre esse campo, e três frouxidões independentes foram
      medidas** — cada uma sozinha a deixa verde sobre defeito real: corpus único (o `.priority` da
      ADR 0033 pela terceira vez, e ele erra nas duas direções ao mesmo tempo), nome solto casando
      onde não há envio (`projects.map((project) =>`), e — as duas achadas na revisão, com a guarda
      já verde — o corpus que inclui os consumidores da rota mais a aspa solta, que juntos dão como
      enviado um parâmetro que o **proxy do BFF recebe e descarta**. Só com as duas últimas
      corrigidas a mutação fica vermelha, e nenhuma delas é suficiente sozinha.
      *E o teste que faltava no repositório inteiro era **um ator com duas memberships**: com um
      projeto por pessoa, "o mais recente" e "o que está na tela" são sempre o mesmo projeto e a
      diferença não tem como aparecer — foi assim que o defeito atravessou seis fases. O caso
      negativo das nove rotas tem **controle positivo** com alvo real, senão um id inventado daria
      404 pelos dois motivos ao mesmo tempo (a medida da ADR 0035).*
      *Fica aberto e nomeado: `activeProject` cai em `projects[0]` quando o casamento por nome de
      `app/page.tsx` falha — dois projetos homônimos no mesmo tenant fariam a tela nomear um projeto
      diferente do que a API serviu. Pré-existente, não tocado.*
- [x] **O verde que dependia do ambiente** *(ADR 0060)*: irmã da ADR 0058, e **retificação por
      escrito** das duas pontas que ela deixou abertas — uma delas diagnosticada errado.
      *Configuração:* a ADR 0058 viu uma porta e havia **duas**. Com `CONTACT_QUIET_HOURS_START/END`
      em `0` reprovam cinco testes do canal; com um `.env` no disco trazendo **só aquelas duas
      linhas**, reprovam **os mesmos cinco** — `Settings` carrega `env_file=".env"`, e são 103
      campos, não dois. Agora `conftest.py` troca as **fontes** da `Settings` (filtra `env_settings`
      **e** `dotenv_settings`) contra uma allowlist de sete nomes com motivo por linha, todos
      passados pelo `env:` do `ci.yml`: *a bateria lê o ambiente para saber onde está um serviço,
      nunca para saber como o produto se comporta*. Fixar os dois campos no `base` de `_settings()`
      consertaria 2 campos em 1 arquivo e deixaria 101 de pé — a lista escrita à mão da ADR 0033.
      *Estado:* **não era resíduo do banco**, e a prova é de dois passos —
      `test_a_client_only_sees_and_reads_their_own_notifications` reprova com o contêiner `worker`
      de pé e **passa, no mesmo banco**, com ele parado. Oitenta e nove linhas antes, no mesmo
      `world` (que é etiquetado com `uuid` a cada sessão), outro teste faz `POST /chat` de verdade,
      a pendência é publicada no Redis do compose e o worker a consome contra o **mesmo Postgres**,
      inserindo na caixa do cliente uma notificação que aquele teste não criou. Agora uma fixture
      `autouse` intercepta `celery_app.send_task` — a porta única por onde todo `.delay()` desce —,
      o que o docstring de `queued_ingestions` já descrevia palavra por palavra para **um** sítio.
      E as três asserções sobre varredura global (`assert queued == []`, `marked == 1`,
      `alerted == 1`) passam a ser sobre **linhas identificadas**, com controle positivo: a
      varredura é global por desenho e o defeito era da asserção, que só ficava verde num banco
      vazio. `unread_count` fica em **delta** em vez de sair — é campo publicado e consumido, e
      apagar sua única cobertura é a ADR 0033 pelo avesso.
      **As sete guardas nasceram vermelhas** e a saída está transcrita na ADR: a do envenenamento
      com **96 de 96** campos atravessando, nas duas portas; a de completude nomeando os três
      `float` quando o envenenador é cegado; a da allowlist trazendo **de volta os cinco de M1** ao
      admitir `CONTACT_QUIET_HOURS_START`; a do vizinho barulhento; a de AST com **cinco** funções,
      arquivo e linha; e a do broker, vermelha nos **dois** ambientes por motivos opostos (com
      broker foi publicada, sem broker o `except` engoliu).
      **A medição que manda no desenho:** derivar as varreduras do `beat_schedule` **avaliado** em
      vez do AST daria 3 em vez de 5 — `whatsapp_enabled` e `drive_sync_enabled` são `False` por
      default —, e **três** testes escapariam em verde, incluindo o próprio defeito que a fatia
      existe para pegar. A amostra seria a configuração da máquina, que é a herança que a outra
      metade corta.
      *De quebra, uma saída medida e escrita: a costura deixou `test_homolog_config.py` vermelho,
      porque a pergunta dele é literalmente "este template seria recusado?" — uma subclasse que
      **nomeia o próprio arquivo** declara, e por isso o `dotenv` dela passa, com allowlist e guarda
      própria para a saída não ficar invisível. O `os.environ` continua filtrado até para ela.*
      *Fica declarado, e não corrigido: os cinquenta sítios `Settings(` continuam onde estão (a
      costura os cobre), e o Postgres de desenvolvimento **não** é limpo — o objetivo era um portão
      que não dependa do estado do banco, e limpar entregaria o verde sem o portão.*
- [ ] **Pesquisa de satisfação por evento.** *(FDD 022.)* **Segundo sinal — só depois que o
      laço do funil estiver fechado.** Uma pergunta no momento com significado (fase concluída,
      entregável aceito), não NPS de calendário, com teto de frequência por pessoa. A forma já
      existe: a ADR 0015 grava nota e comentário com GRANT de coluna, e a ADR 0030 lê o sinal
      **sem a pergunta do cliente**. Nota baixa vira alerta na hora; a IA lê o texto aberto e
      prioriza detratores. E a regressão que a ADR 0033 deixou de herança: **painel só nasce
      depois do escritor**.

**Pontas abertas da fase, sem dono e sem prioridade** (seleção é gate humano):

- **Intervalo mínimo por espécie de mensagem.** Medido na ADR 0042 e escrito na emenda da FDD 022:
  o teto global **não** satisfaz sozinho o critério (2) de lá, porque "um segundo evento na mesma
  semana não gera segundo convite" é afirmação sobre a **espécie** e não sobre o volume — com três
  por semana, dois convites passam. Entra junto de `survey_invite`.

*Fechadas, para não serem reabertas por leitura de ADR:* o **teto de horário**, que as ADRs 0042 e
0043 deixaram aberto e a ADR 0055 entregou em 19/08/2026, junto da varredura sem a qual ele seria
um descarte; e **o link em granularidade de item**, que a ADR 0043 deixou nomeado e a ADR 0056
entregou no mesmo dia — com o **popover do sino** e a **âncora na busca**, que aquela deixou
nomeadas e a ADR 0057 fechou também em 19/08/2026; e **o sino e a busca que não eram do projeto na
tela**, que a ADR 0057 mediu e deixou aberto com todas as letras e a ADR 0059 fechou em 20/08/2026.
Ler aquelas quatro sem estas linhas as dá como pendentes.

**Fora do recorte, e registrado porque nenhuma feature resolve:** velocidade de resposta é
compromisso operacional, não código — o portal pode ser impecável, mas se o cliente perguntar
e o time levar seis horas onde o WhatsApp levaria seis minutos, ele volta para o WhatsApp. E
**sinal traz de volta, valor retém**: se ao voltar não houver algo que importa, nenhum alerta
salva.

## Homologação na nuvem — a implantação como código (07 a 19/08/2026)

Registrada aqui em 19/08/2026, e o atraso é parte do assunto: dez ADRs foram aceitas entre 07 e
13/08 sem que este arquivo — que é o índice canônico de descoberta — soubesse de nenhuma. **Não é
uma fase.** As fases deste roadmap são de produto e entram na ordem recomendada; implantação é
transversal, como a Fase 5 foi. O procedimento vive em `docs/runbooks/hml-gcp.md`; o que segue é o
que cada decisão custou e o que ela mediu.

O ambiente é a HML da GCP: Cloud Run para os serviços, worker pools para o Celery, Postgres no Neon
e Redis no Upstash, com Terraform em `infra/terraform/` (dois estados hoje, `ambientes/hml` e
`ambientes/hml-biahflow`) e um portão de Terraform sem credencial no CI — `fmt -check`,
`init -backend=false` e `validate`, no job `infra-quality`. **Do portal do cliente não há nada de
pé** desde 13/08 — a nota no topo deste arquivo explica por quê.

- [x] **O bootstrap num Postgres que não tem superusuário.** *(ADR 0044, 07/08.)* O
      `infra/postgres/bootstrap/roles.sql` nasceu contra o Postgres do compose, onde quem o executa
      **nasce superusuário**, e por isso nunca houve razão para separar "o que o script quer" de "o
      que só um superusuário pode fazer". O Neon separou, e o que ele recusa foi medido: das sete
      cláusulas de `ALTER ROLE` ele aceita seis e nega `NOSUPERUSER` (`permission denied to alter
      role`), e o `ALTER SCHEMA portal OWNER TO portal_migrator` falha com `must be able to SET
      ROLE`. `NOSUPERUSER` passou a um bloco guardado por `current_user`, e o bootstrap concede
      `portal_migrator` a si mesmo apenas para transferir a posse do schema — `portal_system` fica
      de fora. Verificado nos dois alvos: contra o Neon real o script roda inteiro e os quatro
      papéis saem com os atributos certos; contra o compose, as 55 asserções de RLS continuam
      verdes, que é a prova de que a credencial de requisição não ganhou nada no caminho.
- [x] **O worker que cabia no Cloud Run.** *(ADR 0045, 07/08 — substitui a VM da primeira versão do
      Terraform.)* A justificativa da VM era verdadeira e a conclusão não: `celery worker` e
      `celery beat` de fato não escutam porta, mas existe a primitiva **worker pool** do Cloud Run,
      sem `ports`. A VM sai inteira, o Redis vai para o Upstash, e a VPC fica só para o ingress
      interno fazer sentido, com Cloud NAT para a saída. O `polling_interval=5s` no `worker.py` é
      medida e não estilo: derruba de ~86 mil para ~17 mil comandos por dia e por instância, num
      Redis que cobra por comando. E três Cloud Run Jobs passaram a ser criados pelo próprio
      Terraform — antes eram **invocados por workflows sem existir**.
- [x] **Os nomes que não apontavam para nada.** *(ADR 0046, 08/08 — corrige as duas anteriores.)* O
      Terraform e os dois workflows existiam como código e **nunca tinham rodado**: o CI parava em
      `google-github-actions/auth` por não haver `WIF_PROVIDER`, e não havia porque não havia
      projeto GCP. Um bloqueio de ação humana na primeira linha do primeiro job é o que mantinha
      tudo sem execução e portanto sem medição — nove defeitos apareceram de uma vez. Entre eles: o
      `tag_imagem` placeholder quebrava o **primeiro** apply, porque `ignore_changes` age em
      *update* e não em *create*; a conta de deploy não tinha permissão nem para o `terraform
      init`; o `nip.io` era montado sobre o IP de **saída** do Cloud NAT, endereço onde nada
      escuta; o `preflight.py`, simulado contra o ambiente que aquele Terraform entregava,
      recusaria a subida da API por sete variáveis caídas no default local; e o realm tinha um
      **quarto** nome — `servicos.tf` dizia `/realms/portal`, que não era nome de coisa nenhuma,
      enquanto o runbook manda criar `portal-homolog`.
- [x] **A barreira que o navegador não atravessa.** *(ADR 0048, 12/08.)* Três defeitos achados ao
      construir o que a ADR 0046 deixou aberto, e o segundo é o que ensina: a sonda
      `^/(healthz|readyz)$` não casa barra final, enquanto o middleware do Django responde as duas
      formas — o balanceador leria o `index.html` com 200 e chamaria de saudável um serviço que não
      respondeu à pergunta. Junto veio o `scripts/redis_rate.py`, e ele mediu o que a ADR 0045
      previra: o tráfego real do Celery ocioso é da ordem de **15x** a estimativa, porque gossip,
      mingle, heartbeat e o result backend não estavam na conta. O `restore.sh` passou a saber
      descrever um alvo gerenciado (`RESTORE_ADMIN_URL`, `POSTGRES_MAINTENANCE_DB` e a precondição
      de pertencer a `portal_migrator`), fechando no código a lacuna que a ADR 0044 deixou.
- [x] **O primeiro `apply`, e as três coisas que só ele podia dizer.** *(ADR 0050, 12/08.)*
      Nenhuma das três se deduzia do HCL. `version = "latest"` de um segredo **sem versão** não
      existe, e a revisão do Cloud Run é recusada na **criação** e não no boot — o que obrigou o
      apply em dois tempos (fundação, preencher os 26 segredos, resto). A organização nasce com
      Domain Restricted Sharing ligado, então as ligações públicas falhavam com "one or more users
      named in the policy do not belong to a permitted customer", e a exceção teve de ser escopada
      ao projeto por alguém com papel que **só existe em organização ou pasta**. E o `check
      --deploy` do Django reprovava o boot por `NUM_PROXIES` ausente ao lado de um
      `TRUST_X_FORWARDED_PROTO` que já estava lá.
- [x] **Três states, um por dono.** *(ADR 0051, 12/08.)* O state único tinha **129 entradas**, e o
      que ele escondia não era tamanho: `DATABASE_URL` e `REDIS_URL` eram **um segredo só, com um
      valor só, montado nos dois produtos** — efeito colateral de `segredos` ser lista, nunca
      decidido —, de modo que um merge na API do portal rodaria `alembic upgrade head` contra o
      banco do Biahflow. Era essa a razão de o `WIF_PROVIDER` deste repositório estar desligado.
      Três estados, prefixos diferentes no mesmo bucket, e só **16** recursos atravessaram; a
      travessia foi `removed` + `import` e nunca `state mv`, e nenhum plano mostrou `must be
      replaced` num serviço do Cloud Run. A borda ficou na fundação porque o NEG referencia o
      serviço por **nome**, que é string e não cria ciclo entre estados.
- [x] **O que a primeira subida do portal mostrou.** *(ADR 0052, 12/08.)* Sete defeitos, e **seis
      da mesma família**: variável que o compose declara e o Terraform não reproduzia — com o
      sintoma sendo silêncio, porque o código lê com default vazio e desliga o recurso que ela
      habilitava. `KC_DB_SCHEMA` ausente faria o Keycloak migrar para `public`, ficando **fora do
      `pg_dump -n portal`** do backup; `KC_PROXY` foi removido no Keycloak 26 e é ignorado em
      silêncio, o que anunciava um `issuer` em `http://` e fazia a API recusar todo token; e
      `KEYCLOAK_INTERNAL_URL` tem semânticas diferentes no BFF e na API, então um valor só acertava
      um dos dois. O sétimo foi a corrida do primeiro login, registrada na Fase 1 acima. Login
      fechou ponta a ponta, e a conta entrou e viu "nenhum projeto atribuído" — que é a resposta
      certa, porque nenhum snapshot tinha rodado naquela HML.
- [x] **A homologação dorme.** *(Commit `1062875`, 13/08 — sem ADR própria.)* Seis processos de
      1 vCPU acesos 730h/mês sem ninguém usando. A investigação começou por outro alvo, a remoção
      do Cloud NAT, e a medição a recusou: Private Google Access só cobre destinos do Google, e
      Neon, Upstash, Anthropic, Voyage e o SMTP manteriam o NAT de pé de qualquer forma — o custo
      estava nos processos, não na rede. Os serviços HTTP foram a `min = 0` com a previsão de "503
      no primeiro acesso" **não se confirmando** (o Cloud Run segura a requisição até a sonda
      passar: o que sobra é latência), e o Keycloak também, com boots reais de 43,6s e 115,7s e a
      decisão explícita de que quem espera é a equipe. Desligar worker pool **não é escalar a
      zero** — não há requisição que o acorde —, e por isso a armadilha registrada não é o custo, é
      o esquecimento.
- [x] **A borda que passou a servir um produto só.** *(ADR 0053, 13/08 — substitui a ADR 0048 na
      parte do balanceador.)* O portal saiu do ar por decisão de produto, e levou junto metade da
      borda: os três termos que justificavam o balanceador global eram sobre **dois** produtos, e
      com um só não sobra o que dobrar, nem segundo IP a evitar, nem hostnames de outro produto a
      não quebrar. O que restava era um balanceador global servindo uma aplicação a ~US$ 18/mês em
      regras de encaminhamento mais ~US$ 7/mês de IP reservado — cuja tarifa, **fora de uso, é o
      dobro** da de em uso. A borda passou para a Cloudflare, que já era autoridade da zona e já
      terminava TLS para o site. O override de `Host` das Origin Rules era a ferramenta óbvia e a
      API **recusa** por entitlement de plano (`not entitled to use the HostHeader override`), o
      que foi resolvido com um Worker, onde o `Host` sai da URL da subrequisição — com
      `redirect: "manual"`, porque o padrão engoliria o `Set-Cookie` de um 302 e devolveria um
      login que responde "ok" sem autenticar ninguém. E a `deletion_protection` do provider 6.x,
      ligada por default sem que arquivo nenhum dissesse isso, só apareceu no `destroy`: reprovou
      **três vezes**, uma por tipo de recurso, cada uma depois de já ter derrubado o que não era
      protegido.

- [x] **O índice que não sabia.** *(ADR 0054, 19/08 — não é item de implantação, e está aqui
      porque é o portão da lacuna que abre esta seção.)* As dez linhas acima chegaram com seis dias
      a doze de atraso, e o `AGENTS.md` ganhou a regra de atualizar este arquivo no mesmo commit —
      regra escrita à mão, que é onde a ADR 0034 já mostrou o que acontece: lá o `alerts.md` foi
      corrigido à mão, ficou sem portão e **divergiu de novo em dois dias**. Agora
      `test_roadmap_index.py` deriva a lista de ADRs aceitas de `docs/adr/` e cobra de cada uma uma
      citação aqui — nas duas formas que este arquivo usa, a prosa `ADR 0009` e o caminho
      `docs/adr/0009`. Nasceu vermelha com **catorze** contra o estado pré-conserto, dez delas as
      da implantação. Quatro coisas foram medidas e não deduzidas: o casamento em prosa tem de
      exigir o prefixo `ADR`, porque com quatro dígitos soltos as faltantes caem de 4 para 1 — os
      tokens nus de migração (`0002`, `0004`, `0005`) comem as ADRs de mesmo número, que é o
      `.priority` da ADR 0033; **reconhecer o caminho não é conveniência, é o que impede uma
      allowlist falsa** — a primeira versão lia só a prosa e isentava a ADR 0009 com um motivo bem
      escrito, sendo que a seção "Migração do runtime web" acima é sobre ela e aponta para o
      arquivo dela desde sempre, e allowlist onde bastava reconhecer a citação é sedimento
      (ADR 0029); a decisão de identidade parecia citada por duas menções que apontam para a
      ADR 0003 **do `biahflow-portal`**, e ganhou na Fase 1 a citação que lhe faltava; e a leitura
      do status é *fail-closed* — ADR sem linha de `**Status:**` conta como aceita, senão a `0021`,
      a `0022` e a `0023` sairiam do corpus em silêncio. Fica declarado sem guarda o `CLAUDE.md`: o
      índice canônico é este arquivo, e cobrar toda ADR lá o faria crescer sem limite.

**Pontas abertas da implantação, sem dono e sem prioridade** (seleção é gate humano):

- **Medir o `NUM_PROXIES`.** Aberto desde a ADR 0050, onde o valor `2` foi raciocínio e não
  medição, e repetido na ADR 0053, que o deixou "mais errado, de propósito" ao alongar a cadeia —
  trocar um palpite por outro não melhora nada. O sintoma de errar não é um erro: é todo mundo
  dividindo o mesmo balde de limite de taxa. O procedimento está no `hml-gcp.md`.
- **Restaurar de verdade contra o Neon.** A ADR 0044 abriu, a ADR 0048 entregou o **código** e a
  execução nunca foi registrada. Um backup restaurável só na intenção é o defeito que a ADR 0019
  existe para não repetir.
- **Ler o painel do Upstash.** O instrumento (`scripts/redis_rate.py`) veio na ADR 0048; a leitura
  real é a condição que a ADR 0045 escreveu para declarar a HML pronta.
- **A `run.app` alcançável fora da Cloudflare.** Risco aceito por escrito na ADR 0053: o Access
  protege o nome, não o serviço, e fechar isso exigiria mTLS ou túnel, que não se pagam em
  homologação.
- **A guarda que a ADR 0052 nomeou e deixou sem dono** para a família "variável que o compose
  declara e o Terraform não reproduz". O commit `372b52a` registrou as **oito** ocorrências e o que
  a guarda teria de comparar, e parou aí — que é exatamente a forma da ADR 0034: conserto à mão sem
  portão volta a divergir. *Retificado em 19/08/2026, com medição: **neste repositório ela não é
  construível hoje**, e não por falta de dono. O commit `9e2d61d` (13/08) apagou o
  `infra/terraform/ambientes/hml-portal/` inteiro, então a comparação não tem lado direito — o
  `docker-compose.homolog.yml` continua descrevendo `api`, `worker`, `beat`, `web`, `keycloak` e
  `caddy` do portal, e nenhum `.tf` os declara (as únicas ocorrências de `portal-api` e `keycloak`
  que restam em `infra/terraform/` são comentários de histórico). Uma guarda escrita aqui hoje
  nasceria **verde por vacuidade**, que é o defeito da ADR 0033 — a mesma razão pela qual esta
  ponta continua aberta em vez de ser apagada. Ela volta a ser possível quando o portal voltar, ou
  mora no repositório onde os dois lados coexistem.*

*Fechados, para não serem reabertos por leitura de ADR:* o `CLOUDFLARE_API_TOKEN` que a ADR 0053
deixou aberto foi fiado no commit `6b781ae` e o `infra-hml` de 19/08 passou em `main`; e o defeito 7
da ADR 0052 foi corrigido no commit `58a831a`, com regressão — está registrado na Fase 1. Ler as
ADRs sem o histórico dá os dois como pendentes.

## Ordem recomendada

1. Fase 1 para que dados e acesso sejam reais e seguros.
2. Fase 2 e 3 em paralelo, pois usam o mesmo modelo de projeto.
3. Fase 4 após as fontes e permissões estarem estabelecidas.
4. Fase 5 continuamente, com fechamento antes do lançamento externo.
5. Fase 6 pode andar junto da Fase 1/2, pois destrava a experiência de maior valor do
   cliente e depende sobretudo do snapshot ampliado no Biahflow.
6. Fase 7 depois da 6, e **um sinal por vez**: o funil primeiro, porque é onde se perde
   cliente cedo e barato; a satisfação só quando o time estiver respondendo ao primeiro.
7. A homologação na nuvem não entra nesta ordem, e é de propósito: como a Fase 5, ela é
   transversal e anda junto do que estiver sendo entregue. Hoje ela serve o CRM; para o portal do
   cliente, ela é o que precisa ser religado antes de a Fase 7 voltar a ter o que medir.
