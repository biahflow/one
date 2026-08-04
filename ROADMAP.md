# Roadmap — Portal Labs

Este documento acompanha o plano de entrega. Itens concluídos permanecem aqui para dar visibilidade ao que já existe; cada nova funcionalidade deve ter FDD, testes e atualização deste roadmap.

## Concluído — Fundação local

- [x] Interface responsiva do dashboard e chat demonstrável.
- [x] Docker Compose com web, API, worker, PostgreSQL + pgvector, Redis, MinIO, Keycloak e Mailpit.
- [x] Documentação de produto, arquitetura, segurança, IA, ADRs, RFCs, FDDs e runbooks.
- [x] Contratos iniciais de API para dashboard, chat e eventos de agentes.
- [x] Pirâmide inicial: testes web renderizados, testes de API, lint e CI com build Docker, dependency review e CodeQL.

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
tentativas de acesso cruzado falham na API, no banco e na busca. *Atendido para API e banco
(`test_authorization.py`, `test_rls_isolation.py`, e o e2e de login em `tests/e2e/`); a busca
ainda não existe — chega com o RAG da Fase 4, e o filtro por organização/projeto é requisito
dela.*

## Fase 2 — Jornada do projeto

- [x] ~~Implementar CRUD interno de status, entregas, cronograma, decisões e documentos.~~
      **Superado pela ADR 0006:** o Biahflow é a fonte da verdade e o portal nunca origina
      status. A digitação continua só no Biahflow e chega aqui por snapshot/webhook — um CRUD
      no portal dividiria a fonte da verdade. Ver também `docs/adr/0008`.
- [x] Implementar pendências com responsável, estados e histórico (abertas/resolvidas), com
      distinção de origem: espelhadas do Biahflow vs. abertas pela IA por lacuna de contexto,
      que sobrevivem ao sync (`PendingItem.origin`, migração `0006_portal_sync_fields`).
      *Prioridade, comentários e vínculo a conversas seguem pendentes.*
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
      `GET /api/v1/me/dashboard` no lugar dos dados de demonstração. *Filtros seguem pendentes.*

**Aceite:** equipe interna atualiza o projeto **no Biahflow**; o cliente acompanha as alterações
no portal em quase tempo real — e é avisado delas, no sino e por e-mail, sem precisar abrir o
portal para descobrir. *Atendido: `tests/e2e/notifications.spec.ts` sincroniza um marco
concluído, confere o sino no navegador e lê o resumo na caixa do Mailpit.*

## Fase 3 — Resultados e API dos agentes

- [ ] Autenticar a API de eventos com chave por projeto, hash, escopo, expiração, rotação e rate limiting.
- [ ] Persistir eventos idempotentes e configurar investimento/valor-hora com vigência — **e a
      tela para mantê-la**, que veio do item de administração da Fase 1: o número financeiro só
      faz sentido junto do cálculo de ROI que vive aqui.
- [ ] Calcular horas poupadas, custos evitados e ROI líquido por período, com premissas auditáveis.
- [ ] Criar relatórios e detalhamento que expliquem cada valor exibido no dashboard.
- [ ] Dar fonte real aos três cards ainda de demonstração na aba Resultados — transações
      automatizadas, precisão do fluxo e exceções tratadas (marcados no código em
      `app/DashboardClient.tsx`). São os únicos números sem lastro na tela do cliente.

**Aceite:** reenvio do mesmo evento não duplica resultado; o cliente vê a origem e a premissa de todo indicador.

## Fase 4 — Conhecimento e IA contextual

- [ ] Implementar conector Google Drive OAuth somente leitura, uma pasta permitida por projeto e sincronização idempotente.
- [ ] Armazenar arquivos no MinIO/S3, validar upload, extrair texto e manter metadados de fonte, página e data.
- [ ] Implementar chunking, embeddings, `pgvector` e recuperação estritamente filtrada por organização/projeto.
- [ ] Conectar o provedor de IA por adaptador, prompts versionados e saídas estruturadas validadas.
- [ ] Persistir conversas, citações, feedback e pendências geradas por lacuna de contexto.
- [ ] Criar dataset de avaliação e bloquear regressão em citações, isolamento, lacunas e prompt injection.

**Aceite:** perguntas sobre produção, decisões financeiras e pendências retornam fontes corretas; falta de evidência cria uma pendência, sem resposta inventada.

## Fase 5 — Segurança e produção

- [ ] Implementar antivírus/validação assíncrona de documentos, URLs temporárias e política de retenção/exclusão por organização.
- [ ] Adicionar backup/restore testado para PostgreSQL e MinIO, alertas e telemetria com `trace_id`.
- [ ] Cobrir testes de integração com serviços reais, contratos OpenAPI, Playwright E2E, carga e cenários adversariais de IA.
- [ ] Definir ambiente de homologação, variáveis/segredos de produção, domínio, TLS, observabilidade e plano de incidentes.
- [ ] Revisar dependências vulneráveis apontadas pelo `npm audit` antes de produção.

**Aceite:** pipeline bloqueia regressões de qualidade e segurança; backups são restauráveis e incidentes seguem runbook testado.

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

**Aceite:** o cliente abre o portal e vê a jornada com "Você está aqui", clica numa fase e vê
objetivo e ROI, os entregáveis desbloqueados e os funcionários digitais — tudo vindo da API,
não de dados de demonstração.

## Ordem recomendada

1. Fase 1 para que dados e acesso sejam reais e seguros.
2. Fase 2 e 3 em paralelo, pois usam o mesmo modelo de projeto.
3. Fase 4 após as fontes e permissões estarem estabelecidas.
4. Fase 5 continuamente, com fechamento antes do lançamento externo.
5. Fase 6 pode andar junto da Fase 1/2, pois destrava a experiência de maior valor do
   cliente e depende sobretudo do snapshot ampliado no Biahflow.
