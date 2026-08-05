# ADR 0020 — Contrato de API publicado, e o verde que prova

**Status:** aceita — 05/08/2026
**Contexto:** Fase 5, quarta fatia. Fecha "contratos OpenAPI" e a metade de CI de
"testes de integração com serviços reais / Playwright E2E" em `ROADMAP.md`.

## Contexto

Como as ADRs 0018 e 0019, esta fatia não implementa uma promessa adiada:
implementa uma que os documentos já davam como cumprida. Desta vez o documento
não estava apenas vazio — estava **errado**.

- `docs/api-contracts.md` encerrava com *"Contratos completos serão publicados
  automaticamente pelo OpenAPI do FastAPI"*. As dezesseis rotas de `main.py`
  devolviam `dict` cru e **nenhuma** declarava `response_model`, então o esquema
  publicado saía vazio exatamente na superfície do cliente — a única que alguém
  de fora consome. As vinte e três de `admin.py` estavam tipadas; a assimetria
  não foi decidida, aconteceu.
- `responses=` não aparecia **uma vez** no repositório. O 401 opaco e o "404,
  nunca 403" — a regra mais repetida do projeto, presente no `AGENTS.md`, no
  `api-contracts.md` e em quase todo docstring — não existiam no esquema. Quem
  gerasse um cliente a partir dele trataria 403 como possível.
- `bearer_principal` lê o header à mão, o que é correto e continua sendo, mas
  significava nenhum `securityScheme`: o `/docs` não mostrava cadeado em rota
  nenhuma, e nada dizia que `POST /api/v1/agent-events` é a única autenticada
  por chave.
- E o mesmo arquivo documentava **camelCase** (`fullName`, `notifyByEmail`,
  `unreadCount`, `occurredAt`, `eventId`, `timeSavedSeconds`, `effectiveFrom`)
  enquanto a API responde snake_case em todas elas. A prosa não derivou do
  código porque nunca teve como conferir.
- `docs/testing-strategy.md` lista "Contrato: OpenAPI e payloads" como o nível 6
  da pirâmide. O nível não existia.

O mesmo defeito, na forma que a ADR 0019 já tinha nomeado — *o comando que sai
com zero e ninguém olha duas vezes* —, estava no CI:

- As três asserções que dão sentido ao backup (policies de volta, GRANT de
  coluna ainda de coluna, uma organização sem ver a outra) e a de adulteração
  **pulavam em silêncio em toda execução**, porque o `env:` do job `api-quality`
  não definia `POSTGRES_USER`/`POSTGRES_PASSWORD`. A FDD 013 tinha declarado o
  job de CI como "o próximo passo desta linha"; o que faltava não era o job, era
  perceber que o que existia não rodava.
- `e2e-login` era `continue-on-error: true` e quatro dos sete specs se
  auto-pulavam numa sonda do `docker compose`. O comentário no próprio YAML
  dizia que isso "fica verde sem provar nada, que é pior do que vermelho".

**A tese das duas metades é uma só: um contrato que ninguém verifica e uma
asserção que ninguém executa são o mesmo defeito, e os dois se apresentam como
verde.**

## Decisão

### 1. `schemas.py`, e o modelo descreve o payload em vez de reescrevê-lo

O contrato do cliente vive num módulo só, e não inline como em `admin.py`,
porque lá a resposta nasce ao lado da rota e aqui ela nasce em **outros
módulos** — `build_dashboard`, `results.to_payload`, `_message_payload`. Pôr o
modelo junto de cada produtor reproduziria a divisão que a fatia existe para
fechar. Mesma forma de `notifications.py`, `conversations.py` e `telemetry.py`.

A regra que governa o módulo é não mudar byte nenhum: **onde o produtor já
entregou texto, o modelo declara texto.** Um `occurred_at` que sai de
`.isoformat()` fica `str`, não `datetime`. Declarar o tipo rico faria o Pydantic
reserializar — e reserializar é mudar o que o navegador recebe, numa fatia cujo
compromisso é descrever o que já existe. O tipo rico é o passo seguinte, junto
de fazer os produtores devolverem os modelos em vez de dicionários; separá-los é
o que permite saber qual dos dois quebrou.

### 2. `extra="forbid"`: campo não declarado é erro, não descarte

Esta é a decisão que separa um contrato de um enfeite, e ela vai na direção
oposta do padrão do FastAPI. `response_model` **filtra em silêncio** o que o
modelo não conhece: alguém acrescenta uma chave em `build_dashboard`, a tela
para de recebê-la, e nada fica vermelho — a rota responde 200, o esquema segue
"válido", e o dado some. Tipar as respostas *acrescentaria* esse modo de falha
ao repositório se parasse aí.

Com `extra="forbid"` a mesma situação estoura na resposta, e
`test_openapi_contract.py` a encontra antes da produção comparando ida e volta
(`model_dump(by_alias=True) == payload`) contra um dashboard e uma apuração
construídos de verdade. A comparação pega as três coisas: a chave a mais, a
chave a menos, e o valor que teria sido reserializado em outro formato.

