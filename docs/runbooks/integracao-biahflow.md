# Runbook — ligar o portal ao Biahflow

O `passeio-local.md` ensina a **simular** o Biahflow, chamando `sync_snapshot` por dentro do
contêiner. Este runbook liga o Biahflow de verdade: uma mudança lá vira, sozinha, uma mudança na
tela do cliente aqui.

Os dois lados já implementam o contrato (ADR 0006 aqui, ADR 0003 lá) — o que falta é
configuração e um passo de acesso. **Percorrido de ponta a ponta em 05/08/2026 e de novo em
06/08/2026** contra as duas pilhas locais; os tropeços abaixo são os que apareceram nas execuções,
não hipóteses. A segunda passagem corrigiu o tropeço (c), que já não era verdade, e acrescentou o
(d). Em 07/08/2026 os tropeços (d) e (f) foram **consertados** (ADR 0037), e o (f) encolheu ao ser
medido: exclusão de filho não é alcançável pelo produto, ao contrário do que ele afirmava.

## Como a corrente funciona

```
Biahflow: alguém salva algo
   → signal dispara portal.emit(), assina o corpo com HMAC-SHA256
   → POST {PORTAL_WEBHOOK_URL}   (thread daemon, após o commit, 5 s de timeout)
Portal:  confere a assinatura  → 401 se não bater
   → GET {BIAHFLOW_BASE_URL}/portal/projects/{id}/snapshot/  com Bearer
   → sync_snapshot() grava o read model e produz as notificações
```

O webhook é **fino** (`event`, `object_type`, `project_id`): quem carrega o dado é o snapshot
que o portal puxa em seguida. É por isso que uma entrega perdida não perde informação — a
próxima entrega traz o estado inteiro.

### O que o portal passou a ler do snapshot e o Biahflow talvez ainda não envie

| Campo | Onde | Desde | Ausente significa |
|---|---|---|---|
| `pendencias[].priority` | `low` / `medium` / `high` | ADR 0029 | `medium` |
| `artifact_accepted_at` | raiz do snapshot, ISO 8601 ou `null` | ADR 0041 (FDD 031 de lá) | degrau do funil não carimbado |

Opcional de propósito: o portal não pode exigir campo novo da outra ponta, e a ausência tem de
continuar significando o padrão em vez de derrubar o sync. Enquanto o Biahflow não enviar, toda
pendência espelhada fica em `medium` — a tela mostra a mistura só na stack local, porque o seed
a traz.

Quem originar é o Biahflow: **não há como mudar a prioridade pelo portal**, e não deve haver,
pela mesma razão que não há CRUD de status aqui (ADR 0006/0008).

O `artifact_accepted_at` é a data da **primeira** aceitação daquele cliente (`sent → accepted`
no `Artifact` de lá), e é só isso que atravessa — nem tipo, nem título, nem conteúdo, nem
valor. Do lado do Biahflow ele nasce em `portal._artifact_accepted_at`, com `post_save` de
`Artifact` emitindo webhook **só** em `ACCEPTED`. Duas coisas para não estranhar ao percorrer o
caminho: aceitar um artefato preso a uma **oportunidade sem projeto** não emite nada (o `emit`
de lá não faz nada sem `project_id`, e o fato chega inteiro no primeiro snapshot depois que o
projeto nascer, porque o campo é calculado sobre o cliente); e este lado **não desfaz** o
carimbo se o artefato for arquivado depois — o cliente aprovou naquele dia, e o funil não tem
`UPDATE` para ninguém.

## 1. Os pares de segredo

Quatro valores, dois deles **idênticos dos dois lados**:

| Biahflow (`.env`) | Portal (`.env`) | O quê |
|---|---|---|
| `PORTAL_WEBHOOK_SECRET` | `BIAHFLOW_WEBHOOK_SECRET` | **mesmo valor** — HMAC do corpo |
| `PORTAL_READ_TOKEN` | `BIAHFLOW_READ_TOKEN` | **mesmo valor** — Bearer do snapshot |
| `PORTAL_WEBHOOK_URL` | — | para onde o Biahflow avisa |
| — | `BIAHFLOW_BASE_URL` | de onde o portal lê |

```bash
openssl rand -hex 32     # uma vez para o segredo, outra para o token
```

No local, com as duas pilhas em projetos Compose diferentes, os endereços atravessam pelo host:

