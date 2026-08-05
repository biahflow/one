# FDD — Contrato de API publicado

Fase 5, ADR 0020.

## Objetivo e não objetivos

**Objetivo.** Que o contrato da API exista como artefato — legível por
ferramenta, versionado, e recusado quando derivar do código — e que o verde do
CI passe a afirmar só o que ele de fato provou.

**Não objetivos.** Tipos TypeScript gerados do esquema: pegariam mais deriva que
a fixture, mas acrescentam artefato gerado e passo de build; a deriva que urgia
era a invisível. Fazer os produtores (`build_dashboard`, `to_payload`)
devolverem os modelos em vez de dicionários: é o destino natural e fica para
depois, porque trocar produtor e contrato juntos torna impossível saber qual dos
dois quebrou. **Testes de carga**: sem ambiente com orçamento declarado, um
número de carga mede o laptop de quem roda — pertencem ao item de homologação,
como métrica e painel na ADR 0018. **Evals adversariais e prompt versionado**:
fatia própria, e há defeito real esperando por ela (o `prompt-policy.md` diz que
prompts são versionados e não há `PROMPT_VERSION` nem carimbo em
`conversation_message`; nenhum teste toca o `AnthropicResponder`).

## Jornada e interface

**Nenhuma superfície do cliente muda, e nenhum byte de resposta muda** — é o
compromisso central da fatia, e o teste de ida e volta é quem o sustenta.

Para quem integra, a jornada é o `/docs`: ele passa a mostrar os campos de cada
resposta, o cadeado, e **qual** credencial cada superfície usa — Bearer do OIDC
nas rotas de cliente e administração, `X-Agent-Key` só na de eventos,
`X-Biahflow-Signature` só no webhook.

Para quem desenvolve, a jornada é o diff: mudar o contrato agora exige

```bash
PYTHONPATH=apps/api/src python -m portal_api.openapi --write
```

e o `docs/api/openapi.json` resultante vai no commit, onde alguém o revisa.

## Dados, API e permissões

- **Sem migração, sem modelo de banco novo, sem papel novo, sem policy nova.**
  Nada aqui toca o banco.
- **Nenhuma rota nova e nenhuma rota removida.** As dezesseis de `main.py`
  ganharam `response_model` e `responses=`; `admin.sync_drive_now`, a única de
  lá sem modelo, ganhou o dela; o `APIRouter` de administração ganhou os dois
  erros comuns.
- Três esquemas de segurança declarativos (`auto_error=False`), que **não
  decidem nada**: quem recusa continua sendo `auth.py` e `agent_auth.py`.
- `GET /api/v1/me` e `PATCH /api/v1/me/preferences` são as duas rotas de cliente
  que não declaram 404, e é contrato: elas não dependem de projeto.

## Estados de erro e segurança

- **404 e nunca 403, agora afirmado sobre toda rota.** O teste recusa qualquer
  operação do esquema que declare 403 — inclusive uma que ainda não existe.
- **401 opaco documentado como opaco.** A descrição no esquema diz que o motivo
  vive no log, para que ninguém trate a resposta como diagnóstico.
- **Nenhum campo com nome de segredo no corpo de resposta**, pela lista que
  `telemetry.py` usa para redigir log — reusada, não recopiada. A única exceção
  é o `key` de `AgentKeyCreatedOut`, a chave em claro devolvida uma única vez, e
  há um teste afirmando que ela **não** aparece em `AgentKeyOut`.
- **Campo não declarado é recusado, não descartado** (`extra="forbid"`). O
  padrão do FastAPI filtraria em silêncio, e um dado sumindo da tela sem nada
  ficar vermelho é o modo de falha que tipar as respostas acrescentaria se a
  decisão fosse a outra.
- **`AgentEventIn.agent_key` é rótulo, não credencial.** Achado ao escrever a
  varredura de segredos, e é por isso que ela fecha os `$ref` transitivamente a
  partir das respostas.

## Telemetria e critérios de aceite

Sem evento novo: a fatia não acrescenta caminho de execução. O que ela
acrescenta é ao CI — `backup-restore` como job próprio, e `e2e` bloqueante.

Aceite:

1. Uma rota de cliente nova sem `response_model` não passa no CI.
2. Um campo renomeado no produtor derruba o teste de contrato **e** o do web.
3. O esquema declara 401 em toda rota autenticada, 404 em toda rota escopada, e
   403 em nenhuma.
4. Nenhum nome de segredo aparece como campo de resposta.
5. Um teste que pularia por falta de banco, de cliente `pg_dump` ou de pilha no
   ar **falha** quando `CI` está definida.
6. O par backup/restore roda a cada push, com as três asserções que vinham
   pulando.

## Testes e avaliações de IA

- `apps/api/tests/test_openapi_contract.py`, treze casos: o gate de deriva, as
  cinco propriedades acima, a exceção nomeada do `agent_key`, e os dois de ida e
  volta (dashboard e apuração, construídos de verdade contra Postgres) que
  provam que nenhuma chave se perde.
- `tests/api-contract.test.mjs`, cinco casos: a fixture do teste de SSR validada
  contra o esquema versionado, mais a prova negativa de que um campo renomeado é
  recusado — sem ela o arquivo poderia estar passando por acidente contra um
  esquema permissivo.
- `apps/api/tests/conftest.py` e `tests/e2e/stack.ts`: `skip_unless_ci` e
  `stackIsMissing`, os dois lados da mesma regra.
- **Sem eval de IA.** Nada aqui toca prompt, recuperador, modelo ou ferramenta.
- **Sem spec de e2e novo.** O que a fatia faz pelo e2e é fazê-lo poder reprovar —
  e isso cobrou uma correção na hora: a suíte inteira falhava, um teste diferente
  por execução. O que se dizia (inclusive por escrito) era sessão SSO vazando
  entre specs; era falso, todos já limpavam cookies. `documents.spec.ts` esperava
  a indexação com o **mesmo** orçamento do teste, e `drive.spec.ts` esperava 90s
  dentro de um teste de 60s. A regra que ficou no `playwright.config.ts`: espera
  interna nunca passa de metade do orçamento. 19/19 em três execuções.
