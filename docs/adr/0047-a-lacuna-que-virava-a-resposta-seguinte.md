# ADR 0047 — A lacuna que virava a resposta seguinte

**Status:** aceito
**Data:** 11/08/2026
**Relacionada:** ADR 0015 (a conversa não é fonte de recuperação), ADR 0021 (evals adversariais), ADR 0035 (guardas derivadas)

## Contexto

Cinco testes e2e estavam vermelhos desde 07/08 e barravam merge. A ADR 0046 os registrou como
"dois testes vermelhos que não têm relação com GCP" e não os diagnosticou. Diagnosticados, são
**três** causas independentes, e duas delas são defeitos de teste. A terceira não é.

### O que estava errado nos testes

**Os specs não diziam em qual projeto trabalhavam.** Uma pessoa interna tem vínculo
organizacional (`project_id IS NULL`), e `access.default_project` então resolve por
`created_at DESC` — "o projeto mais recente da organização mais recente". As telas de
administração fazem o equivalente com `me.projects[0]`. Nenhuma das duas está errada; as duas são
**relativas ao que existe no banco**.

O banco local de quem percorreu `docs/runbooks/integracao-biahflow.md` — o que aquele runbook
manda fazer — tem uma segunda organização. A partir daí o upload de um spec ia para um tenant e a
pergunta do cliente rodava em outro, e quatro testes reprovavam por acúmulo de dado local, nunca
por defeito do produto. O runbook já registrava que "o banco local acumula"; o que faltava era a
suíte não depender disso.

**E `chat.spec.ts` usava o ator errado.** `rafael.costa` é `internal_member`, e `/admin/assistente`
exige `internal_admin` (`admin.py:_authorized` → `access.ADMIN_ONLY`), respondendo 404 — o que
`test_authorization.py` já afirmava do lado da API. O teste nasceu assim no commit da ADR 0033 e
**nunca passou**: media o 404 do contrato como se fosse ausência do comentário.

### O que estava errado no produto

Ao rastrear por que `documents.spec.ts` recebia `"Pendência: Responder dúvida do cliente: O que diz
o procedimento zafrenil…"` no lugar da citação do documento, apareceu um laço fechado que nenhum
teste cobria e que **não é sobre teste nenhum**.

Quando o assistente não acha evidência, ele declara a lacuna e abre uma pendência — regra 3 do
`AGENTS.md`, e o desenho está certo. O título dessa pendência é
`f"Responder dúvida do cliente: {question[:160]}"` (`ai/service.py`), isto é, **carrega a pergunta
do cliente**. Na volta, `collect_evidence` recolhia toda pendência aberta e montava a evidência com
`source=f"Pendência: {pending.title}"`.

O fallback genérico do `OfflineResponder` aceita qualquer evidência cujo `source + text` compartilhe
um token de quatro letras ou mais com a pergunta. Logo: **a pergunta de ontem, gravada pelo portal,
casava a pergunta de hoje.** O turno saía `sufficient=True`, citando a própria lacuna anterior, e
cada rodada deixava mais material para a próxima.

É a ADR 0015 outra vez, por uma porta que ninguém tinha olhado. Lá o argumento é que
`conversation_message` nunca é fonte de recuperação, porque senão o cliente escreve a própria
evidência; e a defesa é estrutural — `ai/retrieval.py` não lê aquela tabela. Aqui o texto do
cliente voltava ao contexto **pela tabela certa**, como read model recuperável por construção, com
o portal como autor. O invariante estava intacto e a propriedade que ele protege, não.

E isso não é um problema só do respondedor offline. `ai/service.py` cai no `OfflineResponder`
quando o provedor falha (`responder_name="offline_fallback"`), então **numa queda da Anthropic esse
casador por token é o caminho de produção**, com o corpus envenenado junto.

## Decisão

**1. `collect_evidence` recolhe apenas pendência com `origin=biahflow`.**

