# ADR 0037 — O que o Biahflow não conta ao portal

**Status:** aceito
**Data:** 07/08/2026
**Fase:** 6

## Contexto

A ADR 0036 fechou o tropeço (e) do `integracao-biahflow.md` — arquivar um projeto travava o read
model do portal — e deixou dois itens em aberto, como "fatia própria": não há `post_delete` em
lugar nenhum do Biahflow, e `DigitalEmployee` não tem receiver. Esta ADR é essa fatia, e é a
sétima repetição do padrão das ADRs 0024/0026/0027/0033/0034/0035/0036.

A promessa quebrada, desta vez, está escrita no outro repositório e na primeira pessoa. A ADR 0003
de lá diz, em negrito: **"o que entra no snapshot precisa de emissor, sob pena de o portal exibir
um estado que já mudou"**. `digital_employees` entra no snapshot e não tinha emissor nenhum.

## O que a medição corrigiu no diagnóstico

A ADR 0036 escreveu que "`retention.py` apaga documentos de vez, e exclusões em cascata idem",
sugerindo um cliente olhando para documentos que já não existem. Percorrendo o Biahflow, a parte
alarmante não se sustenta:

| O que a ADR 0036 supôs | O que está no código de lá |
|---|---|
| `DELETE` na API apaga | Os nove viewsets que o portal enxerga são `ArchiveModelViewSet`; `perform_destroy` chama `archive()`, que é um `save()` e **emite** |
| Django admin permite exclusão em massa | `admin.py` registra `User` e `ScheduledJobRun`. Nenhuma entidade de projeto |
| A retenção apaga documento que o cliente ainda vê | `retention.executar()` só alcança linha **já arquivada** — e arquivada ela já saiu do `build_snapshot`, propagada pelo webhook do arquivamento |

Sobra **um** caminho de exclusão real: `Project.delete()` por shell ou migração de dados. E aí o
prejuízo é total e permanente — o portal fica com um projeto morto marcado como **ativo para
sempre**, porque nenhum evento sai e não haverá evento seguinte daquele projeto.

O item com dente é o outro, e nem é sobre exclusão: cadastrar, editar KPI e **arquivar** um
funcionário digital não avisavam o portal. Arquivar é o pior dos três, porque tira a linha do
snapshot: o roster do cliente exibia alguém que a fonte da verdade já considerava fora, até o
próximo salvamento de outra coisa naquele projeto. `test_digital_employee.py` de lá não mencionava
`emit`.

De quebra: o emissor manda `event` e `object_type` em **todo** webhook desde a ADR 0006, e este
lado nunca leu nenhum dos dois — `main.py` lia só `project_id`. É a forma da guarda da ADR 0033
("o que ninguém consome é pergunta para a API") na direção de **entrada**, onde não há guarda
porque o produtor mora noutro repositório.

## Decisão

### O emissor que faltava, e o único `post_delete` (lado do Biahflow)

`post_save` de `DigitalEmployee`, na forma dos oito irmãos e sem guarda de `created` — o roster é
cadastrado um a um pela tela, não materializado em laço como a jornada.

`post_delete` de `Project`, e **só** dele. Exclusão de filho não é alcançável pelo produto (a
medição acima), e registrá-la teria custo medido: numa cascata o coletor do Django apaga filho
primeiro e `on_commit` roda na ordem de registro, então cada filho agendaria um webhook **antes**
do webhook do projeto, cada um provocando uma busca de snapshot que já responde 404. Um projeto
inteiro sai de lá como **um** aviso, e há teste que reprova se isso mudar. Registrado como emenda
na ADR 0003 de lá.

### O portal lê `event`, e é a primeira vez

`event: "deleted"` + `object_type: "project"` **não** busca snapshot. Não é otimização: depois da
exclusão não existe snapshot, e o 404 que a busca traria não distingue "foi apagado" de "id de
outra base" — a ADR 0036 um nível acima. O fato só existe no corpo do webhook, que é assinado por
HMAC, então é o corpo que precisa ser lido.

