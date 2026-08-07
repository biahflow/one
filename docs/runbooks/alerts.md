# Runbook — Alertas

O que deve acordar alguém, com que limiar, e para onde ir depois. Cada linha é um
**evento nomeado** do log estruturado (ADR 0018), então a regra é sempre a mesma
consulta: filtrar por `event` e contar dentro de uma janela.

Não há Prometheus nem exporter neste repositório — métrica e coletor pertencem ao
item de homologação do `ROADMAP.md`, que é quando existirá para onde mandá-las.
Até lá o substrato é o log JSON no stdout de cada serviço, que qualquer coletor
(Loki, CloudWatch, Datadog) ingere sem código nosso.

## Acordam alguém

| Evento | Limiar | O que significa | Runbook |
|---|---|---|---|
| `document.infected` | qualquer ocorrência | Um arquivo com malware chegou ao portal. O objeto já foi destruído e a linha preservada — o alerta é para **avisar o tenant**, não para conter. | `document-ingestion-failure.md`, `incident-response.md` |
| `document.infected_object_kept` | qualquer ocorrência | O caso estritamente pior que o de cima, e **até a ADR 0034 ele era anônimo**: o malware foi confirmado e o objeto **não saiu do bucket** (o storage recusou o `DELETE`). A linha já diz `rejected` e nenhuma rota alcança o arquivo, mas ele está lá. `extra` traz `storage_key`; conter é apagar à mão. | `document-ingestion-failure.md`, `incident-response.md` |
| `http.failed` | qualquer ocorrência | Uma exceção atravessou a API inteira — o cliente recebeu 500. `extra` traz `method`, `route` (template, nunca o path) e `duration_ms`, e o `trace_id` leva ao resto da história. Não tinha linha aqui até a ADR 0034, o que fazia do 500 o único desfecho do produto sem limiar escrito. | `incident-response.md` |
| `web.request_error` | qualquer ocorrência | O irmão do `http.failed` **no BFF**: uma exceção atravessou o Next e o cliente viu a fronteira de erro. `digest` é o "Código" que aparece na tela para a pessoa, e é por ele que se casa a reclamação com a linha; `route` é o template, nunca o path. *Emitido desde a ADR 0018 e sem linha em runbook nenhum até a ADR 0035 — a guarda bidirecional de eventos parava na fronteira do pacote Python, então os quatro eventos do BFF eram invisíveis para ela.* | `incident-response.md` |
| `api.failed` | 3 em 5 min | O SSR do dashboard não conseguiu montar a página: a API respondeu status de erro e o BFF lançou. É a tela de erro do cliente, e o par com `http.failed` do outro lado — se os dois sobem juntos, a causa é a API; se só este sobe, olhe rede e credencial entre os dois contêineres. `extra` traz `url` e `status`. | `incident-response.md`, `auth-failure.md` |
| `api.rejected` | 10 em 5 min | A API recusou uma chamada do BFF (4xx) num caminho que **degrada em silêncio** — o sino que não marca como lido, o painel que volta vazio. Uma ocorrência é rotina (404 é a negação normal, ADR 0010); a taxa é que denuncia sessão expirando em massa ou rota mudada sem o BFF saber. `extra` traz `path` e `status`. | `auth-failure.md` |
| `api.unreachable` | 3 em 5 min | O BFF não alcançou a API: rede caída, contêiner fora, DNS. Distinto do `api.rejected` de propósito — lá alguém respondeu, aqui ninguém atendeu —, e é a metade do par que o `health.database_unavailable` não cobre, porque este vê a falha **de fora** do processo. `extra` traz `path` e `message`. | `incident-response.md` |
| `health.broker_unavailable` | 2 em 5 min | O `/health/ready` perdeu o Redis. Irmão exato do `health.database_unavailable` abaixo, e **faltava** — a assimetria era o defeito: o mesmo endpoint, o mesmo 503, e só metade dele acordava alguém. Sem broker a fila não anda: digest, indexação e sync do Drive param, e as notificações ficam no sino (`queue.unavailable`). | `drive-sync-failure.md` |
| `erasure.failed` / `erasure.storage_failed` | qualquer ocorrência | Um apagamento pedido não foi cumprido. É obrigação contratual e o pedido fica `failed` no banco, visível — mas ninguém olha uma tabela sem motivo. O pedido **não** é retentado sozinho: quem decide tentar de novo é uma pessoa, em `/admin/organizacao`, e um `failed` já libera pedido novo. *`erasure.failed` só passou a ser emitido na ADR 0028 — até então a metade do banco de `_run_erasure` não tinha `except` nenhum, e uma falha ali deixava o pedido em `running` para sempre, sem evento e sem retentativa.* | `incident-response.md` |
| `health.database_unavailable` | 2 em 5 min | O caminho de requisição perdeu o Postgres. O `/health/ready` já está em 503 e o compose/orquestrador já tirou a réplica do balanceamento. | `auth-failure.md` (a RLS sem contexto devolve zero linhas, que **se parece** com isto) |
| ausência de `task.started` com `root=beat` | 2× `RETENTION_INTERVAL_SECONDS` | O agendador parou. É alerta **por ausência** porque o `beat` não tem healthcheck: com tick de 15 min a 24 h, nenhuma sonda barata distingue "parado" de "entre ticks" (ver o comentário no `docker-compose.yml`). | `drive-sync-failure.md` |
| ausência de backup bem-sucedido | 26 h | Também **por ausência**, e pela razão contrária à do `beat`: o backup não roda no `beat` (é operação, não aplicação — ADR 0019), então nada dentro do portal sabe que ele deveria ter rodado. 26 h e não 24 para um backup diário atrasado não acordar ninguém. | `backup-restore.md` |
| `backup.objects.rejected` | qualquer ocorrência | Objetos cujo SHA-256 não bateu num restore. O restore inteiro foi recusado — o alerta é porque o backup em que se confiava está corrompido, e o próximo restore precisa de outro. | `backup-restore.md` |

