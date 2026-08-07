# ADR 0041 — O sétimo degrau, e a régua que ele destrava

**Status:** aceito
**Data:** 07/08/2026
**Fase:** 7 — fecha o critério de aceite (3) da FDD 020, e é a fatia gêmea da FDD 031 do Biahflow

## Contexto

A FDD 020 tem seis critérios de aceite. Cinco estão marcados **Feito**; um estava marcado
*"Adiado, e não esquecido"*, e a razão não era falta de tempo — era falta de produtor. Está
escrita no enum, desde a ADR 0039:

> **`artifact_accepted` não está aqui de propósito.** A RFC o lista, mas o snapshot do
> Biahflow não carrega nada de artefato […] Declará-lo agora criaria um degrau que nada
> carimba — a forma exata do painel sem escritor que a ADR 0033 achou. **Ele entra quando o
> outro lado o afirmar.**

O outro lado tinha o dado inteiro e não o afirmava. `Artifact` existe lá desde a FDD 016 com
`sent → accepted`, `decided_at` carimbado no `save()`, o e-sign fechando o contrato sozinho
quando o signatário assina, e a taxa de aceitação já calculada em `views.py`. O docstring do
modelo diz para que ele serve — *"permite medir onde a jornada trava entre uma etapa e a
seguinte"*, que é literalmente esta RFC. O que faltava era atravessar: `build_snapshot` não
levava artefato nenhum e `signals.py` não tinha receiver de `Artifact`.

É a forma da ADR 0037 um degrau antes. Lá a promessa quebrada era "o que entra no snapshot
precisa de emissor"; aqui o fato **não entrava no snapshot**, então não havia sequer o que
emitir.

## Decisão

### O que o degrau destrava não é um item de lista — é a régua

Esta é a parte que muda o valor da fatia, e ela não estava no plano de ninguém.

A RFC 001 diz qual é a medida: *"a régua que importa não é a taxa de conversão agregada, é o
**time-to-first-value**: quanto o cliente demora **do ganho** até a primeira aprovação e até o
primeiro ROI visto"*. E o `_anchor` da ADR 0040 nunca teve o ganho: sua cadeia é o último
carimbo, depois o convite (`MIN(membership.created_at)`), depois a criação da organização.

Sem este degrau, um cliente ganho em 12 de junho e convidado em 30 de julho contava os dias a
partir de **30 de julho** — de modo que dezoito dias de demora **nossa**, entre fechar o
contrato e convidar a pessoa, *encurtavam* o número em vez de aparecer nele. O funil escondia
exatamente o tipo de atraso que ele existe para tornar visível.

Com o carimbo, a âncora daquele cliente passa a ser 12 de junho, e `MAX(reached_at)` continua
fazendo o resto: assim que qualquer degrau mais recente é alcançado, ele volta a mandar. O
degrau não acrescenta uma pergunta — corrige o zero de todas as outras.

### Ele entra **primeiro** na escada

`LADDER` é a ordem em que a jornada alcança os degraus, e a aprovação precede o projeto:
aceitar o contrato é o que faz o projeto existir. Pôr o degrau em qualquer outro lugar seria
mentir sobre a jornada para evitar a consequência de ser o primeiro — e a consequência tem
resposta própria, abaixo.

### O `blame` é **sempre nosso**, como o do entregável

`artifact_accepted` e `first_deliverable_delivered` são afirmação do Biahflow, e o portal não
origina status (ADR 0006/0008). No degrau da aprovação há um argumento a mais e mais forte: a
aprovação acontece do outro lado, o portal **não a hospeda e não tem como coletá-la**. Nada
que o cliente faça nesta tela move o degrau, então rotulá-lo "travou no cliente" seria a
confusão que a RFC proíbe em voz alta.

O limiar é o de trinta dias, o mesmo do entregável, pelo argumento que o `config.py` já
escreve: cobrar cedo o que é sempre nosso transforma o radar de engajamento num relatório de
execução, que é o que a saúde do projeto já faz.

### A corroboração, e é ela que impede a medição de nascer cega — de novo

Sendo o primeiro da escada, um degrau sem carimbo seria o degrau atual de **toda** organização
anterior à FDD 031 do Biahflow — isto é, de todas. A tela nasceria mandando registrar o
contrato de clientes que estão em produção há meses. É a repetição exata do susto que a ADR
0040 mediu com o `first_login`, e desta vez ele foi previsto em vez de descoberto, porque
aquela ADR deixou o padrão escrito.

A saída é a mesma em forma e diferente em natureza: **projeto vivo no Biahflow significa
negócio fechado.** Um projeto não nasce lá sem que alguém tenha aceitado um artefato ou
fechado o contrato por fora, então a existência da linha é evidência de que o degrau foi
cumprido. `_has_live_project` usa o mesmo predicado de `organizations_to_watch` e de
`_anchor_project` — arquivado e apagado na origem não contam.

Três coisas ficam declaradas, porque a corroboração não é de graça:

1. **A lacuna sai na resposta** (`artifact_not_reported`), e a tela a traduz. Ninguém confunde
   "cumpriu" com "reconhecemos que deve ter cumprido".
2. **Nenhuma data é fabricada.** A corroboração reconhece o degrau; não escreve linha na
   tabela. Por isso a âncora daquela organização continua saindo do convite — que é a mesma
   régua torta de antes, e é honesto que continue até o Biahflow reportar.
3. **Na prática, este degrau nunca é o degrau travado**, e essa é a resposta certa. Ele só
   fica em aberto para uma organização **sem projeto vivo**, e aí ele é a verdade: não há nem
   projeto nem aprovação. "O artefato não foi registrado" com projeto vivo é higiene de
   cadastro, não desengajamento do cliente, e um radar que telefona por isso é um radar que o
   time aprende a ignorar.

