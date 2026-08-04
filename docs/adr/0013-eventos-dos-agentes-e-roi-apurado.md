# ADR 0013 — Eventos dos agentes: chave por projeto e ROI apurado

**Status:** Aceito — 04/08/2026

## Contexto

O aceite da Fase 3 diz: *"reenvio do mesmo evento não duplica resultado; o cliente vê a origem e
a premissa de todo indicador."* Nenhuma das duas metades existia.

A tabela `agent_event` estava lá desde a migração `0002`, com a restrição de idempotência pronta,
e `AgentEventRepository.ingest` implementado — **e não chamado de lugar nenhum**.
`POST /api/v1/agent-events` era uma fronteira de contrato: validava o corpo, exigia
`internal_admin` por OIDC e devolvia 202 sem gravar. Não havia tabela de investimento ou
valor-hora, nem cálculo, nem chave de API.

Enquanto isso a aba Resultados exibia três cards fixos — transações automatizadas, precisão do
fluxo e exceções tratadas — e `roiValue()` devolvia um percentual constante quando o projeto não
tinha ROI no snapshot. Eram os últimos números sem lastro na tela do cliente, sobreviventes das
duas fases que se propuseram a eliminá-los.

Quatro restrições vindas de decisões anteriores moldam a solução:

1. **O portal não origina status** (ADR 0006/0008). Mas evento de agente **não é status**: ele
   não descreve o projeto, descreve uma execução. Não vem do Biahflow porque o Biahflow não o
   tem — quem o tem é o agente. Esta é a primeira coisa que o portal recebe de fora do snapshot,
   e é por isso que precisa de porta própria.
2. **Privilégio mora na credencial** (ADR 0010/0011). Até aqui `portal_app` escrevia apenas
   `pending_item`, `audit_log` e a própria linha de `user`.
3. **Toda tabela com `organization_id` sai com policy na mesma migração**, e um meta-teste quebra
   o CI se não sair.
4. **Negação é 404, nunca 403.**

## Decisão

### 1. O tenant é propriedade da chave, não do corpo

Uma chave (`agent_api_key`) pertence a **um projeto**. Isso resolve o problema central da rota: é
a única da API que recebe um identificador de projeto vindo de fora e precisa gravar com ele. Com
o tenant na credencial, o `projectId` do corpo deixa de ser uma entrada confiável e vira uma
conferência — discordar é 404.

A alternativa era manter OIDC e exigir `internal_admin`, como estava. Ela não sobrevive ao uso
real: um agente não tem sessão de usuário, e dar a ele o token de uma pessoa significa que a
credencial de um administrador passa a circular em processo automatizado. A rota passa a ser
**exclusivamente por chave** — um Bearer humano aqui é 401.

Header próprio, `X-Agent-Key`, e não `Authorization: Bearer`: segue o precedente do
`X-Biahflow-Signature` e evita dois esquemas disputando o mesmo campo, onde um Bearer humano
seria *tentado* como chave antes de falhar. Não entra no `allow_headers` do CORS — é conversa
servidor-a-servidor, e alargar o CORS convidaria o navegador a carregar a chave.

**Armazenamento:** só o prefixo em claro (12 caracteres, para o lookup ser O(1)); o segredo vira
HMAC-SHA256 sob um pepper de servidor (`AGENT_KEY_PEPPER`). HMAC e não bcrypt/argon2 porque isto
roda a cada evento ingerido — um KDF lento aqui seria um limitador de vazão autoinfligido. O que
um KDF lento defende é segredo de baixa entropia, e não é o caso: a chave são 32 bytes de
`secrets.token_urlsafe`. O que precisamos é que o conteúdo do banco, sozinho, não valha nada, e é
o que o pepper dá. Pepper vazio significa que **nenhuma chave autentica** — falha fechada, para
um ambiente mal configurado não abrir a rota com hash previsível.

### 2. Duas transações, dois papéis

A resolução da chave roda sob `portal_system`: a busca acontece **antes** de haver tenant para
ligar, porque é dela que o tenant sai. Na mesma transação ficam `last_used_at` e o contador da
janela — é o único caminho de escrita nessa tabela no request path.

A gravação do evento roda depois, sob `portal_app`, com `bind_tenant` já publicado. `agent_event`
ganha `GRANT INSERT` e uma policy `WITH CHECK` no tenant.

A alternativa — gravar tudo sob `portal_system`, como faz o webhook do Biahflow — seria mais
simples e pior. O webhook roda sob BYPASSRLS porque *cria* o tenant e não tem contexto para
ligar; aqui o tenant já é conhecido antes da primeira consulta. Abrir mão da RLS justamente na
rota que recebe identificador de fora é o oposto do que ela existe para fazer.

`agent_api_key` não concede nada a `portal_app`: o caminho de requisição do cliente não tem por
que enxergar credencial. Suas policies são `TO portal_admin`, pelo motivo escrito na ADR 0011 —
a policy não se aplica ao papel de requisição, então um `set_config` perdido lá não alcança nada.

### 3. Rate limit em Postgres, na própria linha da chave

Janela deslizante de um minuto em `window_started_at`/`window_count`. Redis está no compose, mas
a API sobe hoje sem broker — `queue_*` engole um broker morto de propósito — e trazer uma
dependência dura nova para o caminho de requisição custaria mais do que a precisão que compraria.
Sob concorrência alta o contador subconta; é um limite de abuso, não um contador de faturamento.