```ini
# Biahflow/.env
PORTAL_WEBHOOK_URL=http://host.docker.internal:8000/api/v1/integrations/biahflow/webhook

# portal/.env
BIAHFLOW_BASE_URL=http://host.docker.internal:19000/api/v1
```

Reinicie os dois: `docker compose up -d api` de cada lado.

> **Segredo vazio não é "sem verificação".** `verify_signature` **falha fechado**: sem
> `BIAHFLOW_WEBHOOK_SECRET`, todo webhook responde 401. É o comportamento certo, e é a primeira
> coisa a conferir quando "não chega nada".

## 2. Os tropeços (todos medidos)

**a) `DJANGO_ALLOWED_HOSTS` precisa aceitar o nome que o contêiner usa.** O portal chama o
Biahflow com `Host: host.docker.internal`; o Django recusa host desconhecido com **400**, e o
portal transforma isso num **500** no webhook. O sintoma engana: um `curl` da sua máquina
funciona (ele manda `Host: localhost`) enquanto o contêiner falha.

```ini
# Biahflow/.env
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,host.docker.internal
```

**b) Migrações pendentes derrubam o snapshot.** Com `0027_meeting_meeting_url` por aplicar,
`build_snapshot` levanta `ProgrammingError: column core_meeting.meeting_url does not exist` e o
endpoint responde 500. Antes de qualquer coisa:

```bash
cd ../biahflow-portal && docker compose exec api uv run python manage.py migrate
```

**c) A jornada dispara webhook — isto aqui já foi um tropeço e não é mais.** `_emit_project_phase`
e `_emit_project_deliverable` existem em `backend/apps/core/signals.py`, ambos com um
`if created: return`. Concluir ou avançar uma fase é *update*, não criação, então **avisa o
portal**: medido nos dois sentidos, `locked → active` e `active → locked`, com a fase e o
`current_phase` chegando sozinhos. O mesmo vale para o entregável (`pending → delivered`).

O `if created` não é descuido, e o comentário de lá explica: `journey.materialize_journey` cria
fases e entregáveis num laço de `.objects.create()`, então sem o guarda **criar um projeto**
dispararia dezenas de webhooks, cada um provocando um snapshot inteiro — todos redundantes com o
`_emit_project` do mesmo commit.

> *Corrigido em 06/08/2026, na segunda passagem. Este item dizia que não havia receiver para
> `ProjectPhase` nem para `PhaseDeliverable`, e que concluir fase não avisava o portal —
> "verificado, zero webhooks". Passou a ser falso quando o lado do Biahflow ganhou os dois
> receivers. O nome também estava errado, e o erro é instrutivo: `PhaseDeliverable` é o
> **template** global de entregável, e não ter receiver nele está certo — ele não pertence a
> projeto nenhum, logo não há `project_id` para emitir. Quem carrega o estado no projeto é
> `ProjectDeliverable`, e é esse que tem receiver.*

**d) O funcionário digital não disparava webhook — resolvido na ADR 0037.** Não havia receiver de
`post_save` para `DigitalEmployee` em `signals.py` — a forma exata do que o (c) descrevia.
Cadastrar um funcionário digital **não avisava o portal**: medido, zero webhooks. O dado não se
perdia — o próximo save de qualquer um dos outros trazia o time digital inteiro no snapshot
seguinte —, mas o bloco "Seu Time Digital" ficava desatualizado na tela do cliente por tempo
indeterminado, e nada ficava vermelho.

> *Ampliado em 07/08/2026, ao consertar. Este item falava só em **cadastrar**, e o caso pior era
> outro: **arquivar**. `archive()` tira a linha do snapshot, então o funcionário digital arquivado
> continuava no roster do cliente — o portal exibindo alguém que a fonte da verdade já tinha
> tirado, que é mais errado do que exibir de menos. Os três caminhos (criar, editar KPI, arquivar)
> emitem desde a ADR 0037.*

**e) Arquivar o *projeto* travava o portal — resolvido na ADR 0036, e vale saber o que era.**
Arquivar emite (o `archive()` de lá é um `save()`), mas a rota de snapshot filtrava
`archived_at__isnull=True`: o portal vinha buscar o estado novo e levava **404**, que ele não tem
como distinguir de "este id nunca existiu". O webhook respondia 500, nada era gravado, e a tela do
cliente seguia mostrando como **ativo** um projeto encerrado — por todo o tempo que o
arquivamento durasse, porque cada webhook seguinte batia no mesmo 404.

