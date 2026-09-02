# ADR 0085 — O Value Ledger que a manchete não era, e o KPI cuja lacuna não é zero

**Status:** aceito
**Data:** 02/09/2026
**Fase:** 7

> Sexta fatia da adoção do [Language Map v1.1](../ontology/language-map.md) neste
> repositório, e a que fecha a **metade grande** da Issue #89. A metade pequena — o rótulo
> de projeção do ROI — saiu na [ADR 0084](0084-o-roi-que-a-manchete-nao-dizia-ser-projecao-e-o-radical-que-o-deixaria-passar.md),
> que registrou esta aqui como bloqueada no produtor. **O bloqueio caiu**:
> `biahflow/pulse#105` fechou o contrato e o PR `pulse#107` está mergeado, então `KPI`,
> `Measurement` e `ValueLedgerEntry` passaram a atravessar o snapshot. A Issue #90
> (`Process`, `Finding`, `PainPoint`, `ImprovementOpportunity`) continua bloqueada em
> `biahflow/pulse#106`.

## Contexto

### A manchete do cliente era uma promessa da origem

A ADR 0084 rotulou os dois ROIs deste repositório e disse, no próprio texto, o que
sobrava: o card de manchete da visão geral continuava sendo o `roi` do snapshot — o
número que o Biahflow **afirma** sobre o projeto, sem período, sem método e sem nada por
trás que o cliente possa conferir. Rotulá-lo de "ROI projetado" tornou a frase honesta;
não a tornou útil.

A §2 do Language Map já dizia qual é o termo certo para o que devia estar ali:

| Termo canônico | Pulse | One (o cliente vê) | Nunca chamar de |
| --- | --- | --- | --- |
| **Value** | `ValueLedgerEntry` → Value Ledger | Value Ledger | ROI projetado, Case |

E a §6 diz o que uma entrada precisa carregar para valer alguma coisa:

- **invariante 11** — todo texto voltado ao cliente que diga "Outcome" aponta para um
  `Measurement(kind=outcome)` com **Baseline comparável**;
- **invariante 12** — `ValueLedgerEntry` aponta para um Outcome e **registra método de
  atribuição**.

Nenhum dos dois tinha teste em lugar nenhum, e a §7 listava os quatro termos como
pendência aberta do repo `one`.

### As duas nulidades que o produtor mandou, e que era fácil colapsar

O contrato de `pulse#105` distingue, de propósito, duas ausências que **não são zero**:

```json
"baseline": null                                   // não há Baseline definida
"baseline": {"value": null, "period_start": "…"}   // a janela existe, ninguém mediu
```

O critério (4) da Issue #89 é exatamente sobre isso: *lacuna de medição aparece como
lacuna, nunca como zero*. É um requisito fácil de cumprir no papel e fácil de perder na
implementação — basta um `?? 0` no mapeamento do BFF, um `Numeric NOT NULL DEFAULT 0` na
coluna, ou um `float(value or 0)` na projeção, e a tela do cliente passa a afirmar "0
horas economizadas" sobre um indicador que ninguém mediu. É a mesma família do
`answerFor()` que a ADR 0021 apagou: não é dado faltando, é **dado inventado**.

### O razão é do mandato, e o KPI é do projeto

A diferença de escopo entre as duas listas do snapshot é o que estruturou a fatia
inteira, e ela é do produtor, não uma escolha daqui:

- `kpis[]` é lido por **projeto**;
- `value_ledger[]` é lido por **Engagement** e sai em **fan-out** — a mesma entrada
  aparece no snapshot de todos os projetos do mandato, com a lista completa e atual.

Guardar o razão por projeto duplicaria cada real uma vez por irmão, e a soma do programa
contaria o mesmo valor duas vezes. E `value_ledger[].kpi_id` pode apontar para um KPI que
só existe no projeto **originador**, que este cliente talvez nem alcance.

## Decisão

### 1. Duas tabelas, com escopos diferentes e policies diferentes