Estourar responde **429 com `Retry-After`**, e é a única recusa que não é 401. As demais —
inexistente, revogada, expirada, sem escopo — são o **mesmo 401 opaco**, com o motivo só no log
estruturado: "esta chave existiu e expirou" é informação para quem sonda. Ritmo é diferente, e o
produtor precisa saber, senão retenta para sempre.

### 4. Premissa financeira tem vigência, e o banco garante

`project_financial_assumption` guarda valor-hora e investimento mensal em linhas com
`[effective_from, effective_to)`. Um `EXCLUDE USING gist` impede que duas vigências do mesmo
projeto se cruzem, o que faz "qual era a premissa naquele dia" ter exatamente uma resposta.

Premissa **não se edita no lugar**. Trocar o valor-hora fecha a linha corrente e abre outra, na
mesma transação. A alternativa — colunas em `project`, atualizadas — reescreveria o passado: um
aumento hoje reprecificaria março, e um indicador que o cliente viu na semana passada mudaria
sozinho. A vigência é o que torna "premissa auditável" uma propriedade da tabela em vez de uma
promessa.

### 5. Nada é derivado na escrita

O evento guarda o que o agente reportou, em inteiros — `time_saved_seconds`, `avoided_cost_cents`
— e não decimais já convertidos. O evento armazenado tem de ser igual ao reportado, senão a
auditoria do número não fecha. As colunas `hours_saved`/`value_amount` da fatia original ficam
sem uso: migração é aditiva (AGENTS.md #4), e a remoção é item da Fase 5.

O dinheiro nasce na leitura (`results.py`), aplicando a premissa vigente **no dia do evento**.
As premissas do cálculo, todas declaradas na resposta:

- benefício = Σ(segundos ÷ 3600 × valor-hora vigente) + Σ(custo evitado);
- investimento = investimento mensal **rateado por dia**, com mês comercial de 30 dias. Comparar
  benefício de 30 dias com investimento de projeto inteiro produziria um ROI fictício;
- `ROI = (benefício − investimento) ÷ investimento`, e **nulo com investimento zero**. Dividir por
  zero para exibir "infinito" seria inventar resultado; a lacuna vai em `gaps` e a tela mostra um
  travessão com o motivo.

### 6. O evento carrega desfecho

`outcome` (`success` | `exception_handled` | `failed`) e `human_intervention`. Sem isso não há
como dar fonte a "precisão do fluxo" nem a "exceções tratadas", e os dois cards teriam de sair da
tela. Exceção tratada conta como acerto na precisão: o fluxo encontrou algo para o qual não foi
desenhado e resolveu — contá-la como falha subestimaria a precisão, e como sucesso puro esconderia
justamente o que o cliente acompanha.

### 7. Os dois ROIs convivem, rotulados

`project.roi_net`/`roi_ratio` continuam sendo o ROI **projetado**, espelhado do snapshot do
Biahflow. O apurado é outro número, com outra origem. Eles aparecem lado a lado e nomeados.

Fundir os dois num card só, trocando de fonte conforme houvesse eventos, faria o mesmo rótulo
significar duas coisas em momentos diferentes — e o cliente não teria como perceber a troca.
Mostrar só o apurado descartaria a promessa que o time assumiu no início do projeto, que é
exatamente contra o que o resultado deve ser lido.

## Consequências

- **A rota mudou de autenticação.** Três testes de `test_authorization.py` foram reescritos: a
  propriedade que protegiam — ninguém publica evento em projeto alheio — passa a ser provada por
  chave. Qualquer produtor que usasse Bearer para publicar precisa emitir uma chave.
- **`portal_app` escreve numa quarta tabela.** A lista da ADR 0010 cresce, e a policy `WITH CHECK`
  é o que a mantém honesta.
- **`AGENT_KEY_PEPPER` é um segredo de produção.** Trocá-lo invalida todas as chaves emitidas de
  uma vez; é rotação em massa, não configuração de rotina.
- **`btree_gist` vira dependência do schema.** Está na `pgvector/pgvector:pg16` do compose; um
  Postgres gerenciado precisa da extensão habilitada.
- **O cálculo não é materializado.** Cada leitura do dashboard agrega os eventos do período. Com
  volume alto isso pede uma tabela de agregado por dia — que é a evolução natural, e que só faz
  sentido depois de haver volume para justificar.
- **A tela de administração ganhou uma segunda página.** `/admin` é acesso, `/admin/resultados` é
  apuração; as duas sob `portal_admin`, no mesmo `admin.py`.

## Alternativas consideradas

**Assinatura HMAC do corpo, como o webhook do Biahflow.** Prova integridade do payload além da
identidade, e é melhor onde o segredo é único e global. Aqui a chave é por projeto e precisa de
escopo, expiração e rotação individuais — o que a assinatura acrescentaria (integridade do corpo)
já vem do TLS, e o que ela não resolve (qual projeto, revogar só esta) é o problema real.

**Chave por organização em vez de por projeto.** Menos chaves para administrar, e o `projectId` do
corpo voltaria a ser uma entrada confiável — exatamente o que não queremos. Uma chave vazada
alcançaria todos os projetos do cliente.

**Materializar horas e valor no evento, na ingestão.** Simplifica a leitura e destrói a auditoria:
o número gravado passaria a depender da premissa vigente no instante da entrega do webhook, e uma
reentrega tardia gravaria valor diferente para o mesmo fato.