### Coluna própria, de novo, e pelo motivo seguinte

`source_deleted_at` é separada de `archived_at` pelo argumento da ADR 0036 levado um passo adiante.
Lá as duas perguntas eram "qual o andamento" e "acabou". Aqui são "acabou" e "ainda existe na
fonte". A diferença que decide é a **porta**: arquivamento vem no snapshot e o `sync_snapshot` o
reescreve a cada passagem — é assim que restaurar funciona —, enquanto exclusão chega só pelo
webhook. Numa coluna só, o sync apagaria o fato no dia em que um snapshot voltasse a existir para
aquele id; e um snapshot que volta a existir não é uma restauração, é outro projeto reusando o
número.

`sync_snapshot` **não** toca em `source_deleted_at`, e a ausência é a decisão.

### Visível e marcado, com a escrita fechada — 409, como antes

`_refuse_when_archived` virou `_refuse_when_read_only` e cobre os dois motivos com o mesmo código e
`detail` diferente: quem lê o corpo é a tela, e "encerrado" e "removido na origem" não são frases
intercambiáveis para o cliente — a primeira tem volta pela interface do Biahflow, a segunda não tem
nenhuma. A exclusão é verificada primeiro por ser o estado mais forte, e a tela usa a mesma ordem,
de propósito: se as duas divergirem, o portal passa a dizer "encerrado" na barra e "removido" no
chat sobre o mesmo projeto.

**O portal não apaga nada.** Documento é a evidência de uma citação já dada, e apagar tenant é
decisão de pessoa registrada numa linha e executada pelo worker (ADR 0017) — nenhuma rota HTTP
apaga nada aqui, e um webhook não é exceção a isso. Quem quiser sumir com o projeto usa
`/admin/organizacao`.

### `biahflow.project_deleted`

Evento nomeado com linha no `alerts.md` no mesmo commit (a guarda da ADR 0034 é bidirecional).
Limiar de "qualquer ocorrência", e o argumento está na linha: exclusão não tem volta do outro lado,
então se foi engano o read model daqui é a única cópia que sobrou.

## Consequências

- O Biahflow ganha dois receivers. O de `DigitalEmployee` aumenta o número de webhooks na
  proporção do que se mexe no roster, que é pouco e é o ponto.
- Um projeto removido continua **visível** ao cliente, marcado e sem escrita. É deliberado, e é a
  mesma simetria da ADR 0017.
- `event` passa a ter um leitor. Um webhook antigo (sem o campo, ou com `updated`) continua caindo
  no caminho de sempre — a mudança é aditiva nos dois sentidos.
- A entrega do webhook continua best-effort e sem retentativa, e agora isso **pesa mais**: um
  `deleted` perdido é definitivo, porque não haverá evento seguinte daquele projeto. Um `updated`
  perdido o próximo salvamento corrige; este não. É o custo mais afiado da fatia, e a recuperação é
  a de sempre — backfill manual, que aqui significa alguém marcar a linha.

## O que fica em aberto

**Exclusão de filho continua sem aviso** (marco, documento, reunião, pendência, fase, entregável,
tarefa, funcionário digital) — agora com o argumento medido de por quê: pela interface e pela API
do Biahflow ninguém consegue provocá-la, e shell e migração de dados conseguem. Se algum dia um
caminho de produto apagar filho de verdade, a decisão muda, e aí o dedupe por transação que esta
ADR evitou passa a ser necessário.

**O portal não sabe reconciliar um projeto que morreu sem aviso.** Se o `deleted` se perder, a
linha fica marcada como viva para sempre. Uma varredura periódica que perguntasse ao Biahflow por
todos os ids conhecidos resolveria — e é fatia própria, porque envolve decidir o que fazer com um
404 que pode ser indisponibilidade.
