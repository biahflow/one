# FDD — Telemetria, `trace_id` e alertas

Fase 5, ADR 0018.

## Objetivo e não objetivos

**Objetivo.** Que uma requisição do portal possa ser reconstruída ponta a ponta por
um identificador só — navegador, BFF, FastAPI, Celery e a linha de `audit_log` que
ela produziu —, e que os eventos que merecem acordar alguém tenham nome estável,
campo legível e limiar escrito.

**Não objetivos.** Métrica, exportador e painel: pertencem ao item de homologação
do roadmap, que é quando existirá para onde mandá-los. Tracing distribuído com
spans e amostragem: o `trace_id` num contextvar é o que um `SpanProcessor`
consumiria depois, e adotar OTel agora exigiria escolher coletor antes de haver
ambiente. Backup/restore, que é a outra metade da linha do roadmap e segue aberta.

## Jornada e interface

Só uma superfície muda para o cliente: quando o portal falha, a tela passa a
mostrar um **Código** (o `digest` do Next) além da frase "A falha foi registrada" —
que até aqui era falsa. É o que a pessoa repete ao suporte, e é por onde quem
atende encontra a linha `web.request_error` e, por ela, o `trace_id` da requisição
inteira.

Para a equipe interna, a jornada é o runbook: `docs/runbooks/alerts.md` diz o que é
alerta e o que é o controle funcionando, e `incident-response.md` diz como seguir
um `trace_id` nas duas direções.

## Dados, API e permissões

- **Sem migração.** `audit_log.data` já é JSONB; o `trace_id` entra ali por
  `telemetry.audit_data()`.
- `GET /health/ready` — **pública**, como `/health`. Toca Postgres e Redis; 200
  `{"status":"ready"}` ou 503 `{"status":"down"}` e mais nada.
- Nenhum endpoint de cliente muda de contrato. `X-Request-ID` é aceito e ecoado em
  todas as respostas, e já estava na allowlist de CORS antes de existir quem o
  lesse.
- Nenhum papel novo, nenhuma policy nova, nenhum GRANT novo.

## Estados de erro e segurança

- **Segredo não entra no log.** O formatter redige por nome de campo (`token`,
  `secret`, `password`, `authorization`, `cookie`, `key`), com `key_prefix` numa
  allowlist obrigatória — é a parte pública da credencial e é dela que o runbook de
  eventos depende. Regra 5 do `AGENTS.md` cumprida pelo código.
- **Identificador de tenant não vira URL no log.** O log de acesso guarda o
  *template* da rota (`/api/v1/projects/{project_id}/results`), nunca o path
  resolvido nem a query string. Um caminho que não casou com rota nenhuma vira
  `unmatched`, porque nesse caso a string é escolhida por quem chama.
- **A prontidão não é um mapa da infraestrutura.** Sem versão, hostname, DSN ou o
  nome da dependência que caiu: um `down` é indistinguível de outro, como o 401
  opaco da `auth.py`. O motivo vai para o log.
- **O `trace_id` não é credencial.** Ele identifica uma requisição, não autoriza
  nada, e por isso pode ser ecoado ao cliente e citado ao suporte.
- Falha do próprio logging nunca derruba a requisição: o `json.dumps` usa
  `default=str`, porque um log que estoura ao serializar um UUID é pior que um log
  impreciso.

## Telemetria e critérios de aceite

Eventos nomeados, todos com `trace_id`:

| Evento | Onde | Campos |
|---|---|---|
| `http.request` / `http.failed` | API, todo request | `method`, `route`, `status`, `duration_ms` |
| `task.started` / `task.finished` | worker, toda task | `task`, `root` (`beat`/`request`), `status` |
| `document.infected` | worker, varredura | `document_id`, `organization_id`, `project_id`, `signature` |
| `drive.sync_failed` | worker, sync | `connection_id`, `project_id`, `disable`, `reason` |
| `queue.unavailable` | API e worker | `task` e o id do trabalho perdido |
| `retention.purge_failed`, `erasure.storage_failed`, `digest.send_failed`, `embedding.failed` | worker | o id da organização/usuário/documento |
| `web.request_error` | BFF | `digest`, `trace_id`, `route`, `render_source` |
| `api.failed`, `api.rejected`, `api.unreachable` | BFF | `trace_id`, `url`/`path`, `status` |
| `health.database_unavailable`, `health.broker_unavailable` | API | exceção |

Os já existentes (`auth.rejected`, `agent_key.rejected`, `agent_key.rate_limited`,
`keycloak.failed`, `identity.linked`, `identity.provisioned`) passam a **imprimir
os campos que já carregavam**.

**Aceite.** Subir a pilha, fazer uma pergunta no chat ou subir um documento, pegar
o `trace_id` da linha do `web` e encontrar o mesmo id no log do `api`, no do
`worker` e em `audit_log.data->>'trace_id'`.

**Acrescentado em 06/08/2026 (ADR 0034), e os três primeiros nasceram vermelhos.**
A tabela acima descrevia o que a ADR 0018 entregou; o que faltava era a garantia de
que ela continuasse verdadeira — e ela não continuou. A ADR 0028 já havia corrigido
o `alerts.md` à mão (ele citava `drive.rejected`, que o código nunca emitiu), o
conserto não deixou guarda, e em dois dias o arquivo divergiu de novo pelo outro
lado: doze eventos emitidos que nenhum runbook conhecia.