`kpi` é `_ProjectChildMixin` e usa o predicado simples da `0007`
(`organization_id = portal.current_org() AND project_id = portal.current_project()`),
como `milestone` e `digital_employee`. Ingestão por substituição integral por
`project_id`.

`value_ledger_entry` é `TenantMixin` **mais** `engagement_id`, sem `project_id`. A policy
não podia ser nenhuma das duas que já existiam:

- **tenant puro** (`organization_id = portal.current_org()`) é largo demais, pelo
  argumento que a `0037` já escreveu para o programa: numa conta com dois mandatos, quem
  foi convidado para um projeto leria o valor gerado do outro;
- **vínculo por `membership`**, o predicado da `0037`, é largo pelo outro lado: aquele
  existe porque `GET /me` atravessa projetos sem fixar tenant, e aqui quem lê é o
  dashboard de **um** projeto, com as GUCs de segundo estágio fixadas.

O predicado é `organization_id = portal.current_org() AND EXISTS (SELECT 1 FROM project p
WHERE p.id = portal.current_project() AND p.engagement_id = value_ledger_entry.engagement_id)`
— "o razão deste mandato, visto de dentro de um projeto dele". Ele herda a barreira do
projeto sem reimplementá-la, e não recursa (a policy de `project` consulta `membership`,
cuja policy é GUC pura).

**A diferença foi medida, não argumentada.** Com o predicado de tenant puro no lugar, o
teste `test_the_app_role_does_not_read_the_value_ledger_of_the_other_programme` reprova
com a entrada do programa vizinho visível; os outros dois passam. É o par que separa a
policy certa da uma linha mais curta.

Nas duas: **nenhum `INSERT`/`UPDATE`/`DELETE` para `portal_app`**. KPI e valor gerado
nascem do snapshot sob `portal_system` — o portal não origina status (ADR 0006/0008) —, e
aqui isso guarda uma coisa específica: um caminho de requisição capaz de escrever o
próprio Outcome é um caminho capaz de falsear o próprio resultado, que é o argumento que
a ADR 0039 escreveu para o funil.

### 2. A janela é a condição de existência da medição

Uma tabela só, sem `measurement` filha: o que atravessa a fronteira não é o modelo do
Pulse, é um snapshot em que Baseline e Outcome são no máximo um cada e `monitoring` é uma
série sem identidade própria. O sync substitui o KPI inteiro a cada passagem, então
nenhuma linha de medição sobreviveria para ser referenciada.

As duas nulidades sobrevivem **sem coluna extra**, por uma regra escrita nos dois lados:

> O objeto existe **se e somente se** `baseline_period_start` (ou `outcome_period_start`)
> não é nulo.

A janela é o que a definição da medição carrega mesmo quando o número falta; o número é
`baseline_value`, que pode ser nulo dentro de uma janela que existe. Uma coluna booleana
a mais seria um segundo lugar dizendo a mesma coisa, e os dois podendo divergir.

O mesmo cuidado vale para os números: `_decimal` devolve `None` para ausente, nulo,
booleano e ilegível — e `Decimal(str(value))`, nunca `Decimal(float)`, pela razão pela
qual `results.py` não converte dinheiro por `float`. `target` nulo é "ninguém definiu
meta". Na tela, cada um deles vira **frase**, com peso visual menor que o de um número:
"Ainda não medido", "Sem baseline definida", "Sem meta definida". Mesmo peso faria a
lacuna ser lida de relance como leitura válida, que é o vizinho do zero.

### 3. Os invariantes 11 e 12 são conferidos deste lado, e a recusa é assimétrica

O produtor garante os dois. Conferimos assim mesmo, e as duas recusas **não são iguais**:

- **Outcome sem Baseline** derruba o **Outcome**, não o KPI. Definição, unidade, meta e
  Baseline continuam valendo, e o cliente vê o indicador sem o resultado em vez de não
  ver o indicador. Sai `projection.kpi_rejected` com `reason=outcome_without_baseline`, e
  o `alerts.md` conta **qualquer ocorrência**: o produtor garante a invariante, então uma
  linha ali quer dizer que ela quebrou de lá para cá.
- **Entrada sem método de atribuição** derruba a **entrada inteira**. Uma quantia sem a
  conta que a atribui é um número solto na tela — a afirmação que a §5 bane —, e uma
  coluna nula viraria "R$ 48.000, sem explicação". Recusar é melhor que gravar mudo.

### 4. O `id` publicado é o da origem, e não o uuid

`KpiOut.id`, `ValueLedgerEntryOut.kpi_id` e `DigitalEmployeeOut.kpi_ids` publicam todos o
**`external_id` do Pulse**. É o que permite a tela casar três listas sem uma camada de
tradução, e o uuid local não responde pergunta nenhuma do cliente: ele é recriado a cada
webhook.

`DigitalEmployee.kpi_external_ids` é JSONB de ids crus, sem tabela associativa e sem FK,
pela mesma razão — uma FK apontaria para linha apagada na passagem seguinte. E é
**aditivo**: `kpi_label`, `kpi_value`, `hours_saved_month` e `roi_month` continuam vindo e
continuam sendo exibidos, sem data de morte marcada. Quem a marca é o dia em que a origem
parar de emiti-los.

Sem FK também em `value_ledger_entry.kpi_external_id`, e aqui o argumento é mais forte: o
KPI de origem pode viver num projeto irmão que ainda não sincronizou. **Não casar é caso
normal** — a tela mostra a entrada com o método de atribuição e sem o vínculo, e diz que
o indicador está em outro projeto do Engagement em vez de inventar um rótulo.

### 5. A manchete troca; a aba Resultados não

O card de manchete da visão geral passa a ser **Valor gerado**, com o total do razão, a
contagem de entradas e o período mais recente. Sem entrada nenhuma ele diz "Nenhum valor
registrado ainda" — e **não R$ 0,00**, que é a mesma lacuna-virou-zero um nível acima.

Abaixo dele entram duas seções novas: **KPIs**, com Baseline e Outcome lado a lado na
mesma unidade, e **Value Ledger**, com uma linha por entrada.

O card "ROI projetado" da aba Resultados **fica onde está**. Ele já está correto e
rotulado desde a ADR 0084, e a AC pede que a manchete troque, não que o ROI suma do
produto. O `roi` do snapshot continua no contrato e continua sendo lido.

## Consequências

**A guarda de SSR mudou de recorte, e a mudança é do mundo.** `tests/rendered-html.test.mjs`
afirmava `doesNotMatch(html, /Outcome/)` na página inteira, para provar que a decisão de
gate não se chama Outcome (decisão D7). Até esta fatia `Outcome` **não tinha produtor
neste repositório**, então "a palavra não aparece em lugar nenhum" e "a palavra não
aparece no selo do gate" eram a mesma afirmação. Agora não são: o Outcome de negócio
chegou, legitimamente, à mesma página. A asserção passou a recortar o bloco
`journey-gate`, com uma segunda asserção provando que o recorte não é vazio — recorte
vazio afirma nada, em verde, que é o defeito da ADR 0033.

**A lista `INTERNAL_SURFACES` da guarda R7 ganhou um vencimento novo.** A entrada
`apurado` do `LOCAL_QUALIFIERS` diz, com todas as letras, que ela "deixa de ser necessária
no dia em que o `Outcome` atravessar". O Outcome atravessou — mas só como **medição de
KPI**, não como o nome do lado apurado dos eventos de agente, que continua sendo
`ResultsOut` e continua sem `Measurement` por trás. A linha fica, e a condição de morte
dela fica mais estreita e mais próxima: quando a apuração dos eventos virar
`Measurement(kind=outcome)`, e não antes.