### 3. As regras viram propriedades do esquema, e o teste as cobra de toda rota

Não bastava documentar 401 e 404 nas rotas de hoje. `test_openapi_contract.py`
afirma sobre **todas**, inclusive a que alguém acrescentar amanhã sem ler nada
disto:

- nenhuma rota declara 403, em lugar nenhum;
- toda rota com esquema de segurança declara 401;
- toda rota escopada por tenant declara 404 — com duas exceções nomeadas e
  justificadas (`GET /api/v1/me` e `PATCH /api/v1/me/preferences`, que não
  dependem de projeto: autenticar não é autorizar, e quem não tem vínculo
  recebe 200 com `projects` vazio);
- `/api/v1/agent-events` é a **única** rota por chave, e não declara o Bearer;
- nenhum campo de corpo de resposta tem nome de segredo, pela lista que
  `telemetry.py` já usa para redigir log — reusada, e não recopiada, porque duas
  listas divergem e aí um dos dois controles passa a proteger outra coisa.

Os três esquemas de segurança são declarativos e **não decidem nada**:
`auto_error=False` os mantém mudos, e quem recusa continua sendo `auth.py` e
`agent_auth.py`. Trocar a validação por eles mudaria a resposta — o `HTTPBearer`
de erro automático responde 403 a header ausente, e aqui 403 não existe.

Escrever o teste encontrou o único campo da API cujo nome parece segredo e não
é: `AgentEventIn.agent_key`, que é o **rótulo** do agente, do lado da
requisição, enquanto a credencial viaja no header `X-Agent-Key`. É por isso que
a varredura fecha os `$ref` transitivamente a partir das respostas: os dois
nomes quase iguais convidam a confundi-los, e agora há um teste que escreve a
diferença.

### 4. O esquema é artefato versionado, com gate de deriva

`docs/api/openapi.json` entra no repositório, gerado por
`python -m portal_api.openapi --write`, e o teste falha quando diverge do
código. É o `alembic check` do contrato, e pelo mesmo motivo: um esquema que só
existe num processo no ar não pode ser comparado com o da semana passada, e uma
mudança de contrato precisa aparecer como diff que alguém aprova.

`sort_keys` é deliberado — sem ele uma troca de versão do FastAPI reordena
chaves e produz um diff enorme onde nada mudou, que é como se ensina uma equipe
a aprovar diff de contrato sem ler.

Com o artefato existindo, `docs/api-contracts.md` deixa de ser uma segunda
verdade: fica com o que prosa faz bem — as regras, quem autentica com o quê, o
que é idempotente, o que é devolvido uma vez só — e aponta para o esquema para
lista de campos. O camelCase sai. Trocar a API para camelCase foi descartado: o
web lê snake_case em quatro arquivos, e uma fatia de contrato que quebra o
contrato é piada.

### 5. A fixture do teste web deixa de ser livre para mentir

`tests/fixtures/dashboard.mjs` afirma no cabeçalho que espelha o que as rotas
devolvem, e nada conferia. A API que `rendered-html.test.mjs` sobe é de mentira,
e uma API de mentira é livre para mentir: renomeada uma chave, a fixture fica
com o nome velho, o `page.tsx` lê o nome velho, e o teste passa provando que
dois enganos combinam entre si.

`tests/api-contract.test.mjs` valida a fixture contra o esquema versionado com
`ajv` — uma devDependency, nenhum passo de geração. Tipos TS gerados foram
descartados por ora: pegariam mais deriva, mas acrescentam artefato gerado e um
passo de build, e a fixture é onde a deriva se torna invisível.

### 6. Um pulo silencioso deixa de ser possível no CI

A generalização, e não os dois remendos. `conftest.py` ganhou `skip_unless_ci`,
que pula na máquina de quem desenvolve e **falha** quando `CI` está definida; o
par em TypeScript é `tests/e2e/stack.ts`, que substituiu quatro cópias de
`dockerAvailable()`.

Um pulo é uma afirmação sobre o ambiente: "aqui não dá para provar isto". Numa
máquina sem Postgres no ar isso é verdade e é útil. No CI a mesma frase é
falsa e é cara — o job *tem* um Postgres, o job *sobe* a pilha —, e ali um pulo
não diz "falta ambiente", diz "o ambiente não está como se pensava", em verde.
É a regra da ADR 0017 outra vez, *`skipped` não é `clean`*, aplicada ao próprio
arsenal de testes. Vale só para o que o CI deve cobrir: ClamAV e chave da Voyage
continuam pulando em silêncio, porque ali o pulo continua verdadeiro.

Daí saíram duas mudanças de workflow:

