# FDD — Cenários adversariais de IA

Fase 5, ADR 0021.

## Objetivo e não objetivos

**Objetivo.** Que o prompt tenha uma versão que não pode mentir; que as evals de
injeção rodem contra o respondedor real com um modelo hostil, em vez de contra um
casador que não tem como obedecer; que abusar do chat custe alguma coisa; e que a
queda do provedor deixe rastro com o nome que o runbook manda procurar.

**Não objetivos.** **Testes de carga**: sem ambiente de homologação com orçamento
declarado, um número de carga contra o `docker compose` mede o laptop de quem
roda — continua no item aberto do roadmap, junto de métrica e painel (ADR 0018).
**Quotas** (janela longa, por organização, com cobrança): o `threat-model.md` as
prometia e a fatia **corrige o documento** em vez de fingir que as entregou; elas
dependem do mesmo ambiente. **Filtro de injeção na saída**: recusado com
argumento, não adiado — falha na primeira paráfrase enquanto cria a impressão de
que o problema acabou (ADR 0021, decisão 5). **Expor o carimbo de prompt na
API**: o cliente não é a audiência disso.

## Jornada e interface

Para o cliente, quase nada muda — e o "quase" é o que importa. Perguntar segue
igual até o vigésimo turno do minuto; passando disso, o assistente responde
"Você fez muitas perguntas em pouco tempo. Tente de novo em Ns" em vez de
responder a pergunta. E quando a API não responde por qualquer outro motivo, o
assistente passa a dizer que não conseguiu falar e que **nada foi registrado** —
onde antes ele inventava uma data, uma decisão, uma contagem de pendências e dois
rótulos de citação que nunca existiram, e ainda anunciava uma pendência que
ninguém tinha gravado.

Para quem opera, a jornada é o runbook:

```bash
docker compose logs api | grep '"event":"chat.provider_unavailable"'
docker compose logs api | grep '"event":"embedding.unavailable"'
docker compose logs api | grep '"event":"chat.rate_limited"'
```

Para quem mexe no prompt, é um comando e uma regra:

```bash
PYTHONPATH=apps/api/src python -m portal_api.ai.prompt --record
```

Mudou o texto, muda a `PROMPT_VERSION`. Regravar o registro não é saída.

## Dados, API e permissões

- **Migração 0016** — `conversation_message` ganha `prompt_version`, `responder`
  (enum `message_responder`: `offline`/`anthropic`/`offline_fallback`) e `model`,
  todos anuláveis, só preenchidos na mensagem do assistente. **Nenhum GRANT
  novo**: `portal_app` já tinha `INSERT` desde a 0012, e o `UPDATE` continua
  restrito às quatro colunas de feedback.
- **Migração 0017** — `chat_rate_window`, uma linha por `sub`, **sem
  `organization_id` e sem `project_id`**. RLS ligada e nenhuma policy
  `TO portal_app` (forma de `agent_api_key`); `GRANT SELECT, INSERT, UPDATE` só
  para `portal_system`. O meta-teste de `test_rls_isolation.py` não cobra policy
  desta tabela porque cobra por `organization_id`, e a migração registra isso.
- **API** — `POST /api/v1/chat` passa a declarar **429** com `Retry-After`, e o
  `docs/api/openapi.json` foi regerado. Nenhum campo novo em nenhuma resposta.
- **Settings** — `chat_rate_limit` (20) entra; `chat_prompt_version` sai;
  `anthropic_model` passa a `claude-opus-5`.

## Estados de erro e segurança

- **429 é a única recusa não opaca do chat**, e é deliberado: quem pergunta
  precisa distinguir "seu ritmo" de "sua permissão". Gasto **antes** da
  resolução do projeto, então um token válido sem projeto vê 429 antes de 404 —
  o que não conta nada sobre projeto nenhum.
- **A requisição recusada não deixa rastro.** Sem pendência, sem mensagem, sem
  linha de auditoria. É a propriedade que dá sentido ao limite, porque a ameaça
  é a enxurrada na caixa do time interno.
- **Recusa do provedor ≠ parser quebrado.** `ProviderRefused` separa os dois no
  `reason` do log; antes uma recusa (que devolve `content` vazio) virava
  `JSONDecodeError` e mandava procurar um bug inexistente.
- **Nenhum caminho da tela fabrica resposta ou citação.** Provado por varredura
  de fonte, e não por navegador: um array de literais atribuído a `sources` no
  cliente do chat reprova o build.
- **O limite estrutural está declarado**, não escondido: o portal não garante que
  um modelo remoto deixe de parafrasear texto injetado dentro da `answer`. O que
  ele garante é que afirmação sem citação real nunca chega ao cliente como fato.

## Telemetria e critérios de aceite