## Avisam, sem acordar

| Evento | Limiar | O que significa | Runbook |
|---|---|---|---|
| `drive.sync_failed` com `disable=true` | qualquer ocorrência | O Google recusou a credencial e a pasta foi **pausada**, não apagada. O índice continua servindo o chat; alguém precisa reconsentir. | `drive-sync-failure.md` |
| `document.scan_unavailable` | 3 em 15 min | **O antivírus caiu.** É o sinal que a linha do `scan_state=skipped` lá embaixo mandava vigiar pelo caminho errado até a ADR 0034: com `CLAMAV_HOST` configurado o scanner nunca devolve `skipped`, ele devolve `error` e emite isto. Enquanto durar, nenhum documento novo entra no índice — a indexação recusa por conta própria o que não passou (ADR 0017). `extra` traz `host`, `port` e `detail`. | `document-ingestion-failure.md` |
| `authz.denied` | 20 em 5 min por `subject_prefix` | Um chamador **autenticado** pediu o que não é dele. Isolado é rotina — link velho, projeto que a pessoa deixou de acompanhar. Em volume por pessoa é enumeração, e é a primeira linha do `threat-model.md` acontecendo. `reason=not_a_member` é acesso cruzado; `reason=role_insufficient` é escalada **dentro** do próprio tenant, e leva a outra investigação. Este é o indicador que `observability.md` chamava de "anomalias de autorização" e que **não tinha emissor** até a ADR 0034. | `auth-failure.md`, `incident-response.md` |
| `keycloak.failed` | 5 em 1 h | O realm não respondeu ao service account de administração. Convite não sai e a lista de e-mails não verificados degrada para sem rótulo — a tela continua de pé. `extra` traz `what`, que diz qual chamada falhou. | `auth-failure.md` |
| `drive.scope_refused` | qualquer ocorrência | O Google concedeu um escopo diferente de `drive.readonly` e a conexão foi **recusada sem nada ser gravado**. É o controle "OAuth Drive excessivo" do `threat-model.md` funcionando — e uma tentativa de consentimento excessivo é exatamente o que alguém quer ver, não algo a somar em silêncio. | `drive-sync-failure.md` |
| `drive.listing_truncated` | 2 dias seguidos | A pasta tem mais arquivos do que o teto de uma varredura. **Não é erro e é pior que parece**: o índice fica incompleto e o chat responde igual, declarando lacuna por motivo errado. Repetido, quer dizer que o resto nunca alcança a fila. A tela mostra o mesmo em `/admin/conhecimento` (ADR 0033). | `drive-sync-failure.md` |
| `document.object_not_removed` / `drive.object_not_removed` | 5 em 1 h | Objeto órfão no storage: a linha saiu e o arquivo ficou. Não vaza — nenhuma rota o alcança sem a linha —, e a retenção o recolhe. Volume alto é o storage recusando escrita. *Até a ADR 0034 o primeiro era prosa interpolada, e o `document-ingestion-failure.md` mandava procurá-lo por substring.* | `document-ingestion-failure.md` |
| `document.storage_write_failed` / `document.signing_failed` / `drive.unavailable` / `storage.bucket_not_created` | 5 em 1 h | O storage ou o Google não responderam no caminho de requisição. O cliente vê erro na hora; o que interessa é a taxa. | `document-ingestion-failure.md` |
| `retention.purge_failed` | 2 dias seguidos | A poda de uma organização falha repetidamente. Uma falha isolada é recuperada no tick seguinte por construção. | `incident-response.md` |
| `queue.unavailable` | 5 em 5 min | O Redis está fora. Cada `queue.unavailable` é um trabalho que **não** se perdeu — a linha está comitada —, mas que só sai no próximo tick. Volume alto é indisponibilidade do broker. | — |
| `digest.send_failed` | 10 em 1 h | O SMTP está recusando. As notificações continuam no sino; só o e-mail atrasa (`emailed_at IS NULL` faz a retentativa sozinha). | — |
| `embedding.failed` | 5 em 1 h | O provedor de embeddings está fora. Documentos ficam `failed` e não entram no índice — o chat responde declarando a lacuna, que é o comportamento correto, mas por motivo errado. | `ai-provider-failure.md` |
| `agent_key.rate_limited` | 100 em 5 min por `key_prefix` | Um agente está retentando em loop. Ler o `key_prefix` para saber qual. | `agent-events-failure.md` |
| `chat.provider_unavailable` | 5 em 5 min | O provedor de resposta caiu e cada ocorrência é **um chat que perdeu o modelo em silêncio**: a pessoa recebeu resposta do respondedor offline sem nada na tela dizendo isso. Ler `reason` — `ProviderRefused` é o classificador recusando, e não indisponibilidade. | `ai-provider-failure.md` |
| `embedding.unavailable` | 10 em 1 h | O embedder de consulta caiu: o chat responde só pelo read model, sem trecho de documento. As respostas param de citar antes de qualquer coisa ficar vermelha. | `ai-provider-failure.md` |
| `chat.rate_limited` | 100 em 5 min por `subject_prefix` | Alguém (ou algum script com a sessão de alguém) está perguntando em loop. Uma ocorrência isolada é o controle funcionando — leia como o `agent_key.rate_limited`. | — |
| `ai_quota.exhausted` | qualquer ocorrência, por `organization_id` | O teto mensal de gasto de IA daquela organização acabou, e **o chat parou de responder para ela**. Ao contrário do `rate_limited`, uma ocorrência isolada já é um cliente sem assistente: ou o teto está baixo demais, ou houve consumo anômalo. `extra` traz `spent_cents` e `limit_cents`, que é o bastante para decidir sem abrir a tela — e o teto se muda em `/admin/organizacao` (ADR 0027), que até então **não existia**, embora esta linha já falasse dela. | `/admin/organizacao` |
| `ai_quota.price_missing` | qualquer ocorrência | Chamadas cujo modelo não tem preço vigente em `ai_model_price` — o gasto delas **não entra na soma**, e o mês parece mais barato do que foi. Quase sempre significa que alguém trocou `ANTHROPIC_MODEL` sem abrir a vigência. O turno não é recusado de propósito (o razão guarda tokens, então o custo é recalculável depois), mas o teto está cego enquanto isto durar. | `load-test.md` |
| `biahflow.project_deleted` | qualquer ocorrência | O Biahflow apagou o projeto **de vez** e avisou (ADR 0037). Não é falha: o portal marcou a linha, fechou as escritas com 409 e **manteve tudo o que já tinha** — o histórico é a evidência das citações já dadas. Uma ocorrência isolada merece olho porque exclusão não tem volta do outro lado: se foi engano, o read model daqui é a única cópia que sobrou. `extra` traz `biahflow_project_id`, `project_id` e `marked` — este último acima de 1 significa que o mesmo projeto do Biahflow existe em duas organizações daqui, o que só acontece se ele tiver mudado de cliente lá. Apagar de verdade continua sendo decisão de pessoa, em `/admin/organizacao`. | `integracao-biahflow.md` |
| `onboarding.client_stuck` | qualquer ocorrência, por `organization_id` | Um cliente parou num degrau do funil e passou do limiar (RFC 001 passo 3, ADR 0040). O caso que a fatia existe para tornar visível é "ganho há nove dias, convite enviado, nunca logou" — aos nove dias ainda se resolve com um telefonema; aos trinta virou churn. Sai **uma vez por organização e por degrau**, e não a cada passagem: a memória é o `dedupe_key` da notificação que acompanha o evento, não um contador. `extra` traz `step`, `days_stuck`, `blocked_by` e `threshold_days` — e é o `blocked_by` que diz para quem ligar, porque `us` significa que a espera é **nossa** e nenhum telefonema ao cliente resolve. A linha inteira está em `/admin/funil`. *Uma organização travada por mais que `retention_notification_days` (180) toca de novo, uma vez, quando a notificação antiga é podada: é limitado, e um cliente travado há meio ano merece o segundo olhar.* | `/admin/funil` |
| `contact.suppressed` | 10 em 1 dia, ou qualquer ocorrência por `organization_id` em 3 dias seguidos | O teto de frequência barrou um contato que sairia para uma pessoa (FDD 021, FDD 022, ADR 0042). **Uma ocorrência é o controle funcionando** e não se conserta — foi para isso que o teto existe. O que se lê é a taxa, e ela responde a duas perguntas diferentes: em volume, o teto está baixo demais para o ritmo real do produto; concentrado numa organização, alguma coisa está gerando contato demais para as mesmas pessoas, e aí o defeito é do produtor, não do teto. Nos dois casos o cliente **não** ficou sem saber: o que foi suprimido é o contato externo, nunca a linha no sino. `extra` traz `kind`, `reason` e `cap`, e **não** traz a pessoa — comportamento de pessoa identificada não vai para o log, a mesma regra do funil. O teto é `contact_cap_per_window` (três por semana); *a entrada correspondente no compose chega junto do primeiro remetente, na FDD 021 — até lá nenhum caminho em execução gasta orçamento, e esta linha existe porque o emissor existe, não porque ele já toca.* | — |
| `onboarding.alert_undeliverable` | 2 dias seguidos | A organização está travada e **não há ninguém interno a quem avisar** — nenhum `internal_admin` nem `internal_member` com vínculo nela. Sem esta linha o caso sumiria: sem destinatário, o `fan_out` devolve vazio e o alerta acima não sai, de modo que o tenant ficaria travado em silêncio absoluto. Ao contrário do anterior, repete a cada passagem de propósito: é defeito de configuração, não sinal de cliente. O conserto é `python -m portal_api.grant_access` (ADR 0025). | `integracao-biahflow.md` |
| `onboarding.stuck_scan_failed` | 2 dias seguidos | A varredura do funil falhou para uma organização. Uma falha isolada é recuperada no tick seguinte por construção, como no `retention.purge_failed` — o laço é o mesmo, com uma transação por organização. | `incident-response.md` |
| `biahflow.snapshot_missing` | 5 em 1 h | O Biahflow avisou de um projeto e depois respondeu **404** quando o portal foi buscar o estado dele. `extra` traz `biahflow_project_id`. Não há o que reconciliar, e o read model daquele projeto fica parado no que já tinha — que é o ponto: repetido, é um projeto do cliente divergindo em silêncio. Quase sempre é `BIAHFLOW_BASE_URL` apontando para outra base (ids não batem entre instâncias). *Até a ADR 0036 isto era um 500 com traceback anônimo, e a causa comum era outra: arquivar um projeto lá o tirava do snapshot, e o portal não tinha como distinguir "acabou" de "nunca existiu".* | `integracao-biahflow.md` |