- **Job `backup-restore` próprio.** Rodar o par exige o que o resto da suíte não
  exige — storage, as senhas dos quatro papéis e um cliente do Postgres tão novo
  quanto o servidor —, e descobrir isso foi consequência de fazer o pulo falhar:
  ligar as duas variáveis que faltavam revelou mais quatro e um MinIO. Job
  separado porque um backup quebrado deve ficar vermelho sozinho.
- **`e2e` deixou de ser `continue-on-error`** e perdeu o `-login` do nome, que
  já não descrevia o que ele faz.

E tirar a flag cobrou o que devia cobrar: a suíte inteira falhava, um teste
diferente por execução, enquanto cada spec passava sozinho. A explicação
corrente — e a que estava escrita — era sessão SSO do Keycloak vazando entre
specs. **Era falsa**: todos já limpavam cookies. A causa real é que
`documents.spec.ts` esperava a indexação com `toPass({ timeout: 60_000 })`
dentro de um teste cujo orçamento total também era 60s, e `drive.spec.ts`
esperava **90s dentro dos mesmos 60s** — uma espera que nunca teve como chegar
ao fim. Com a suíte inteira o worker está ocupado com o que os outros specs
enfileiraram, a espera consome o orçamento, e o Playwright reporta a falha no
**passo seguinte**, quase sempre um `signIn` cuja página já é o dashboard. Daí a
aparência de sessão vazada, e daí um diagnóstico errado sobreviver meses: o
sintoma apontava para longe da causa, e o job não podia reprovar, então ninguém
precisou olhar.

A correção é uma regra, escrita no `playwright.config.ts`: **espera interna
nunca passa de metade do orçamento do teste**. Orçamento a 120s, as esperas a
40s e 60s. Dezenove testes, três execuções seguidas, ~33s.

## Consequências

- Existe `apps/api/src/portal_api/schemas.py`, e uma rota de cliente nova sem
  `response_model` não passa no CI.
- `docs/api/openapi.json` é artefato versionado. Toda mudança de contrato agora
  é um diff revisável; esquecer de regenerá-lo é vermelho.
- `admin.py` ganhou os dois erros no `APIRouter` em vez de repetidos vinte e
  três vezes, e `sync_drive_now` — a única rota de lá sem `response_model` —
  ganhou o dele.
- O `/docs` passou a mostrar cadeado, e a mostrar **qual** credencial cada
  superfície usa. Os três esquemas têm `scheme_name` explícito: sem isso duas
  `APIKeyHeader` colapsam numa entrada só e a chave do agente vira a mesma coisa
  que a assinatura do webhook — exatamente a confusão que a fatia desfaz.
- `GET /api/v1/me/conversations/latest` é a única rota com
  `response_model_exclude_unset`, e é o preço da regra 1: sem conversa nenhuma o
  corpo não traz `title`, e declará-lo com padrão acrescentaria uma chave nula
  que hoje não existe.
- O `MyDashboardOut` documenta uma assimetria anterior a esta fatia — só
  `/me/dashboard` acrescenta `organization` — em vez de corrigi-la, porque
  corrigi-la muda um payload.
- `ajv` é a primeira dependência de teste do web além do Playwright.
- O CI ficou com sete jobs e mais lento. É o preço de ele passar a afirmar o que
  antes só parecia afirmar.

## Alternativas descartadas

- **Gerar tipos TypeScript do esquema** (`openapi-typescript`). Pegaria mais
  deriva que a fixture — há três declarações independentes de `ApiMe` em três
  arquivos, e `toOverview` faz cast campo a campo sobre `Record<string,
  unknown>`. Descartado *por ora* por acrescentar artefato gerado e passo de
  build a uma fatia que já cruza API, testes e CI; e porque a fixture é onde a
  deriva fica invisível, que é o que urgia.
- **Fazer os produtores devolverem os modelos.** É o destino natural, e não cabe
  aqui: `build_dashboard` é lido por dezenas de asserções de chave em
  `test_biahflow_integration.py`, e trocar produtor e contrato na mesma fatia
  tornaria impossível saber qual dos dois quebrou.
- **`extra="ignore"`, o padrão.** É o que produz o modo de falha da decisão 2.
  Um contrato que descarta em silêncio o que não conhece descreve a API menos
  fielmente do que o `dict` cru que ele substituiu.
- **Schemathesis ou testes de propriedade sobre o esquema.** Geram carga de
  requisição contra rotas que exigem tenant e membership; o que produziriam aqui
  é 401 e 404 em volume. O valor está nas propriedades do documento, que é o que
  `test_openapi_contract.py` afirma.
- **Deixar `api-quality` rodar `test_backup_restore.py` com tudo ligado.**
  Somaria MinIO e seis variáveis ao job que roda a suíte inteira, para servir a
  um arquivo. O par backup/restore tem dependências próprias e merece o próprio
  vermelho.
- **Testes de carga nesta fatia.** Sem ambiente com orçamento declarado, um
  número de carga contra o `docker compose` de quem roda mede o laptop.
  Pertencem ao item de homologação, pelo mesmo argumento que a ADR 0018 usou
  para métrica e painel.