O recorte é por coluna e não por heurística de texto, e isso é possível porque o discriminador é
exato: existem **dois** sítios que criam `PendingItem` em todo o `src/` — `ai/service.py`, que não
passa `origin` e portanto cai no default `portal`, e `integrations/biahflow.py`, que passa
`biahflow`. A coluna responde exatamente à pergunta "isto veio da fonte?".

Já havia precedente do mesmo recorte na direção oposta: `sync_snapshot` apaga
`WHERE origin == biahflow` justamente para **não** apagar as do chat. As duas metades agora
concordam sobre o que cada origem significa.

Descartadas: filtrar por `external_ref IS NOT NULL` (equivalente hoje, mas é ausência de dado e não
afirmação de origem); e excluir por `ConversationMessage.pending_item_id`, que é o discriminador
semanticamente mais preciso e poria `ai/retrieval.py` a ler `conversation_message` — abrir essa
porta por um caso que a coluna resolve custaria o invariante da ADR 0015.

Sem migração: a coluna é `NOT NULL` com `server_default`, então as linhas existentes já estão
classificadas.

**2. Os specs resolvem o projeto pela tela, e navegam com `?project=`.**

O parâmetro já existia nas cinco páginas; o que faltava era os testes usarem. Como o id é
`uuid4()`, não há valor a cravar — `tests/e2e/atores.ts` resolve pelo seletor de projetos quando ele
existe e pelo `data-project-id` quando não existe, que são os dois estados legítimos do banco local.
O `signIn`, que vivia em seis cópias com duas variações de `waitForURL` que ninguém escolheu, foi
junto.

**3. `chat.spec.ts` ganha um segundo ator interno em vez de trocar o que tinha.**

Trocar a constante compartilhada consertaria o teste do comentário e **estragaria** o do
isolamento, onde `rafael.costa` é insubstituível: ali o que se prova é que nem quem alcança o
projeto lê a conversa do cliente, e usar a administradora enfraqueceria a afirmação.

## Consequências

- A lacuna de um turno não pode ser a citação do seguinte, e a suíte deixa de ficar mais frágil a
  cada execução. O critério de aceite escolhido reflete isso: os cinco ficam verdes **contra o banco
  acumulado**, e verdes de novo numa segunda execução seguida. Rodar contra um banco limpo teria
  escondido as duas propriedades.
- Um caso novo em `docs/ai/eval-dataset.md` — "lacuna anterior não vira a resposta seguinte" —, e
  `test_chat_ai.py` ganhou a eval correspondente, que roda a mesma pergunta duas vezes e exige
  lacuna nas duas. Nada testava esse caminho.
- Um teste existente precisou de conserto e vale registrar por quê: o caso "pendências abertas são
  citadas" criava a pendência **sem** `origin`, então ela nascia `portal` — a espécie que agora não
  é recolhida. Passar `origin=biahflow` não é acomodar o teste ao código: é escrever na fixture o
  que o `sync_snapshot` grava de verdade, e o teste era ambíguo antes.
- `PROMPT_VERSION` **não** muda. Os três digests de `prompt.py` cobrem o `SYSTEM_PROMPT`, o
  `OUTPUT_SCHEMA` e a moldura de `build_user_prompt`; o recuperador não está entre eles, e a
  moldura não foi tocada. A convenção que pede eval quando o recuperador muda foi cumprida pelo
  item acima.
- Nenhuma mudança de contrato: `PendingOut.origin` já era publicado, e a tela já rotula "aberta pela
  IA". Nenhuma pendência deixa de existir ou de aparecer para o cliente — elas só deixam de ser
  **evidência para o modelo**, que é outra coisa.

**Fica aberto, e é a causa de fundo que esta fatia não conserta:** `default_project` resolve por
duas ordenações por recência encadeadas e `visible_projects` por outra, de modo que o dashboard e a
administração **podem divergir sobre qual é "o projeto atual"** da mesma pessoa. Os specs agora são
imunes a isso porque dizem o que querem; uma pessoa interna com duas organizações não é. Qual
projeto ela deve ver por padrão é decisão de produto, não de implementação, e merece fatia própria.
