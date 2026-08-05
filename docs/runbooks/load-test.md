# Runbook — carga de IA

Fase 5, ADR 0022. A ferramenta é `scripts/loadtest.py`; ela mora em `scripts/` pela razão do
backup: é **operação**, não aplicação.

```bash
# Local, sem chave: mede a infraestrutura do chat, e o relatório diz isso.
PYTHONPATH=apps/api/src python scripts/loadtest.py --duration 60 --out /tmp/carga.json

# Contra homologação, com chave e orçamento — sem `--budget-usd` ele recusa.
PYTHONPATH=apps/api/src python scripts/loadtest.py \
  --base-url https://api.interna.exemplo --issuer https://auth.exemplo/realms/portal-homolog \
  --users ana bruno carla dani --password "$LOAD_PASSWORD" \
  --budget-usd 5 --duration 300 --out carga-$(date +%F).json
```

## Antes de rodar contra homologação

1. **Contas.** O limite é de 20 perguntas por minuto **por pessoa**, então a vazão máxima
   honesta é `contas × 20/min`. Quatro contas dão 80/min. Crie-as como qualquer outra pessoa,
   pelo `/admin`, e apague-as depois.
2. **Tokens.** O harness usa password grant. O realm de homologação **não** tem direct access
   grants habilitado, e não deve ter — habilitá-lo no client de login significa que uma senha
   vazada vale um token sem passar pelo navegador. As duas saídas honestas: habilitar
   temporariamente num client separado só para a execução, ou obter os tokens por logins reais e
   passá-los ao harness. No realm **local** ele está habilitado no `portal-web`, e ali isso não
   custa nada — todas as senhas daquele realm são `portal_local_only` e estão versionadas.
3. **Orçamento.** Um turno médio a `claude-opus-5` custa, aos preços da migração 0018, algo como
   0,5 centavo de entrada mais o que a resposta gerar. US$ 5 compram uma execução confortável de
   alguns minutos. O harness **para sozinho** ao atingir o teto e escreve `stopped_by_budget` no
   relatório.
4. **A quota da organização é um teto real.** Uma execução longa pode esbarrar nela e o relatório
   passa a contar `quota_exhausted`. Isso não é falha do harness: é o controle da ADR 0022
   funcionando. Suba o teto daquela organização pelo `/api/v1/admin/organizations/{id}/ai-quota`
   antes, e devolva-o depois.

## Lendo o relatório

O campo que decide se o resto vale alguma coisa é **`responder_mix`**:

| O que aparece | O que significa |
|---|---|
| `{"anthropic": N}` | A medição é do caminho real. Os percentis descrevem o modelo. |
| `{"offline": N}` | Não havia `ANTHROPIC_API_KEY`. Mediu pgvector, RLS, transações e o limite de taxa — **não** mediu o modelo. |
| `offline_fallback > 0` | **O provedor degradou no meio da execução.** Os percentis não descrevem o que dizem descrever: aqueles turnos foram respondidos pelo casador local, que é ordens de grandeza mais rápido. Descarte a execução e vá ao `ai-provider-failure.md`. |

E `notes` traz, em texto, tudo que qualifica o número — inclusive a frase que importa quando
alguém citar o relatório meses depois: `ENVIRONMENT=local` significa que aquilo **não é
homologação** e descreve a máquina que rodou o compose.

`rate_limited > 0` quase sempre quer dizer que faltam contas, não que o sistema saturou; o campo
`rate_ceiling_per_second` diz qual era o teto.

## Um 429 do provedor

O `ai-provider-failure.md` não falava disso até esta fatia. Sob carga com chave real, um 429 da
Anthropic **não** aparece como erro: `ai/service.py` engole toda exceção do provedor e cai no
respondedor offline, então ele chega ao relatório como `offline_fallback` no `responder_mix` e,
no log, como `chat.provider_unavailable` com `reason=RateLimitError`. É por isso que a mistura de
respondedores é a primeira coisa a ler.

```bash
docker compose logs api | grep '"event":"chat.provider_unavailable"' | tail -20
```

Se for isso, baixe `--rate` e repita. O portal **não** faz retry com recuo próprio: acrescentá-lo
transformaria uma recusa de ritmo do provedor numa latência que ninguém explica, e a decisão de
esperar pertence a quem paga a conta.

## Quando o preço do modelo muda

O custo do relatório sai de `ai_model_price`, que é a mesma tabela que a quota usa para recusar
perguntas — de propósito, para as duas não discordarem. Preço não se edita: fecha-se a vigência
corrente e abre-se outra, como a premissa financeira da ADR 0013.

```sql
UPDATE portal.ai_model_price SET effective_to = CURRENT_DATE
 WHERE model = 'claude-opus-5' AND effective_to IS NULL;

INSERT INTO portal.ai_model_price
  (id, model, effective_from, effective_to, input_cents_per_mtok, output_cents_per_mtok)
VALUES (gen_random_uuid(), 'claude-opus-5', CURRENT_DATE, NULL, 600, 3000);
```

Editar a linha vigente reprecificaria os meses passados, que é exatamente o que a vigência existe
para impedir. O `EXCLUDE USING gist` recusa duas vigências sobrepostas do mesmo modelo.

**Trocar `ANTHROPIC_MODEL` sem cadastrar o preço do modelo novo** faz o consumo entrar no razão e
ficar fora da soma: o mês parece mais barato do que foi e o teto fica cego. O portal declara isso
em vez de esconder — `ai_quota.price_missing` no log, e a lacuna no corpo de
`GET /api/v1/admin/organizations/{id}/ai-quota`. O turno **não** é recusado, e a razão está na
ADR: os tokens ficaram gravados, então o custo é recalculável depois; uma pergunta recusada hoje
não volta.

## O que este runbook não promete

Não existe linha de base publicada, e não vai existir enquanto a homologação for definida e não
provisionada. Um p95 medido no laptop de alguém não é um número que se compare com o da semana
que vem. A primeira execução contra o ambiente real é que abre essa série — e o relatório traz
`environment` e `is_homologation` justamente para que ninguém compare as duas por engano.