## Não são alerta

São o controle **funcionando**, e tratá-los como incidente ensina a equipe a
ignorar o painel:

- `auth.rejected` — token expirado é o caso comum de qualquer sessão. Só vira
  sinal como **taxa**: um salto sustentado de `reason=signature` ou
  `reason=issuer` é sondagem, e aí o runbook é `auth-failure.md`. Um pico de
  `reason=expired` logo depois de um deploy do Keycloak é rotina.
- `drive.file_outside_authorized_folder` e `drive.shortcut_skipped` — é a fronteira
  barrando o que deve barrar, como diz `observability.md`. *Corrigido em 06/08/2026
  (ADR 0028): esta linha dizia `drive.rejected`, que o código **nunca emitiu**. O
  primeiro caso sempre teve evento com outro nome; o segundo não tinha nenhum —
  o atalho só incrementava um contador, então metade da fronteira que a ADR 0016
  confere duas vezes passava por "nada aconteceu".*
- `document.scan_state=skipped` — é "ninguém varreu", e é o estado normal da
  stack local e do CI, que não têm ClamAV. A ADR 0017 é explícita em que
  `skipped` nunca equivale a `clean`. *Corrigido em 06/08/2026 (ADR 0034): esta
  linha dizia que **"em produção com `CLAMAV_HOST` configurado, `skipped`
  sustentado é alerta"**, e isso é impossível — `get_scanner` só devolve o
  `OfflineScanner` quando `CLAMAV_HOST` está **vazio**, e o `ClamavScanner`
  responde `clean`, `infected` ou `error`, nunca `skipped`. Quem seguisse a
  instrução vigiava um contador pinado em zero enquanto o antivírus caía. O
  sinal certo é `document.scan_unavailable`, que agora tem linha acima, e o
  estado certo na linha do documento é `scan_state=error`.*
