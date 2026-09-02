# ADR 0086 — A superfície de Discovery que o cliente lê, e a marca de publicação que nunca atravessa

**Status:** aceito
**Data:** 02/09/2026
**Fase:** 7

> Sétima fatia da adoção do [Language Map v1.1](../ontology/language-map.md) neste
> repositório, e a que fecha a Issue #90 — a última das duas que a
> [ADR 0084](0084-o-roi-que-a-manchete-nao-dizia-ser-projecao-e-o-radical-que-o-deixaria-passar.md)
> registrou como bloqueadas no produtor. **O bloqueio caiu**: `biahflow/pulse#106` fechou
> o contrato e o PR `pulse#107` está mergeado, então `Process`, `ProcessStep`, `Finding`,
> `PainPoint`, `ImprovementOpportunity`, `PriorityAssessment` e `SolutionHypothesis`
> passaram a atravessar o snapshot. Com ela, a linha da §7 do mapa que listava os cinco
> termos como pendência do repo `one` fica vazia.

## Contexto

### O que o mapa promete que o cliente vê, e o que ele via

A §3 do Language Map é uma tabela de duas colunas — o que o One mostra e o que ele nunca
mostra — e a coluna da esquerda tinha **cinco linhas sem código deste lado**:

| No One | Estado antes desta fatia |
| --- | --- |
| Process · ProcessStep (o AS-IS validado) | não existia |
| Finding · PainPoint (revisados) | não existia |
| Evidence marcada como revisada e publicável | não existia |
| ImprovementOpportunity + Opportunity Score | não existia |
| SolutionHypothesis | não existia |

Não é lacuna de vocabulário: é a metade do produto que responde *"o que vocês
descobriram sobre a nossa operação?"*. O cliente via o **resultado** do trabalho — fases,
entregáveis, KPIs, valor gerado — e não via o **levantamento** de onde ele saiu.

### A regra 1 da §3 é o que torna a fatia arriscada

> *"Nada aparece no One antes de ser revisado por humano. Finding com
> `epistemic_status=hypothesis` aparece rotulado como hipótese ou não aparece — nunca
> aparece como fato."*

O Discovery é a única superfície deste repositório em que o dado que atravessa é
**afirmação sobre a empresa do cliente feita pelo time**, e não estado de projeto
observado. Uma hipótese exibida com cara de fato não é um rótulo errado: é o portal
dizendo ao cliente que descobrimos algo que ainda estamos supondo.

### A divergência que este repositório tinha escrita, e que o contrato refutou

A [ADR 0082](0082-o-que-o-one-nunca-expoe-e-a-negacao-por-omissao.md) criou
dois blocos em `docs/contracts/one-visibility.json` **antecipando** esta issue:

```json
"epistemic_resources": { "field": "epistemic_status", "members": [] },
"reviewed_resources":  { "field": "reviewed_at",      "members": [] }
```

O primeiro estava certo e só esperava o recurso. **O segundo estava errado**, e a ADR
0085 já tinha registrado o cheiro disso na §7 do mapa: *"a §3 promete 'Evidence marcada
como revisada e publicável' sobre um campo que não existe lá"*.

O fechamento de `pulse#106` resolveu por qual lado: a marca de publicação
(`published_at`/`published_by`) existe **só no modelo do Pulse**, em `Process`,
`Evidence`, `Finding`, `PainPoint` e `ImprovementOpportunity`, e **o filtro é aplicado
antes de emitir**. O payload não carrega marca nenhuma — *a presença no array é a prova*.

Havia três saídas, e duas são o defeito que este repositório já nomeou:

