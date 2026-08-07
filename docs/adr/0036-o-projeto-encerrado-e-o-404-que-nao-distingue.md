# ADR 0036 — O projeto encerrado, e o 404 que não distingue

**Status:** aceita — 06/08/2026
**Contexto:** Fase 6. Diferente das ADRs 0024/0026/0027/0033/0034: não é uma promessa de documento
que não se cumpria, é um **defeito de integração encontrado por alguém usando o produto**. Um
projeto foi arquivado no Biahflow e o portal continuou mostrando-o ao cliente como ativo.

## Contexto

Arquivar um projeto no Biahflow é `DELETE /api/v1/projects/{id}/`, que lá é *soft delete*:
`ArchiveModelViewSet.perform_destroy` chama `instance.archive()`, e `archive()` é
`instance.save(update_fields=["archived_at", "updated_at"])`.

Sendo um `save()`, o `post_save` dispara e `portal.emit()` sai. **O webhook chegou aqui, e a
assinatura passou.** O que falhou foi o passo seguinte, o *pull*:

```
httpx.HTTPStatusError: Client error '404 Not Found' for url
  '.../api/v1/portal/projects/1/snapshot/'
```

A rota de snapshot de lá filtrava `Project.objects.filter(archived_at__isnull=True)`. Arquivar o
projeto fazia o snapshot dele **deixar de existir**, o webhook respondia 500 e nada era gravado.
Enquanto durasse o arquivamento, todo webhook daquele projeto batia no mesmo 404 — inclusive os
dos filhos —, então o read model ficava parado no último estado bom.

O filtro não estava lá por descuido: é o mesmo do `get_queryset` do `ArchiveModelViewSet`, onde
está certo, porque quem *lista* não quer ver arquivado. Copiado para uma rota de reconciliação
servidor-a-servidor, ele produziu o oposto do pretendido.

## O que a medição corrigiu no diagnóstico

Duas coisas que a primeira leitura errou, e que mudam a severidade:

**O escopo é só o projeto.** Arquivar um documento, marco, reunião ou pendência **já funcionava**
nos dois sentidos — o item sai do snapshot, e `sync_snapshot` substitui as listas por inteiro a
cada webhook. Só o projeto caía no buraco, porque só ele é a chave da própria rota.

**E era reversível.** O `unarchive` também é um `save()`, então restaurar o projeto emitia,
o snapshot voltava a existir e o portal reconciliava sozinho. Medido nos dois sentidos. Não era
perda de dado; era divergência enquanto o projeto estivesse arquivado — que continua sendo o
defeito, porque é justamente o intervalo em que o cliente vê como ativo um projeto encerrado.

## Decisão

### A fonte declara o fato; o portal não infere de um código de erro

Do lado do Biahflow, a rota passa a servir o projeto arquivado e o snapshot ganha
`project.archived_at`. O 404 volta a significar **uma coisa só** — não existe —, que é o que
torna possível distinguir os dois casos. Os querysets dos filhos continuam filtrando arquivados,
e isso está certo: arquivar o projeto não cascateia, então o histórico continua vindo inteiro.

A alternativa era o portal tratar 404 como "arquivado". Rejeitada: 404 também é id inexistente e
base errada, e agir destrutivamente sobre um erro ambíguo é como se apagam dados de cliente por
engano. Além disso inverteria o princípio das ADRs 0006/0008 — o portal não origina status, e
deduzir encerramento de um código HTTP é originá-lo.

### Coluna própria, não um valor de `ProjectStatus`

`ProjectStatus` descreve o andamento: `discovery`, `in_implementation`, `live`, `paused`.
Arquivamento é ortogonal — um projeto encerrado *tinha* um andamento quando acabou. Acrescentar
`archived` ao enum faria as duas informações disputarem a mesma coluna, e a segunda apagaria a
primeira: depois de restaurar, ninguém saberia dizer se o projeto estava pausado ou em
implementação quando foi arquivado.