Eventos novos: `chat.answered` (`prompt_version`, `responder`, `model`,
`confidence`, `citations`), `chat.provider_unavailable` (`responder`, `model`,
`reason`), `embedding.unavailable` (`model`, `reason`), `chat.rate_limited`
(`subject_prefix`, `limit`). Limiares em `runbooks/alerts.md`. O `sub` inteiro
nunca vai ao log — só o prefixo, como o `key_prefix` da API de eventos.

**Aceite:**

1. Editar o `SYSTEM_PROMPT` sem trocar a `PROMPT_VERSION` reprova no CI, e
   `--record` não conserta.
2. Um turno guardado nomeia o prompt, o respondedor e o modelo; um turno que caiu
   no fallback é distinguível de um turno normal, pela linha.
3. Um modelo que cita fonte inventada, cita fonte de outro tenant, afirma sem
   citar ou devolve prosa não produz fato citado na tela — em todos os casos, e
   sem 500.
4. Nenhum segredo do portal e nenhum texto de outro projeto aparece no pedido
   enviado ao modelo.
5. A vigésima primeira pergunta do minuto responde 429 com `Retry-After`, e não
   grava pendência nem mensagem.
6. Uma queda do provedor emite o evento que o `ai-provider-failure.md` manda
   procurar.
7. Uma falha do chat na tela nunca vira resposta ou citação fabricada.

## Testes e avaliações de IA

- **`apps/api/tests/test_chat_ai.py`** — os catorze casos existentes seguem, e
  entram **catorze adversariais** contra o `AnthropicResponder` real com um Claude
  hostil (`anthropic_fake.py`). O primeiro deles é a guarda dos outros treze:
  *uma chave configurada seleciona o respondedor real* — sem ele, uma fixture
  quebrada faria o conjunto re-testar o offline em silêncio, e um conjunto
  adversarial que não roda contra o alvo é lido como cobertura sem ser.
  Determinístico e sem chave em CI: a chave é um literal, conferido como ausente
  do que sai. Ver `docs/ai/eval-dataset.md`.
- **`apps/api/tests/test_prompt_version.py`** — nove casos, e o que importa é o
  que prova o portão: um prompt alterado sob versão já gravada é **recusado**, e
  `--record` recusa reescrever.
- **`apps/api/tests/test_chat_rate_limit.py`** — seis casos, incluindo o que o
  limite existe para garantir (a requisição recusada não grava nada) e o que o
  desenho de RLS promete (o caminho de requisição lê zero linhas da janela).
- **`apps/api/tests/test_conversations.py`** — dois casos novos para o carimbo,
  lendo a **linha** e não a API, porque o carimbo não está no contrato.
- **`apps/api/tests/test_telemetry.py`** — três casos garantindo que os campos
  novos atravessam o formatter e a redação.
- **`tests/rendered-html.test.mjs`** — a guarda de `answerFor` trocou de lado, e
  ao lado dela entrou uma sobre a forma: citação fabricada no cliente do chat
  reprova.

## Acrescentado na ADR 0035 — a regra 2 deixa de ser um inventário

*Acrescentado em 06/08/2026.* `test_eval_no_secret_ever_reaches_the_model` é a
única asserção do repositório dedicada à regra 2 do `AGENTS.md`, e fixava **seis
sentinelas escritas à mão**. `Settings` declara 85 campos, dos quais **dezesseis**
carregam segredo — a proporção da ADR 0033 outra vez, no lugar mais caro possível.

- **Dois casadores, porque o segredo se esconde de duas formas.** `_SECRET_HINTS`
  entra por `import` de `telemetry.py` (o precedente é `test_openapi_contract.py`;
  recopiar faria uma cópia envelhecer sozinha) e pega doze campos pelo nome. Os
  outros quatro são as `database_*_url`, que escondem a senha **dentro do valor** e
  não casam nome nenhum — o casador do log pergunta pelo nome porque no log é a
  chave do `extra`, e ali está certo.
- Ficavam de fora `drive_token_encryption_key_previous` — a chave anterior da
  rotação, que abre todo ciphertext ainda não resselado (ADR 0016) — e a senha do
  `portal_admin`, a credencial que escreve `membership`.
- **Medido, não deduzido:** com um vazamento injetado em `ai/service.py`, a guarda
  nova reprova nomeando `database_admin_url` e a antiga **passa verde**, com uma
  asserção auxiliar confirmando que o DSN estava no corpo do pedido.
- Falsos positivos viraram allowlist com motivo e guarda de obsolescência. Cinco
  dos seis são o mesmo caso: **"keycloak" contém "key"**.
- `voyage_api_key` com sentinela escolheria o `VoyageEmbedder` e abriria rede; o
  embedder é fixado offline e a sentinela **continua atravessando** o serviço.