**Três eventos novos, com linha no `alerts.md` no mesmo commit.** `projection.kpi_rejected`,
`projection.value_ledger_rejected` e `projection.value_ledger_skipped`. Nenhum carrega o
número medido nem o texto do método — o conteúdo do cliente não vai para o log, a mesma
regra do termo de busca e do comentário de pendência.

**Um sync sem `engagement` não apaga o razão do mandato, e a omissão é a decisão.** Como
a tabela não tem `project_id`, um `DELETE` "do que veio neste sync" não teria escopo:
apagaria o que o projeto irmão gravou corretamente, e o Value Ledger do cliente
encolheria a cada webhook de um projeto mal configurado. O bloco inteiro é pulado, com
`projection.value_ledger_skipped` no log, no "ausência não é negação" que
`sync_snapshot` já aplica a `engagement_id` e a `artifact_accepted_at`.

**A quarta exclusão à mão no apagamento por decisão.** `retention.py` já tinha a regra
escrita — *"toda tabela nova com `organization_id` e sem `project_id` precisa de uma linha
aqui"* —, e `value_ledger_entry` é exatamente isso, com a armadilha um passo adiante: ele
é escopado por **Engagement**, e a linha `engagement` fica de pé depois do apagamento,
como a `organization`. Nem o CASCADE do projeto nem o da organização o alcançam, e o que
sobreviveria é quantia, período e o método de atribuição em prosa da origem. `kpi` **não**
precisa de linha: é escopo de projeto e sai no CASCADE.

*E a regra achou um caso anterior que esta fatia não fecha:* `engagement` (ADR 0079) é
escopado por organização, não tem `project_id`, e **também não tem linha** em
`run_erasure` — o nome do programa contratado sobrevive ao apagamento do tenant. Pode ser
deliberado, pelo argumento da própria `organization` ("o próximo snapshot a recriaria de
qualquer forma"), mas não está escrito em lugar nenhum. Fica registrado aqui em vez de
corrigido de passagem: é decisão da ADR 0079, não desta.

**Um limite de concorrência, declarado.** Dois projetos do mesmo mandato sincronizando ao
mesmo tempo apagam e reinserem as mesmas linhas do razão. O `DELETE` do segundo espera
pelos locks do primeiro mas não enxerga o que ele inseriu depois, então o `INSERT`
seguinte pode bater na unicidade `(engagement_id, external_id)` e devolver 500 ao webhook.
Não há perda — a fonte reentrega, e o razão que fica é o do snapshot que venceu. Um lock
por mandato resolveria e não foi feito: o caso exige dois webhooks do mesmo Engagement no
mesmo instante, e o custo seria serializar a porta de entrada inteira. É o mesmo tipo de
limite declarado que a ADR 0076 escreveu sobre o `synced_at`.

**O que fica aberto, nomeado.** A Issue #90 inteira (`Process`, `ProcessStep`, `Finding`,
`PainPoint`, `ImprovementOpportunity`) continua bloqueada em `biahflow/pulse#106`, com a
ressalva de documento que a ADR 0084 registrou: a §3 do Language Map promete "Evidence
marcada como revisada e publicável" e esse campo não existe, porque `Finding.reviewed_by`
só é obrigatório para `fact`. `KPI.owner` e `Measurement.source_evidence` **não**
atravessam por decisão do contrato de `pulse#105`, e não devem ser pedidos. Não há coluna
`currency`: tudo é BRL, e criar o campo antes de o produtor emiti-lo seria o painel sem
escritor da ADR 0033 na direção de entrada.

**E um limite que a fatia não fecha:** `hours_saved_month` e `roi_month` do Digital
Employee continuam sendo projeção da origem ao lado de um KPI medido, no mesmo card. Os
dois convivem rotulados — a ADR 0084 garantiu o rótulo —, mas o cliente lê promessa e
medição na mesma tela sem que nada os separe visualmente. Fechar isso é decisão de
desenho, não de dado, e não cabia aqui.