Hoje o snapshot responde 200 e carrega `project.archived_at`; o portal marca "Projeto encerrado",
mantém a leitura e recusa escrita com 409. Se você vir o sintoma de novo, é `BIAHFLOW_BASE_URL`
apontando para outra base — os ids não batem entre instâncias, e aí o 404 é verdadeiro. O portal
emite `biahflow.snapshot_missing` nesse caso, em vez de 500.

Duas coisas medidas junto, que delimitam o problema: **arquivar item individual** (documento,
marco, reunião, pendência) sempre funcionou, nos dois sentidos, porque o sync substitui as listas
inteiras a cada webhook; e **desarquivar o projeto sempre destravou sozinho**, porque o
`unarchive` também é um `save()` e o snapshot volta a existir.

**f) Exclusão definitiva do projeto não avisava ninguém — resolvido na ADR 0037, e o diagnóstico
encolheu ao ser medido.** Não havia receiver de `post_delete` nem de `pre_delete` em `signals.py`
— os quinze eram `post_save`.

> *Corrigido em 07/08/2026, ao percorrer o outro lado. Este item dizia que "onde o Biahflow apaga
> de verdade (`retention.py`, e qualquer cascata de `queryset.delete()`), o portal não fica
> sabendo", e a parte alarmante não se sustenta: `retention.executar()` só alcança linha **já
> arquivada** (`archived_at` + N dias), e arquivada ela já saiu do snapshot e já foi propagada pelo
> webhook do arquivamento. Quando a retenção apaga de vez, o portal já removeu. Some-se a isso que
> o `DELETE` da API de lá **arquiva** (os nove viewsets são `ArchiveModelViewSet`) e que o Django
> admin registra só `User` e `ScheduledJobRun`: exclusão de filho não é alcançável pelo produto.*

O que sobrava era o **projeto**, apagado por shell ou migração de dados — e aí o prejuízo era total
e permanente: nenhum webhook saía, não haveria evento seguinte daquele projeto porque não há mais
projeto, e o portal seguia mostrando ao cliente um projeto morto **como ativo**. Hoje o Biahflow
emite `("deleted", "project", id)` — o único `post_delete` de lá —, o portal marca a linha, mostra
"Projeto removido na origem", mantém o histórico e recusa escrita com 409. O evento daqui é
`biahflow.project_deleted`.

**Exclusão de filho continua sem aviso, agora de propósito.** Se um dia a interface de lá passar a
apagar marco ou documento de verdade, isto volta a ser defeito — e a correção precisa de dedupe por
transação, senão uma cascata vira dezenas de buscas de snapshot. O argumento está na ADR 0037.

## 3. Prove que o caminho está aberto, antes de esperar mágica

```bash
TOKEN=$(grep '^BIAHFLOW_READ_TOKEN=' .env | cut -d= -f2)

curl -s -o /dev/null -w "sem token: %{http_code}\n" \
  http://localhost:19000/api/v1/portal/projects/1/snapshot/          # 401
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:19000/api/v1/portal/projects/1/snapshot/ | head -c 200   # o JSON
```

Depois provoque um webhook salvando qualquer coisa no Biahflow (pela tela, ou pelo ORM) e leia
os dois lados:

```bash
# de lá: silêncio é bom; "Falha ao entregar webhook" é o diagnóstico
cd ../biahflow-portal && docker compose logs api --since 2m | grep -i webhook

# daqui: 200 é sucesso; 401 é segredo, 500 é (a), (b) ou a desconexão do parágrafo abaixo
docker compose logs api --since 2m | grep "integrations/biahflow"
```

> **Pelo ORM, segure o processo.** `portal.emit()` roda numa `threading.Thread(daemon=True)`
> depois do commit, e um `manage.py shell -c` termina antes de a thread completar o POST: o
> webhook **não sai, e não há erro nenhum** — silêncio dos dois lados, idêntico ao de um
> `PORTAL_WEBHOOK_URL` vazio. Um `time.sleep(7)` no fim do script resolve. Pela tela isso não
> acontece, porque o processo do `runserver` continua vivo.