`NULL` significa ativo, e o sync **devolve a coluna a `NULL`** quando o Biahflow restaura. Não é
detalhe: a interface de lá arquiva e desarquiva por item, e um campo que só soubesse ir deixaria
projetos eternamente marcados como encerrados depois de um arquivamento desfeito — o mesmo
caminho sem volta que esta ADR existe para fechar, com outro nome.

### Visível e marcado, com a escrita fechada — 409

O projeto encerrado continua acessível, com selo "Projeto encerrado". Nada do cliente desaparece,
pelo argumento da ADR 0017: o documento é a evidência de uma citação já dada, e tirá-lo do
alcance tornaria uma resposta antiga impossível de conferir. O que fecha é a escrita: `POST /chat`
e `POST /me/pendings/{id}/comments`.

**O código é 409, e a escolha é a decisão mais delicada desta fatia.** 404 seria mentira, e
mentira cara: neste contrato ele significa exatamente a ausência de vínculo, é a única resposta
que `test_authorization.py` verifica em toda rota escopada (ADR 0035), e usá-lo aqui tornaria
"você não tem acesso" indistinguível de "este projeto acabou" — um cliente legítimo passaria a
receber a mesma resposta de um estranho. 403 não existe nesta API. O precedente é o 429 da quota
(ADR 0022), que também recusou sem ser sobre permissão: **o código sai do motivo**, e o motivo
aqui é o estado do recurso, que é o que 409 nomeia.

`ARCHIVED_PROJECT_ERROR` fica fora de `CLIENT_ERRORS` de propósito — aquele dicionário é o que
*toda* rota de cliente responde, e a maioria continua servindo um projeto arquivado. E
`_refuse_when_archived` é chamado **depois** do 404: a recusa confirma que o projeto existe, então
só pode acontecer depois de estabelecido o vínculo de quem pergunta. Há teste para as duas
metades, e a segunda é a que erraria em silêncio.

O feedback em mensagem continua aberto: avaliar uma resposta já dada é sobre o passado.

### `biahflow.snapshot_missing`

O 404 no `fetch_snapshot` deixa de virar 500 com traceback anônimo e passa a ser evento nomeado,
com linha no `alerts.md` no mesmo commit (a guarda é bidirecional, ADR 0034). A causa comum foi
resolvida do outro lado; o que sobra é id que nunca existiu ou `BIAHFLOW_BASE_URL` apontando para
outra base, e aí não há nada a reconciliar — nomear e sair é mais honesto que estourar.

## Consequências

- O Biahflow ganha um campo no contrato de snapshot. É aditivo: `sync_snapshot` lê com `.get`, e
  ausência da chave significa ativo, então um Biahflow anterior a esta fatia continua sincronizando.
- Uma rota do Biahflow passa a expor projeto arquivado. É servidor-a-servidor com Bearer, e o
  conteúdo é o mesmo que ela já servia no dia anterior ao arquivamento.
- 409 passa a existir na API. `test_openapi_contract.py` continua exigindo que ninguém declare
  403, e essa propriedade não muda.
- Uma pergunta em projeto encerrado **consome janela de taxa** antes de ser recusada, porque
  `chat_limit.consume` roda antes de haver projeto. É o mesmo preço que o 404 já pagava (ADR 0021),
  e pelo mesmo motivo.

## O que fica em aberto

**Não há `post_delete` em lugar nenhum do Biahflow** — os 15 receivers de `signals.py` são
`post_save`. Então *hard* delete não avisa: `retention.py` apaga documentos de vez, e exclusões
em cascata idem. Fora do escopo por decisão, registrado como tropeço no
`integracao-biahflow.md`, e é fatia própria porque mexer na retenção dos dois lados junto é
escopo demais para um passo.

`DigitalEmployee` também não tem receiver — cadastrar um funcionário digital não emite, e ele só
chega ao portal de carona no próximo save de outra coisa. Mesmo tratamento.
