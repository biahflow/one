# Runbook — o passeio local: ver cada fatia funcionando

Os outros runbooks desta pasta respondem *"deu errado, e agora?"*. Este responde *"está de pé,
e agora?"* — é o caminho de alguém que quer **usar** o portal local e conferir, com os próprios
olhos, o que cada fase entregou.

Ele existe porque esse conhecimento morava só dentro dos specs de `tests/e2e/`: o comando que
dispara o sync do Biahflow, o corpo do evento de agente e o canário do Drive estavam embutidos
em arquivos de teste — legíveis para quem já sabia onde procurar, invisíveis para quem queria
usar o produto. As credenciais do ambiente local não estavam documentadas em lugar nenhum.

**Tudo aqui foi executado contra a pilha local antes de ser escrito**, inclusive os tempos. Um
runbook que ninguém percorreu é o defeito que a Fase 5 encontrou sete vezes; onde a observação
foi medida nesta máquina, está dito que foi.

## 1. Subir, e saber que subiu

```bash
cp .env.example .env
docker compose up --build          # a primeira vez leva alguns minutos
```

Não é preciso rodar seed: o serviço `api-seed` roda uma vez, depois das migrações, e a API
declara `service_completed_successfully` sobre ele — ou seja, **a API não sobe sem o seed
aplicado**. Ele é idempotente, então um `up` seguinte não duplica nada.

Está pronto quando:

```bash
docker compose ps                  # dez serviços em "running"
curl -s localhost:8000/health/ready # {"status":"ready"}
```

| Serviço | Endereço | Para quê |
|---|---|---|
| Portal web | http://localhost:3000 | o produto |
| API + OpenAPI | http://localhost:8000/docs | o contrato, navegável |
| Keycloak | http://localhost:8080 | o SSO (console: `admin` / `admin_local_only`) |
| Mailpit | http://localhost:8025 | **todo** e-mail que o portal envia cai aqui |
| MinIO Console | http://localhost:9001 | os arquivos enviados (`portal-minio` / `portal-minio-local-only`) |
| Drive stub | http://localhost:19100 | o "Google Drive" falso do compose |

O `drive-stub` é o que permite exercitar o conector do passo 3.9 sem credencial do Google — do
mesmo jeito que o Mailpit permite ler os e-mails sem provedor de SMTP.

## 2. Quem é quem

Três contas, semeadas por `apps/api/src/portal_api/seed.py`. A senha está versionada no realm,
porque este ambiente é descartável por construção — e o sufixo `_local_only` não é enfeite: o
`preflight` recusa a subida fora de `ENVIRONMENT=local` com qualquer valor assim.

| Usuário | E-mail | Senha | Papel | O que alcança |
|---|---|---|---|---|
| `marina.farias` | `marina.farias@acme.com.br` | `portal_local_only` | `client_member` | o portal do cliente. **Não** alcança `/admin` |
| `helena.dias` | `helena.dias@biahflow.ai` | `portal_local_only` | `internal_admin` | tudo, incluindo as três telas de administração |
| `rafael.costa` | `rafael.costa@biahflow.ai` | `portal_local_only` | `internal_member` | o projeto, sem administrar |

**O Keycloak pede o usuário, não o e-mail.** O e-mail está aí porque é por ele que a pessoa
aparece no Mailpit (passo 3.5) e é ele que se digita ao convidar alguém (passo 3.11) — na tela de
login, quem entra é `marina.farias`.

Os `sub` do realm e os do seed são os mesmos UUIDs de propósito — é o que faz a linha do banco
já nascer ligada à conta do Keycloak, em vez de esperar o primeiro login para casar por e-mail.
`test_seed_matches_realm.py` reprova o build se os dois divergirem.

## 3. O passeio

### 3.1 O portal está fechado, e o login é SSO de verdade