> **Um 500 isolado no primeiro webhook pode não ser (a) nem (b).** Medido em 06/08/2026:
> `httpx.RemoteProtocolError: Server disconnected without sending a response`, levantado dentro de
> `fetch_snapshot` — ou seja, **a assinatura já tinha passado** e o que falhou foi a leitura do
> snapshot, com o `runserver` derrubando a primeira conexão depois de ocioso. O save seguinte
> passou limpo. Não perde dado, pela razão de sempre: o webhook é fino, e o próximo traz o estado
> inteiro. Se repetir em todo webhook, aí é (a) ou (b).

## 4. O passo que não é configuração: quem enxerga a organização nova

O primeiro sync cria **organização e projeto sem membership nenhuma** — o projeto fica invisível
para todo mundo, inclusive para a equipe interna, cujo vínculo org-wide é de outra organização.
E `/admin` não resolve: administrar um projeto exige já ser `internal_admin` nele.

Por isso existe o bootstrap (ADR 0025), que roda **uma vez por organização**:

```bash
docker compose exec api python -m portal_api.grant_access \
  --email helena.dias@biahflow.ai \
  --organization biahflow-client-1 --role internal_admin
```

O slug da organização é `biahflow-client-<id do cliente no Biahflow>`; o do projeto é
`biahflow-<id do projeto>`. Para descobrir:

```bash
docker compose exec -T postgres psql -U portal_system -d portal -c \
  "select o.slug, o.name, p.slug, p.name from portal.organization o
     join portal.project p on p.organization_id = o.id where o.slug like 'biahflow-client-%'"
```

O comando é idempotente e **recusa** quando a organização já tem `internal_admin` — a partir daí
o caminho é o `/admin`, que é auditável e tem tela. A partir daí, também, o cliente entra por
convite como sempre.

## 5. A prova que vale

Com tudo no lugar: salve algo no Biahflow e entre no portal como a pessoa que recebeu o
bootstrap. Ela deve cair na organização nova (`Igreja Cartas Vivas / Teste`, no ambiente onde
isto foi escrito), com a barra "Você está aqui" mostrando as sete fases vindas de lá e o selo
**"Sincronizado com o Biahflow"** no cartão de status.

O aviso no sino e o e-mail de resumo seguem as regras de sempre (ADR 0012): o **primeiro** sync
de um projeto não notifica ninguém — sem foto anterior não existe "mudou" —, e o e-mail chega no
Mailpit **do portal** (`:8025`), não no do Biahflow (`:19025`).

## Quando não funcionar

| Sintoma | Onde olhar |
|---|---|
| Nada acontece, nenhum log dos dois lados | `PORTAL_WEBHOOK_URL` vazio, ou o Biahflow não foi reiniciado |
| Salvei pelo ORM e não saiu nada, nem erro | o `shell` terminou antes da thread daemon; veja o bloco da seção 3 |
| `Falha ao entregar webhook … 401` | os dois segredos não são o mesmo valor |
| `Falha ao entregar webhook … 500` | veja o log daqui: (a) `ALLOWED_HOSTS`, (b) migração, ou desconexão isolada |
| 500 uma vez só, `RemoteProtocolError` | primeira conexão ao `runserver` ocioso; salve de novo antes de investigar |
| 200 no webhook e nada muda na tela | o projeto sincronizou noutra organização — confira os slugs e o bootstrap |
| O time digital não aparece | tropeço (d): `DigitalEmployee` não emite; salve outra coisa para forçar |
| `biahflow.snapshot_missing` no log daqui | o Biahflow respondeu 404 no snapshot: id de outra instância, quase sempre `BIAHFLOW_BASE_URL` |
| Arquivei o projeto e continua na tela como ativo | o portal não recebeu o `archived_at`: confira se aquele Biahflow já tem a mudança da ADR 0036 |
| Apaguei o projeto e continua na tela como ativo | o `deleted` se perdeu (entrega é best-effort e sem retentativa) — não virá outro; marque a linha à mão |
| Apaguei um **item** e continua na tela | é (f), e é esperado: só o projeto emite na exclusão. Arquive em vez de apagar, que emite |
| Cadastrei/arquivei funcionário digital e nada mudou | era (d), resolvido na ADR 0037; se persistir, aquele Biahflow ainda não tem a mudança |
| `biahflow.project_deleted` no log daqui | o Biahflow apagou o projeto de vez. Não é falha — veja a linha em `alerts.md` antes de agir |
| Login, sessão, "sem projeto atribuído" | `auth-failure.md` |