### Só a data atravessa

Do lado do Biahflow o snapshot leva `artifact_accepted_at` e nada mais: nem `kind` (diria em
que etapa do funil comercial o cliente está), nem `title`, nem `content` (o texto comercial
que a IA de lá redige), nem valor, nem contagem. A linha do módulo `portal.py` de lá —
*"nenhum dado comercial é exposto"* — foi **qualificada em vez de contornada**, com emenda na
ADR 0003 daquele repositório: nenhuma das três coisas que ela nomeia (Opportunity,
PipelineStage, valores) cruza, e o que cruza é a data em que o próprio cliente aprovou alguma
coisa. Deste lado ela também não chega a tela nenhuma do cliente — alimenta uma tabela em que
`portal_app` não tem policy.

## O defeito que só apareceu ao executar, e ele era da ADR 0039

O primeiro teste do carimbo pelo caminho de verdade — um `sync_snapshot` de cliente novo com
`artifact_accepted_at` — falhou com **violação de chave estrangeira**.

`sync_snapshot` **cria** a organização, e chamava `onboarding.stamp`, que abre sessão
**própria** sob `portal_system`. No primeiro snapshot de um cliente novo a linha
`organization` ainda não estava comitada, então o `INSERT` do degrau não a enxergava. O
`except` engolia, saía `onboarding.stamp_failed`, e o `alerts.md` diagnostica esse evento como
*"ruído de indisponibilidade momentânea do banco"* — que é falso: não é o banco oscilando, é
ordem de transação.

**Isso já valia para `first_deliverable_delivered` desde a ADR 0039**, e foi medido: com o
código daquela ADR intacto, um snapshot inaugural com entregável entregue não carimba nada. O
motivo de ninguém ter visto é que o caso era raro (um cliente cujo *primeiro* snapshot já traz
entrega feita) e o degrau se recupera sozinho no snapshot seguinte. Com a aprovação ele deixa
de ser raro e vira o **caso central**: a aceitação do artefato é justamente o fato que chega
no primeiro snapshot de um cliente novo.

A correção é `stamp_within`, que carimba **dentro** da transação que o chamador já abriu. A
sessão separada nunca comprou nada aqui — `sync_snapshot` já roda sob `portal_system`, que é o
papel que escreve o funil. O que ela comprava era isolamento de falha, e isso o `SAVEPOINT`
(`session.begin_nested()`) dá sem inverter a ordem: o carimbo passa a ser **atômico com o fato
que o justifica**, e uma falha nele desfaz só a si mesma.

O savepoint não é zelo. Um `IntegrityError` deixa a transação do Postgres em estado abortado,
de modo que engolir a exceção sem ele apenas adiaria a queda para o `COMMIT` — trocando um
degrau perdido por um **snapshot perdido**, o inverso exato do que a ADR 0039 decidiu ao
escrever que "medir engajamento não pode derrubar o que o cliente veio fazer". Há teste para
os dois lados.

`stamp` continua existindo e continua abrindo sessão própria: é a porta das cinco rotas que
rodam sob `portal_app` e não têm transação de sistema em mãos.

## Consequências

- **Um teste antigo passou a afirmar sobre outro degrau sem que uma linha dele mudasse.**
  `test_the_roi_gap_comes_from_the_snapshot...` usava `onboarding.LADDER[:4]`, e uma fatia por
  índice se desloca inteira quando a escada cresce na frente. Os degraus passaram a ser
  nomeados ali. É a mesma família do `.priority` da ADR 0033: o elo entre o teste e o que ele
  afirma precisa ser pelo nome.
- **A âncora de um cliente ganho recentemente fica mais antiga**, e portanto `days_stuck`
  maior. É o objetivo, não um efeito colateral: o número passa a incluir a demora entre fechar
  e convidar. Uma organização que já tinha outros degraus carimbados não muda nada, porque
  `MAX(reached_at)` continua escolhendo o mais recente.
- **`_ALL_DONE` fala em sete degraus**, e a escada da tela (`STEP_ORDER` em
  `app/admin/funil/page.tsx`) cresceu junto. Aquela duplicação segue sendo o único ponto de
  deriva declarado entre os dois lados, e o custo dela continua cosmético.
- **A migração 0027 é só um rótulo de enum**, e o `downgrade` **apaga** as linhas do degrau em
  vez de remapeá-las. Reescrever "aprovou um artefato" como outro degrau seria inventar um
  fato, que é o que a imutabilidade do carimbo protege.
- **Nenhum evento de log novo**, então `alerts.md` não muda. O degrau usa o
  `onboarding.step_reached` que já existe, que é `NOT_AN_ALERT` com o motivo escrito.
- **Um `deleted` do Biahflow continua sendo o buraco de sempre**: um artefato aceito e depois
  arquivado lá some do snapshot, e o portal **não desfaz** o carimbo — nem poderia, porque
  nenhum papel tem `UPDATE` ou o `DELETE` correspondente na rota. É coerente: o cliente
  aprovou naquele dia, e desarquivar o registro não desfaz a aprovação.

## O que fica em aberto

A **vigília da IA** (passo 4 da RFC 001), que segue condicionada a histórico que ainda não
existe — a instrumentação tem um dia, e o passo 3 acabou de ser mergeado. Três documentos
declaram essa condição, e esta fatia foi escolhida por respeitá-la em vez de contorná-la.

E o caso do artefato ligado a uma oportunidade **sem projeto nenhum**, que do lado do Biahflow
não emite webhook: o fato chega no primeiro snapshot depois que o projeto nascer, que é também
quando o portal conhece aquela organização pela primeira vez. É limite declarado na FDD 031 de
lá, e não esquecimento.