1. **Declarar `reviewed_at` em `EvidenceOut`** preenchido pela ingestão. É a ADR 0033 na
   direção de entrada — um campo publicado sem produtor —, e pior: seria o One
   **afirmando** que algo foi revisado. A regra 3 da §3 diz o contrário ("o One nunca é
   fonte primária").
2. **Deixar `members` vazia e seguir**. É a allowlist vazia que a ADR 0033 mediu: *"seguia
   vazia porque nada a consultava, não porque nada escapava"*.
3. **Registrar a divergência e dar-lhe portão**, que é o que a §9 do mapa manda fazer
   ("divergência encontrada em campo se registra no mapa antes de ser corrigida").

### O que este repositório não podia proteger com o guard que já tinha

O guard de visibilidade da ADR 0082 classifica **campo de esquema**. Ele não enxerga
dentro de um JSONB: um objeto declarado como `dict[str, int]` não tem propriedades, e
`evidences` é uma lista de objetos livres. Duas das superfícies desta fatia são
exatamente isso — `Finding.evidences` e `PriorityAssessment.dimensions` —, e o que a
issue proíbe (`raw_excerpt`, `content_hash`, transcrição, e o `rationale` da
priorização) entraria por ali sem nada ficar vermelho.

## Decisão

### Oito tabelas, escopo de conta, e nenhuma escrita para o papel de requisição

Cinco agregados e duas tabelas de ligação, todos com `TenantMixin` e **sem `project_id`**
— o Discovery é lido por Account no Pulse e sai em fan-out no snapshot de todo projeto
dela, como o `value_ledger` da ADR 0085 sai por mandato. A migração `0041` liga RLS nas
oito, dá `SELECT` a `portal_app` e **nenhum `INSERT`/`UPDATE`/`DELETE`**: um caminho de
requisição capaz de escrever um `Finding` é um caminho capaz de promover a própria
hipótese a fato.

O predicado é o mais curto do repositório — `organization_id = portal.current_org()` — e
o limite está declarado na própria migração: **duas pessoas convidadas para projetos
diferentes da mesma conta veem o mesmo Discovery**. É o que a conta *é*, e recortar por
projeto exigiria um vínculo que o produtor não emite.

As duas tabelas de ligação **não têm chave de tenant**, e a policy alcança a linha pelo
pai (`EXISTS` sobre `pain_point` / `improvement_opportunity`, a forma que a 0040 usou
para o razão). Uma terceira cópia da chave seria um segundo lugar dizendo o que a dor já
diz. Elas também são o caso que o meta-teste de RLS **não** cobra — ele exige policy de
quem tem `organization_id` —, e por isso o teste do vazamento é escrito à mão e foi
medido: com `USING (true)`, duas asserções ficam vermelhas.

**Ligação é tabela, e não JSONB**, ao contrário do `kpi_external_ids` da ADR 0085. Lá o
id solto é certo porque o KPI de origem pode viver num projeto irmão que nunca
sincronizou — não casar é estado normal e permanente. Aqui achado, dor e oportunidade
chegam no **mesmo payload**, escopados pela mesma conta e recriados na mesma transação:
um id pendurado significa que a ingestão errou, e a chave estrangeira é o que faz o banco
cobrar o que a ingestão promete.

### A marca de publicação: divergência registrada, e com portão

`EvidenceOut` **não declara** campo de revisão, e o bloco `reviewed_resources` passa a
carregar a decisão por escrito, com dois campos novos:

```json
"publication_marks": ["reviewed_at", "reviewed_by", "published_at", "published_by"],
"excluded": [{ "schema": "EvidenceOut", "reason": "…" }]
```

A guarda (`tests/api-contract.test.mjs`) afirma que o esquema excluído **não declara
nenhuma das quatro marcas**. É o que impede a exclusão de virar allowlist: no dia em que
o produtor passar a emitir a marca, a asserção reprova e a linha muda de `excluded` para
`members` — a decisão do outro lado não chega aqui em silêncio. `epistemic_resources`
ganha `FindingOut` e passa a morder de verdade; a amostra sintética das duas guardas
**fica**, porque ela nunca foi um remendo para lista vazia: é o par que prova que a regra
é estreita.

### Lista branca onde o esquema não alcança

`_EVIDENCE_KEYS` (`id`, `kind`, `reference`, `captured_at`) e `_PRIORITY_DIMENSIONS` (as
cinco da D5) são aplicadas na **ingestão**. É a negação por omissão da ADR 0082 no lugar
em que o esquema não chega: um `raw_excerpt`, um `content_hash` ou um `rationale`
**dentro** de `dimensions` não atravessa, e a asserção que prova isso injeta os três no
payload.

### O invariante 9, conferido deste lado

> *"`Finding` com `epistemic_status=fact` tem ao menos uma `Evidence` viva e revisor
> humano."*

O produtor garante, e a ingestão confere assim mesmo — pelo argumento que a ADR 0085
escreveu para o `outcome_without_baseline`: a regressão do outro lado chegaria aqui em
silêncio, e um fato sem lastro na tela do cliente é a afirmação sem evidência que a regra
3 do `AGENTS.md` proíbe ao assistente, na voz do levantamento. **Cai o rótulo, não o
achado**: ele vira `hypothesis` e continua visível, com `projection.discovery_rejected`
no log.

E o padrão do mapa de vocabulário é **invertido** em relação ao `PROJECT_STATUS_MAP`: um
`epistemic_status` desconhecido cai em `unknown`, nunca em `fact`. Vocabulário novo do
outro lado não derruba o sync e também não vira afirmação — o degrau seguro é a lacuna.

### Ausência é silêncio; lista vazia é afirmação

As quatro chaves ausentes do payload **não apagam nada** (um Biahflow anterior à fatia
está calado, e apagar o Discovery de toda conta a cada webhook antigo seria a aba
esvaziando sem ninguém ter despublicado). Presente e vazia **apaga**: é o produtor
dizendo que nada está publicado, e sem essa distinção despublicar no Pulse não teria como
chegar até aqui — a ADR 0036 na direção do Discovery.

### A aba, e o rótulo que não se traduz

`TAB_DISCOVERY = "Discovery"` é o único rótulo em inglês da barra lateral, e é decisão. A
§1 do mapa é normativa e explícita — *"não se traduz o termo, traduz-se o texto em volta
dele"* — e a §2 escreve **Discovery** na coluna "O One (o cliente vê)". As outras oito
abas não passam por isso porque nenhuma delas nomeia um termo da ontologia: "Cronograma"
e "Pendências" são áreas da tela. O precedente na tela já existe e é o Engagement (ADR
0079). As quatro seções usam os rótulos canônicos da §2 e da §5 — **Process**,
**Findings**, **Pain Points**, **Improvement Opportunity Backlog**, **Opportunity
Score** —, os três últimos entre os rótulos de artefato que a §5 nomeia como as únicas
exceções ao qualificador obrigatório.

**As quatro seções aparecem sempre, inclusive vazias.** Hoje o Pulse não tem tela de
publicar — só API —, então na prática os quatro blocos chegam vazios, e isso é estado
normal e não falha de integração. Uma aba que se escondesse faria o cliente concluir que
o produto não tem a superfície; as quatro frases de ausência dizem o que **vai** aparecer
ali, e nenhuma delas se parece com erro de carregamento.

### O que a tela recusa dizer

- **Impacto sem símbolo de moeda.** `impact_estimate` vem sem unidade declarada e
  `impact_type` diz coisas que não são dinheiro (`time`, `quality`, `volume`). Formatar
  tudo como BRL seria o defeito que a ADR 0033 achou no `money()`: um número que não é em
  reais com "R$" na frente não fica incompleto, fica **errado**. `null` é "Impacto não
  quantificado", nunca "R$ 0".
- **Oportunidade sem nota não recebe zero.** `priority_assessment: null` vira "Ainda não
  priorizada" e vai para o fim da lista. Ausência de nota não é a pior nota — e o
  `NULLS LAST` não é detalhe: sem ele o Postgres põe o não avaliado **em primeiro** num
  `ORDER BY … DESC`, e o backlog abriria pelo item sobre o qual não há juízo nenhum.
- **A ordem nasce na API**, e a tela não repete o critério — o argumento do `tabs.py`.

## Consequências

- **Fecha a Issue #90** e, com ela, as cinco linhas da §3 do Language Map que não tinham
  código deste lado. A §7 do mapa deixa de listar pendência do repo `one`.
- **A divergência do `reviewed_at` fica registrada e vigiada**, em vez de corrigida em
  silêncio ou deixada como lista vazia decorativa.
- **O apagamento por decisão ganhou a quinta exclusão escrita à mão** (`retention.py`), e
  ela é a mais cara: o Discovery descreve como a empresa do cliente trabalha por dentro, é
  escopado por organização e não vem no CASCADE do projeto.
- **O custo do fan-out é o mesmo já aceito na ADR 0085**, dobrado: quatro blocos de escopo
  de conta substituídos a cada sync de qualquer projeto dela. E o mesmo limite declarado —
  dois projetos do mesmo tenant sincronizando ao mesmo tempo podem colidir na unicidade e
  devolver 500 ao webhook; não há perda, a fonte reentrega.
- **A busca não alcança o Discovery.** A regra da ADR 0024 é que entra na busca o que
  alguma aba mostra, e agora quatro listas novas passaram a ser mostradas. Ligá-las pede
  `Hit`, espaço de nomes de âncora e `data-item` nos quatro blocos, com as guardas de
  `test_item_anchor.py` junto — é fatia própria, e fica declarada como item aberto aqui em
  vez de ficar por dizer.
- **O `UNLINTABLE` do `"Opportunity Score" de uma venda` encolheu de razão, não de
  conclusão**: a `ImprovementOpportunity` passou a existir aqui e o rótulo é aplicado a
  ela; a venda continua sem existir e tem proibição própria em `forbidden_resources`. O
  que nenhuma varredura decide continua sendo alguém aplicar o rótulo certo à entidade
  errada.
- **Nada de tela de publicar.** É trabalho do lado do Pulse e não existe lá; enquanto não
  existir, a aba do cliente fica vazia — e o produto diz isso em vez de parecer quebrado.