| Evento | Onde | Campos |
|---|---|---|
| `authz.denied` | API, `access.py` | `reason` (`not_a_member`/`role_insufficient`), `subject_prefix`, `project_id`/`organization_id` |
| `document.scan_unavailable` | worker, varredura | `host`, `port`, `detail` |
| `document.object_not_removed`, `document.storage_write_failed`, `document.signing_failed`, `document.page_unreadable` | API e worker | a chave ou o id do documento |
| `drive.unavailable`, `storage.bucket_not_created`, `digest.email_disabled` | API e worker | o detalhe da falha |

11. **Todo `logger.*` do pacote usa nome estável** (`familia.acontecimento`), com o
    detalhe em `extra`. Não é estilo: o `JsonFormatter` põe a mensagem **já
    interpolada** em `event`, então prosa com `%s` produz um valor por ocorrência e
    o limiar do `alerts.md` deixa de ser aplicável. A exceção são os comandos de
    operação, cujo leitor é uma pessoa no terminal.
12. **Todo evento emitido tem linha no `alerts.md`**, ou linha em `NOT_AN_ALERT`
    dizendo por que ninguém precisa ser avisado.
13. **Todo evento que o `alerts.md` nomeia é emitido** — o defeito da ADR 0028,
    agora verificado. A guarda ignora as notas históricas (`*Corrigido em …*`), senão
    cobraria que o repositório apagasse o registro do próprio erro.
14. **A negação de autorização deixa rastro contável por pessoa, e continua opaca
    para quem chamou** — as duas metades, porque distinguir "não é seu" de "não
    existe" na resposta criaria o oráculo que a ADR 0010 evita.

## Testes e avaliações de IA

- `apps/api/tests/test_telemetry.py` (unitário, sem banco): os campos de `extra`
  chegam à linha — que é a **regressão** que motivou a fatia —, o segredo é
  redigido e o `key_prefix` sobrevive, o header é honrado e ecoado, duas
  requisições não compartilham id, o log de acesso guarda a rota e não a URL, um
  path não casado nunca é ecoado, o id atravessa a fila como header de mensagem, e
  uma publicação fora de requisição não carimba nada. **Desde a ADR 0034 ele
  carrega também as três guardas que impedem a volta**, todas por leitura do AST do
  pacote e do `alerts.md`: nome de evento estável, evento emitido com linha no
  runbook, e evento do runbook que é de fato emitido. Mais a quarta, que faz as duas
  allowlists vencerem como a do `advisories.json`. Duas provas negativas dão sentido
  a elas: um evento inventado numa linha de tabela **reprova**, e a menção histórica
  a `drive.rejected` — dentro da nota de correção da ADR 0028 — **não** reprova.
- `apps/api/tests/test_authorization.py` (integração): a tentativa de acesso cruzado
  emite `authz.denied` com `reason=not_a_member` e só o prefixo do `sub`; o membro
  sem o papel emite `role_insufficient`. E, no mesmo caso, a asserção que impede a
  fatia de ter criado um oráculo: o projeto do vizinho responde **exatamente** como
  um id que não existe, corpo e status.
- `apps/api/tests/test_main.py`: `/health/ready` responde `ready`/`down` e **nada
  além disso** — é o caso negativo desta fatia (regra 6 do `AGENTS.md`), que aqui
  não é "quem pode chamar" e sim "o que a rota conta a quem não está autenticado".
- `apps/api/tests/test_admin_endpoints.py`: as duas asserções exaustivas de
  auditoria continuam exaustivas, agora com `trace_id` — e continuam provando que o
  segredo da chave e o conteúdo do arquivo não entram na linha.
- `tests/rendered-html.test.mjs`: o stub da API **recusa com 400** uma chamada sem
  `X-Request-ID`, do mesmo jeito que já recusava com 401 sem `Authorization` — é o
  que faz a asserção provar que o id viajou. Mais dois testes: as três `fetch()`
  paralelas do SSR saem com **um** id, e um id vindo de fora é respeitado.
- **Sem eval de IA.** Nada aqui toca prompt, recuperador, modelo ou ferramenta.
- **Sem spec de e2e novo.** O que esta fatia precisa provar cabe nos níveis de
  baixo, e o `e2e-login` é `continue-on-error` no CI.

## Acrescentado na ADR 0035 — o BFF entra na guarda

*Acrescentado em 06/08/2026.* A guarda bidirecional acima parava na fronteira do
pacote Python, e o BFF tem logger estruturado próprio (`app/lib/log.ts`) que
escreve no mesmo formato. Quatro eventos — `api.rejected`, `api.unreachable`,
`api.failed` e `web.request_error` — eram emitidos em produção **sem linha em
runbook nenhum**, que é exatamente a divergência que esta FDD existe para impedir.

A evidência estava dentro da própria guarda: um `elsewhere = {"web.request_error"}`
que declarava o evento como "emitido pelo BFF, não por este código". A exceção
descrevia o ponto cego em vez de fechá-lo.

- `apps/api/tests/test_telemetry.py`: a varredura passou a incluir os `.ts` da raiz
  e `app/`+`components/`, por expressão regular e não por AST (é TypeScript), com
  `app/lib/log.ts` de fora por ser a **definição** das funções. `emitted_events()`
  agora responde pelos dois deployables, e `test_every_web_log_line_is_a_named_event`
  reprova um `logWarn(\`api falhou: ${erro}\`)` — medido, neutralizando o sítio de
  `app/actions.ts:39`.
- Numa guarda só, e não num teste node ao lado: o `alerts.md` é um arquivo só, e
  duas guardas sobre ele divergem. O precedente é `test_seed_matches_realm.py`.
- Os quatro eventos ganharam linha em `docs/runbooks/alerts.md`, com o par
  `api.rejected`/`api.unreachable` distinto de propósito — lá alguém respondeu,
  aqui ninguém atendeu.