- `document.scan_state=error` **isolado** — o clamd recusou aquele arquivo
  específico (o caso comum é `INSTREAM size limit exceeded`, arquivo maior que o
  `StreamMaxLength` do daemon). O documento não entra no índice, e a tela de
  `/admin/conhecimento` diz por quê. É o controle funcionando; o que alerta é a
  **taxa**, e aí o evento a ler é `document.scan_unavailable`.
- `agent_key.rejected` — credencial de agente recusada: chave revogada,
  expirada, ou de outro projeto. Isolado é rotina de rotação. Como taxa é
  sondagem, e aí o `key_prefix` diz qual chave (`agent-events-failure.md`).
- `onboarding.step_reached` — um degrau do funil foi alcançado pela **primeira** vez
  (RFC 001). É um fato bom, não um chamado: quem precisa agir é quem olha o cliente
  **travado**, e esse é o `onboarding.client_stuck` da tabela acima. Sai uma vez por
  organização e por degrau, nunca a cada download ou pergunta, e não carrega conteúdo:
  só o tenant e o nome do degrau.
  *Corrigido em 07/08/2026 (ADR 0040): esta linha dizia que o alerta de cliente
  travado "não existe ainda, de propósito, porque esta fatia carimba sem expor". Era
  verdade enquanto só o passo 1 da RFC 001 estava de pé; o passo 3 chegou, e a frase
  passou a mandar procurar por um alerta que existe.*