Abra http://localhost:3000 sem sessão: você cai em `/login`. Clique em **Entrar com SSO da
empresa** — quem pede usuário e senha é o Keycloak, no endereço dele, e a senha nunca passa
pelo domínio do portal.

Entre como `marina.farias`.

### 3.2 O dashboard vem da API

Você deve ver **"Bom dia, Marina."** e quatro cartões com dado real do snapshot semeado:

- Status do projeto — "Em implementação", selo "No prazo", 68% concluído
- Próxima entrega — "Treinamento da operação · 18 set"
- ROI do projeto — "+142% · R$ 214.000 de retorno"
- Próxima reunião — "Comitê de projeto · 28 ago"

Nenhum desses números é fixo no código. Se a API cair, a tela mostra um painel de erro — nunca
um dashboard inventado.

### 3.3 A busca (Fase 6)

Clique na **lupa** do topo e digite:

| Digite | Deve achar |
|---|---|
| `excecoes` | o documento "Política de exceções financeiras.docx" **e** a pendência "Aprovar fluxo de exceções" — sem acento e sem caixa |
| `contrato` | os documentos por título **e** trechos, cada um com a página |
| `girassol` | um **trecho** do arquivo que veio do Drive (ver 3.9) |
| `zzzznada` | "Nada encontrado para …" — a busca não inventa resultado |

Clique num resultado: se for linha do read model, você cai na aba dela; se for **trecho de
documento**, o arquivo abre por URL assinada.

A busca é **lexical**: "quando posso cancelar" não acha "cláusula de rescisão". Quem responde
esse tipo de pergunta é o assistente.

### 3.4 As abas e a jornada

Percorra o menu lateral. Os títulos são "Cronograma do projeto", "Documentos do projeto",
"Reuniões do projeto", "Pendências do projeto" e "Resultados do projeto"; na Visão geral ficam
a barra "Você está aqui" e o roster de Funcionários Digitais. O contador ao lado de
"Pendências" é a contagem real de pendências abertas.

### 3.5 Notificação no sino e e-mail na caixa

O portal **não origina status**: quem avisa é o sync do Biahflow. Como o Biahflow vive em outro
repositório, dispare o mesmo `sync_snapshot` que o webhook chamaria — ou, para ligar o Biahflow
de verdade e ver a mudança chegar sozinha, siga
[`integracao-biahflow.md`](integracao-biahflow.md):

```bash
MARKER="passeio-$(date +%s)"
docker compose exec -T api python -c '
import json, sys
from portal_api.db.session import DbRole, get_session
from portal_api.integrations import biahflow
from portal_api.seed import SNAPSHOT_PATH
from portal_api.worker import send_project_digests

marker = sys.argv[1]
snapshot = json.loads(SNAPSHOT_PATH.read_text())
with get_session(role=DbRole.system) as session:
    biahflow.sync_snapshot(session, snapshot)          # 1. linha de base

snapshot["milestones"][0]["status"] = "done"
snapshot["documents"].append({
    "id": marker, "name": "Ata do comite " + marker, "type": "PDF",
    "author": "Biahflow", "link": "", "created_at": "2026-08-04T12:00:00+00:00",
})
with get_session(role=DbRole.system) as session:                  # 2. algo mudou
    project = biahflow.sync_snapshot(session, snapshot)
    project_id = str(project.id)

print("project_id:", project_id)
print("digests:", send_project_digests(project_id))
' "$MARKER"
```

**São dois syncs de propósito.** O primeiro sync de um projeto não notifica ninguém — sem uma
foto anterior não existe "mudou". O segundo muda um marco e acrescenta um documento, e é dele
que saem os avisos.

Aqui a saída foi `digests: {'sent': 5, 'notifications': 5}`. Então:

- No portal, o sino passa a `Notificações (N não lidas)` e o popover lista "Novo documento no
  projeto". Abrir marca como lidas **no banco** — um F5 não ressuscita o ponto vermelho.
