# FDD — Homologação, quotas de IA e carga

Fase 5 · ADR 0022 · fecha os dois últimos itens abertos da fase.

## Objetivo e não objetivos

**Objetivo.** Dar ao portal um ambiente que não seja o laptop de quem desenvolve, um teto para a
conta de IA de cada organização, e uma ferramenta de carga cujo número diga em que condições foi
obtido.

**Não objetivos, e cada um por um motivo:**

- **Provisionar a homologação.** A entrega é o ambiente como código — override de compose,
  Caddyfile, template de variáveis, runbook e portão de CI. Máquina, DNS e cron de backup são
  decisão de infraestrutura fora deste repositório.
- **Linha de base de desempenho.** Não existe e não vai existir enquanto a homologação for
  definida e não provisionada: um p95 medido no laptop de alguém não se compara com o da semana
  que vem. O relatório carrega `environment` e `is_homologation` justamente para ninguém comparar
  os dois por engano.
- **Métrica e coletor.** Continuam onde a ADR 0018 os deixou: o substrato é o log JSON no
  stdout, que qualquer coletor ingere sem código nosso. O que esta fatia acrescenta é o dado que
  faltava — custo e tokens no `chat.answered`.
- **Tela de administração da quota.** A rota existe sob `portal_admin`; a tela não. Sem consumo
  acumulado ela mostraria zero, que é o mesmo argumento com que a ADR 0015 adiou a tela de
  feedback.

## Jornada e interface

**Quem opera** copia `.env.homolog.example`, preenche os segredos e sobe com o override. Se
esquecer um, o compose recusa; se preencher pela metade, o processo recusa e lista **todos** os
problemas de uma vez. O runbook é `docs/runbooks/deploy.md`.

**Quem administra** vê e ajusta o teto da organização em
`GET|PUT /api/v1/admin/organizations/{id}/ai-quota`, que devolve o teto como foi definido, o que
de fato vale, o gasto do mês e as lacunas.

**Quem pergunta** não vê nada de novo até estourar. Aí o chat responde com a mensagem de cota —
distinta da mensagem de ritmo, e a tela as separa pela ordem de grandeza do `Retry-After`, não
pelo texto do erro.

**Quem mede** roda `scripts/loadtest.py` e recebe um JSON que declara o alvo, o modo, a mistura
de respondedores, os percentis, o custo e — em texto — tudo que qualifica esses números.

## Dados, API e permissões

Migração `0018_ai_usage_and_quota`, três tabelas:

| Tabela | Papel | Tenant | `portal_app` | `portal_admin` |
|---|---|---|---|---|
| `ai_usage_event` | razão: uma linha por chamada, com tokens | org + projeto | `SELECT`, `INSERT` (com `WITH CHECK`) | `SELECT` |
| `organization_ai_quota` | política: teto mensal, nulo = padrão | org | `SELECT` | `SELECT/INSERT/UPDATE` |
| `ai_model_price` | preço com vigência (`EXCLUDE USING gist`) | **nenhum** | `SELECT` | `SELECT` |

Nenhum `UPDATE` ou `DELETE` em `ai_usage_event` fora de `portal_system`: ninguém reescreve o que
uma chamada custou.

Settings: `ai_quota_monthly_cents` (padrão US$ 200; zero desliga) e `environment`
(`local` | `homolog` | `production`).

Rotas novas: as duas de `ai-quota` em `admin.py`. `POST /api/v1/chat` ganha um segundo motivo de
429, declarado no `responses=` e no `openapi.json`.

## Estados de erro e segurança

- **Teto atingido** → 429 com `Retry-After` até a virada do mês. Nunca 403, que o contrato
  proíbe. A requisição recusada **não grava pendência, mensagem nem consumo**.
- **Preço do modelo ausente** → o turno passa, o consumo entra no razão, a soma declara a lacuna
  e sai `ai_quota.price_missing`. Falha aberta deliberada: os tokens gravados tornam o custo
  recalculável, e uma pergunta recusada não volta.
- **Provedor limitando (429 da Anthropic)** → invisível para o cliente, porque toda exceção do
  provedor vira `offline_fallback`. Aparece como `chat.provider_unavailable` com
  `reason=RateLimitError` e como `offline_fallback` no `responder_mix` do relatório.
- **Configuração insegura fora de `local`** → o processo **não sobe**. Sentinela de exemplo,
  segredo vazio, `DEMO_MODE` ligado ou endereço em texto claro.
- **Segredo faltando no override** → o compose recusa (`${VAR:?}`), antes de qualquer contêiner
  existir.

## Telemetria e critérios de aceite

Eventos novos: `ai_quota.exhausted` (com `spent_cents`, `limit_cents`, `organization_id`),
`ai_quota.price_missing`, `preflight.refused`/`preflight.ok`. `chat.answered` passa a carregar
`input_tokens` e `output_tokens` — e os dois entraram na allowlist do formatter, porque contêm
"token" sem serem um, e sairiam `[redacted]`. Limiares em `docs/runbooks/alerts.md`.

**Aceite:**

1. Um `.env` de homologação incompleto não sobe — nem pelo compose, nem pelo processo.
2. Toda variável documentada no `.env.example` chega a algum contêiner.
3. O gasto do mês é calculado pelo preço vigente no dia de cada chamada, e mudar o preço hoje não
   reprecifica ontem.
4. Estourado o teto, o chat responde 429 e a requisição recusada não deixa rastro.
5. O relatório de carga declara o alvo, o modo e a mistura de respondedores.

## Testes e avaliações de IA

- `apps/api/tests/test_homolog_config.py` — 16 casos: o `preflight` em cada categoria de recusa,
  o template sendo ele próprio recusado, a correspondência override↔template, e o
  **defeito que motivou a fatia** travado no lugar (as cinco variáveis de chat no serviço `api`,
  e a proibição genérica de variável documentada sem destino).
- `apps/api/tests/test_ai_quota.py` — 14 casos pelo stack HTTP real: preço com vigência não
  reprecificando o passado, lacuna em vez de zero, offline sendo grátis sem ser lacuna, mês de
  calendário, 429 com `Retry-After` longo, a recusa sem rastro, o zero explícito desligando, e a
  RLS impedindo uma organização de enxergar o gasto de outra.
- `apps/api/tests/test_loadtest_harness.py` — 7 casos sobre a aritmética e as recusas do harness.
  Não medem carga (isso mediria o runner); existem para a ferramenta não apodrecer, que é a lição
  que a ADR 0021 aprendeu do jeito caro.
- **CI:** o job `local-stack` afirma que o override recusa sem segredos **e** valida com o
  template; o job `e2e` roda o harness por quinze segundos e confere que o relatório continua
  declarando que não é homologação.

**Avaliações de IA:** nenhuma nova, e a razão importa — esta fatia não toca no `SYSTEM_PROMPT`,
no `OUTPUT_SCHEMA`, na moldura do prompt do usuário, no recuperador nem no modelo. `PROMPT_VERSION`
não muda, e `test_prompt_version.py` confirma. O que ela acrescenta ao caminho da IA é leitura de
`response.usage` e uma linha de razão — nada que altere o que sai para o modelo, que é o que o
`evaluation-plan.md` cobra.