- `onboarding.stamp_failed` — o carimbo do funil falhou e a requisição **seguiu normal**,
  que é a decisão declarada na ADR 0039: medir engajamento não pode derrubar o download ou
  o dashboard do cliente. Isolado é ruído de indisponibilidade momentânea do banco. Como
  **taxa** vira sinal de que o funil parou de encher — e ninguém repara na falta de uma
  linha, por isso o evento sai com traceback.
- `preflight.refused` — o processo **não subiu**, de propósito (ADR 0022). Não
  precisa de alerta próprio porque o alerta é o serviço não existir; a linha diz
  qual setting está com valor de exemplo.
- `drive.account_email_unavailable` — o Google não devolveu o e-mail da conta
  conectada. A pasta sincroniza igual; só o rótulo da tela fica sem o endereço.
- `document.page_unreadable` — uma página de PDF sem texto extraível (só imagem,
  fonte exótica). O documento é indexado pelo que dá para ler, que é o desenho.
- `digest.email_disabled` — não há SMTP configurado. É o estado normal de quem
  roda sem Mailpit; as notificações continuam no sino.
- `backup.objects.dumped` / `backup.objects.restored` — curso normal da
  operação. O que alerta é a **ausência** de backup (26 h, acima) e o
  `backup.objects.rejected`.

## Como consultar

O log é uma linha JSON por evento, com `trace_id` em todas:

```bash
docker compose logs api   | grep '"event":"auth.rejected"' | tail -20
docker compose logs worker | grep '"event":"queue.unavailable"'
```

Para seguir uma requisição inteira — web, API e as tasks que ela disparou:

```bash
docker compose logs | grep '"trace_id":"<id>"'
```

E para chegar ao `trace_id` a partir de uma ação registrada:

```sql
SELECT action, created_at, data->>'trace_id' FROM portal.audit_log
 WHERE entity_id = '<id>' ORDER BY created_at DESC;
```
