# Roadmap — Portal Labs

Este documento acompanha o plano de entrega. Itens concluídos permanecem aqui para dar visibilidade ao que já existe; cada nova funcionalidade deve ter FDD, testes e atualização deste roadmap.

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
      `X-Portal-User` não existe mais. ADR 0010, FDD 007.)*
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
      espelhados do snapshot. *O texto da transcrição e as decisões extraídas dependem da
      ingestão de texto da Fase 4.*
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

- [x] **O que o Biahflow não conta ao portal.** *(ADR 0037, FDD 020, mais emenda na ADR 0003 de
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

- [x] **A citação sem data.** *(ADR 0038, FDD 021. Nona repetição do padrão, num documento de
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

**Aceite:** o cliente abre o portal e vê a jornada com "Você está aqui", clica numa fase e vê
objetivo e ROI, os entregáveis desbloqueados e os funcionários digitais — tudo vindo da API,
não de dados de demonstração. *E acha qualquer um deles pela lupa: `tests/e2e/search.spec.ts`
digita, clica e cai na aba, e sobe um documento com termo inédito para achá-lo **dentro** do
texto.*

## Fase 7 — Saber se o cliente engaja, e puxá-lo de volta (proposta)

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

- [ ] **Funil de onboarding medido.** *(RFC 001, FDD 020.)* Degraus de valor com carimbo de
      tempo por organização, e alerta de quem travou. A régua é o **time-to-first-value**: do
      ganho até a primeira aprovação e até o primeiro ROI visto — número que prediz retenção
      melhor que qualquer health de projeto. O dado já ocorre; falta registrar **quando**.
      Duas travas: instrumentar **degraus de valor, não vaidade** ("logou doze vezes" pode ser
      um cliente perdido procurando o que devia estar óbvio), e separar "travou no cliente" de
      "travou em nós". A IA vigia e escreve o sinal ao time; **não conversa**.
- [ ] **Canal de WhatsApp.** *(RFC 002, FDD 021.)* Aviso 1:1 por template ao lado do sino e do
      digest, no ponto de extensão que a ADR 0012 já descreve, com opt-in revogável como
      coluna da pessoa. **Nunca grupo**: a razão de existir de um grupo é conversa de muitos
      para muitos, que é justamente o que não se quer fora do portal — e o canal de menor
      atrito vence sempre, então pôr os dois para fazer o mesmo trabalho esvazia o eixo. O
      aviso leva o fato e um link que cai na coisa exata. Spoke, nunca hub.
- [ ] **Pesquisa de satisfação por evento.** *(FDD 022.)* **Segundo sinal — só depois que o
      laço do funil estiver fechado.** Uma pergunta no momento com significado (fase concluída,
      entregável aceito), não NPS de calendário, com teto de frequência por pessoa. A forma já
      existe: a ADR 0015 grava nota e comentário com GRANT de coluna, e a ADR 0030 lê o sinal
      **sem a pergunta do cliente**. Nota baixa vira alerta na hora; a IA lê o texto aberto e
      prioriza detratores. E a regressão que a ADR 0033 deixou de herança: **painel só nasce
      depois do escritor**.

**Fora do recorte, e registrado porque nenhuma feature resolve:** velocidade de resposta é
compromisso operacional, não código — o portal pode ser impecável, mas se o cliente perguntar
e o time levar seis horas onde o WhatsApp levaria seis minutos, ele volta para o WhatsApp. E
**sinal traz de volta, valor retém**: se ao voltar não houver algo que importa, nenhum alerta
salva.

## Ordem recomendada

1. Fase 1 para que dados e acesso sejam reais e seguros.
2. Fase 2 e 3 em paralelo, pois usam o mesmo modelo de projeto.
3. Fase 4 após as fontes e permissões estarem estabelecidas.
4. Fase 5 continuamente, com fechamento antes do lançamento externo.
5. Fase 6 pode andar junto da Fase 1/2, pois destrava a experiência de maior valor do
   cliente e depende sobretudo do snapshot ampliado no Biahflow.
6. Fase 7 depois da 6, e **um sinal por vez**: o funil primeiro, porque é onde se perde
   cliente cedo e barato; a satisfação só quando o time estiver respondendo ao primeiro.