- No Mailpit (http://localhost:8025), chega um e-mail para `marina.farias@acme.com.br` com
  assunto "Novo documento no projeto — Automação Financeira" e o corpo nomeando o documento:
  `- Novo documento no projeto: Ata do comite passeio-…`.

É **um e-mail por lote de sync**, não um por aviso.

> **O que foi medido, e vale mais que a regra.** Rodar o comando de novo com o **mesmo**
> `MARKER` devolveu `{'sent': 8, 'notifications': 16}` — o que parece contradizer a
> deduplicação, e não contradiz. Consultando a tabela, os 16 avisos eram `pending_opened` de
> **duas pendências novas**, abertas minutos antes pelas perguntas de lacuna do passo 3.6, e
> não do documento repetido: dele não nasceu linha nenhuma, que é o `dedupe_key` funcionando.
> O número de destinatários também cresce sozinho conforme você convida gente no passo 3.11.
> Em resumo: **o contador sobe porque algo novo aconteceu**, e conferir *o quê* é uma consulta:
>
> ```bash
> docker compose exec -T postgres psql -U portal_system -d portal -c \
>   "select kind, left(dedupe_key, 48), count(*) from portal.notification
>    where created_at > now() - interval '10 minutes' group by 1, 2"
> ```

### 3.6 O assistente cita, e declara lacuna quando não sabe

Abra o chat pelo balão flutuante **"Falar com a IA"**, no canto inferior direito — ou pelo
botão **"Perguntar à IA"** no topo de qualquer aba.

**Pergunta com evidência** — "Qual é o status do projeto?" — responde citando
`Status do projeto — 68% concluído`, e as citações aparecem embaixo da resposta.

**Pergunta sem evidência** — use `Cotação do níquel em Xangai?`. Você deve ver:

> Não encontrei evidências suficientes nos materiais deste projeto para responder com segurança.
> Registrei uma pendência para o time responsável retornar com a informação.

E a pendência nova aparece na aba Pendências, marcada como aberta pela IA.

> **Armadilha medida.** A versão com "Qual" na frente — *"Qual foi a cotação do níquel na bolsa
> de Xangai?"* — **não** produz lacuna num banco já usado, e isso não é defeito. O respondedor
> offline casa por termos de 4+ letras, e cada lacuna anterior gravou uma pendência cujo título
> embute a pergunta do cliente ("Responder dúvida do cliente: **Qual** é o ROI…"). O token
> `qual` casa com ela. Em banco limpo a pergunta original funciona; num banco acumulado, tire as
> palavras genéricas.

O `F5` é o teste que vale: a conversa volta com as mesmas citações, porque o turno está gravado
(ADR 0015) e não num `useState`.

### 3.7 Um documento enviado vira citação com link

Entre como `helena.dias` e vá a **`/admin/conhecimento`** ("O que o assistente pode citar
sobre …"). Envie um `.txt` com um termo que não exista em lugar nenhum, dê um título e clique
**Enviar e indexar**.

A tela responde *"Documento recebido. A indexação roda em segundo plano — atualize para ver o
estado"*. Atualize: a linha passa a `68 B · 1 trecho · indexado em <data>` com o selo
**Indexado**. Aqui isso levou **0,3 s** entre o upload e o `indexed_at` — o worker está ocioso
numa máquina de desenvolvimento; o e2e reserva 40 s porque lá a fila está cheia.

Agora entre como `marina.farias` e pergunte pelo termo: a resposta cita o documento, e a
citação é **um link** que abre o arquivo por URL assinada de vida curta.

### 3.8 O arquivo com assinatura de malware é barrado

Ainda em `/admin/conhecimento`, envie um `.txt` com a cadeia EICAR — o teste padrão da
indústria, inofensivo por construção. Monte-a em pedaços para o antivírus da sua própria
máquina não acusar o arquivo:

```
X5O!P%@AP[4\PZX54(P^)7CC)7}$ + EICAR-STANDARD-ANTIVIRUS-TEST-FILE + !$H+H*
```

A linha aparece como **"Barrado pela varredura: Eicar-Test-Signature · arquivo removido do
storage"**. No banco, `ingest_state = rejected` e `scan_state = infected`. Ele nunca vira
trecho, e o assistente nunca o cita.

> Sem `CLAMAV_HOST` configurado — que é o padrão local — os arquivos **bons** ficam com o selo
> "Indexado sem antivírus configurado", isto é, `scan_state = skipped`. Isso é a verdade sendo
> dita: um antivírus ausente não tem como afirmar que o arquivo está limpo. O EICAR é barrado de
> qualquer forma, porque o reconhecedor da cadeia de teste não depende do ClamAV.

### 3.9 Uma pasta do Drive entra pelo consentimento

No mesmo painel, bloco **GOOGLE DRIVE** → **Conectar Google Drive**. Contra o `drive-stub` o
consentimento é instantâneo: você volta para `/admin/conhecimento?...&drive=connected` sem tela
do Google.

O painel passa a listar as pastas — **Contratos do Projeto** e **Pessoal** —, cada uma com um
botão **Autorizar**. Autorize a primeira e sincronize. O painel passa a "2 documentos vindos do
Drive".

O que provar aqui: o stub tem, de propósito, um arquivo **fora** da pasta autorizada e um
**atalho** apontando para fora. Nenhum dos dois pode aparecer. O canário `girassol-cravado-42`
existe só dentro da pasta autorizada — procurá-lo na busca do cliente (3.3) é a prova de que o
conteúdo atravessou.

### 3.10 O número do cliente nasce de uma premissa e de eventos reais

Como `helena.dias`, vá a **`/admin/resultados`** ("Como … apura valor").

1. **Premissa**: preencha vigência, valor-hora e investimento e clique **Abrir vigência**.
   Premissa não se edita no lugar — fecha uma, abre outra.

   > Se a resposta for *"a vigência precisa começar…"*, já existe uma vigência aberta que começa
   > depois da data que você pôs. Use uma data posterior à vigência em curso.

2. **Chave de agente**: dê um nome e clique **Emitir chave**. O segredo `plk_…` aparece **uma
   única vez**; depois só existe o hash.

3. **Publique um evento** com ela (o agente vive fora deste repositório):

```bash
KEY="plk_…"                                     # a chave que a tela mostrou
PROJ="…"                                        # data-project-id, na mesma tela
EVENT=$(uuidgen)
for i in 1 2; do
  curl -s -X POST http://localhost:8000/api/v1/agent-events \
    -H "Content-Type: application/json" -H "X-Agent-Key: $KEY" \
    -d "{\"event_id\":\"$EVENT\",\"project_id\":\"$PROJ\",
         \"occurred_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"agent_key\":\"finance-agent\",
         \"time_saved_seconds\":3600,\"avoided_cost_cents\":5000,\"run_reference\":\"passeio\",
         \"outcome\":\"exception_handled\",\"human_intervention\":false}"; echo
done
```

O mesmo evento duas vezes devolve `accepted` e depois `duplicate` — os dois são 202, porque
reenvio não é erro e o produtor precisa distinguir um do outro.

4. Volte como `marina.farias` → aba **Resultados** → bloco **COMO CALCULAMOS**. Ele mostra
   período, eventos considerados, valor-hora vigente com a data de início, investimento mensal,
   a observação da premissa e a fórmula. Nenhum número ali é fixo: o dinheiro nasce na leitura,
   pela premissa vigente **no dia do evento**.

### 3.11 Um convite chega por e-mail e a pessoa entra

Como `helena.dias`, em **`/admin`** ("Quem enxerga …"): preencha Nome e E-mail e clique **Enviar
convite**. A tela confirma *"Convite enviado para …"* e a pessoa aparece na lista como **Convite
pendente**.

No Mailpit está o e-mail do Keycloak com o link de definir senha. Abrindo-o num navegador
anônimo, definindo a senha e entrando, a pessoa cai no dashboard do projeto — e vê **só** esse
projeto. O rótulo "Convite pendente" some quando ela confirma o endereço.

### 3.12 A negação é 404, nunca 403

O ponto que sustenta o resto. Como `marina.farias`, tente abrir http://localhost:3000/admin:
você recebe a página **404**, e não uma tela de "acesso negado" — o portal não confirma que
aquilo existe.

Do lado da API:

```bash
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/api/v1/me/dashboard   # 401, sem Bearer
```

E na rota de eventos, com uma chave inexistente e com um projeto que não é o da chave:

```
chave inexistente ............ 401   (opaco: nunca diz *qual* parte falhou)
projeto de outro tenant ...... 404   (não confirma que o projeto existe)
```

Um 422 de validação mostra `type`, `loc` e `msg` — e **não** devolve o corpo que você enviou.

## 4. O que você vai ver de diferente aqui, e por quê

Nada disto é defeito; é o ambiente local dizendo a verdade sobre si mesmo.

- **Sem `ANTHROPIC_API_KEY`** (o padrão do `.env.example`) o assistente é o `OfflineResponder`:
  determinístico, curto, cita evidência real e não obedece a instrução nenhuma. É o modo em que
  o CI roda. Com chave, entra o `AnthropicResponder` e a resposta muda de textura — a política
  de citação é a mesma para os dois.
- **Sem `VOYAGE_API_KEY`**, o embedding é uma projeção determinística por hashing: a citação
  continua correta, a recuperação fica mais grosseira.
- **Sem `CLAMAV_HOST`**, todo arquivo bom fica `skipped`, e a tela diz isso (ver 3.8).
- **Decisões não aparecem na busca**: o modelo existe desde a Fase 1 e não há aba que as mostre,
  então um resultado levaria a lugar nenhum (ADR 0024).
- **O banco local acumula.** Uploads, convites e conexões de Drive de execuções anteriores —
  suas e do `npx playwright test` — ficam. Buscar "contrato" pode devolver meia dúzia de
  arquivos de teste, e é isso que produz a armadilha de 3.6.

## 5. Armadilhas medidas

**`pytest` depois do e2e falha em dois testes.** `test_the_beat_tick_only_fans_out_enabled_connections`
e `test_a_client_only_sees_and_reads_their_own_notifications` contam linhas globais, e o e2e
deixa uma conexão de Drive habilitada e avisos para trás. Não é regressão — o CI sobe um
Postgres limpo. Para reproduzir o CI: `docker compose down -v` e suba só `postgres db-bootstrap`
antes do `pytest`.

**O Keycloak tem dois endereços, e isso é desenho.** `localhost:8080` para o navegador,
`keycloak:8080` para os contêineres. O primeiro é o `iss` de todo token; o segundo é por onde a
troca do código acontece (ADR 0010). Um erro de `invalid_token` costuma ser essa confusão —
`docs/runbooks/auth-failure.md` tem a tabela.

**Recomeçar do zero é `docker compose down -v`.** Sem o `-v` o volume do Postgres sobrevive, o
seed não refaz o que já existe, e o banco continua com o acúmulo da seção 4.

**A primeira subida é lenta** — build de duas imagens, import do realm e migrações. Da segunda
em diante, `docker compose up -d` sobe em segundos.

## Quando algo estiver errado

| Sintoma | Runbook |
|---|---|
| Login falha, `invalid_token`, "sem projeto atribuído" | `auth-failure.md` |
| Documento não vira citação | `document-ingestion-failure.md` |
| Pasta do Drive não sincroniza | `drive-sync-failure.md` |
| Evento de agente recusado | `agent-events-failure.md` |
| Assistente fora do ar | `ai-provider-failure.md` |
| O Biahflow real não chega ao portal | `integracao-biahflow.md` |
