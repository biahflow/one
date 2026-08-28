# Biahflow Language Map v1.1 — Pulse · One · Notion · Biahflow

> Espelho do documento canônico no Notion: **Language Map — Pulse · One · Notion · Biahflow**
> <https://app.notion.com/p/3ca82225ad278115bd44c2d90247f44e>
> Quando divergirem, a página do Notion vence — e a divergência se registra antes de qualquer edição.

**Status:** normativo · **Depende de:** Biahflow Operating Ontology v1 · **Data:** 28/08/2026

A Ontology v1 define **o que cada termo significa**. Esta página define **onde cada termo aparece e com que nome**, nas quatro superfícies em que a Biahflow fala: Pulse, One, Notion e material de mercado. Quando as duas divergirem, a Ontology v1 vence no significado e esta página vence no rótulo.

Regra de ouro: **um conceito, um nome, quatro superfícies.** Se uma superfície precisa de outra palavra, ela não precisa de outra palavra — ela precisa de outro conceito.

---

## 0. Decisões desta versão

Sete conflitos reais entre Pulse, Notion e material comercial, resolvidos aqui. Cada um mudava o significado de dado já persistido, então nenhum ficou em aberto.

| # | Conflito | Decisão | Quem muda |
| --- | --- | --- | --- |
| D1 | Ontology v1 §3 diz que Qualification "não é entidade"; o gap doc do Pulse pede um agregado `Qualification` | Qualification **é entidade persistida**: a avaliação fica registrada, com autor, data e resultado. Não é container comercial nem de entrega | Ontology v1 §3 · Pulse |
| D2 | Quatro vocabulários para o resultado da Qualification | Enum único: `qualified` · `nurture` · `disqualified`. Só `qualified` abre CommercialOpportunity | Ontology v1 · Pulse · script comercial |
| D3 | Ontology v1 §9 diz Project → Engagement `0..1`; gap doc diz obrigatório | **Obrigatório.** Todo Project pertence a exatamente um Engagement. Venda avulsa cria um Engagement de escopo único | Ontology v1 §9 · Pulse · One |
| D4 | Qualification Call listada como um dos "sete degraus vendáveis" | **Sai da escada comercial.** Vira oferta de aquisição (`service.category=acquisition`). Nunca gera CommercialOpportunity nem Project. Restam **seis degraus vendáveis** | Notion (Sistema Operacional) · Pulse |
| D5 | "Opportunity Score" existe na FDE, mas não há entidade que o carregue | O score é `priority_assessment.score`. **"Opportunity Score" é rótulo de UI/cliente**, aplicável só a ImprovementOpportunity — nunca a CommercialOpportunity | Pulse · One · Executive Readout |
| D6 | FATO / HIPÓTESE / DESCONHECIDO vive dentro de `Evidencia` | Vira `finding.epistemic_status` = `fact` · `hypothesis` · `unknown`. Finding extraído por IA nasce `hypothesis`; promoção a `fact` é ato humano | Pulse · FDE |
| D7 | `GateOutcome` colide com Outcome de negócio | Renomeado para `GateDecision`, valores `go` · `conditional_go` · `redesign` · `no_go` | Pulse · One · FDE |

---

## 1. As quatro superfícies

| Superfície | O que é | Quem lê | Papel na linguagem |
| --- | --- | --- | --- |
| **Pulse** | Portal operacional interno da Biahflow (repo `pulse`) | Biahflow | Fonte da verdade do **dado**. Nomes canônicos em modelo, banco, API e UI interna |
| **One** | Portal do cliente (repo `one`) | Sponsor e time do cliente | **Projeção de leitura** do Pulse. Mesmos nomes, subconjunto visível. Não inventa termo |
| **Notion** | Estratégia, método, playbooks, verticais | Biahflow | Fonte da verdade do **método**. Prosa em português, termos canônicos em inglês |
| **Biahflow** | Site, decks, propostas, one-pagers, conteúdo | Mercado | Mesma palavra, sem jargão de banco. Nunca um sinônimo criado para "soar melhor" |

**Regra de idioma:** termos canônicos **em inglês nas quatro superfícies**. `snake_case` em código, banco e API; `Title Case` em UI e prosa. Não se traduz o termo — traduz-se o texto em volta dele. "A Account tem três Engagements ativos" está certo; "A Conta tem três Compromissos ativos" está errado.

---

## 2. Tabela mestra de termos

| Termo canônico | Pulse (modelo · API) | One (o cliente vê) | Notion | Comercial | Nunca chamar de |
| --- | --- | --- | --- | --- | --- |
| **Lead** | `Lead` · `/leads` | — | Lead | contato de entrada | Cliente, Oportunidade |
| **Qualification** | `Qualification` · `/qualifications` | — | Qualification | Qualification Call (o encontro) | Oportunidade, Projeto, Lead status |
| **CommercialOpportunity** | `CommercialOpportunity` · `/commercial-opportunities` | — | Commercial Opportunity | Proposta / negociação | `Opportunity` sozinho |
| **Account** | `Account` (era `Client`) · `/accounts` | sua organização | Account | Cliente (só com `lifecycle_status=active`) | Client (no modelo), Empresa |
| **Engagement** | `Engagement` · `/engagements` | Engagement | Engagement | Programa de transformação | Projeto, Conta, Contrato |
| **Project** | `Project` · `/projects` | Project | Project | Discovery Sprint · Feasibility · PROVE · Scale | Engagement, Entrega |
| **Process** | `Process` (era `Processo`) | Process (mapa AS-IS) | Process | Processo | Fluxo, Projeto |
| **ProcessStep** | `ProcessStep` (era `ProcessoEtapa`) | Step | Process Step | Etapa | Tarefa |
| **Discovery** | `Discovery` · `/discoveries` | Discovery | Discovery | Discovery Sprint (o produto) | Reunião, Documento, Fase |
| **DiscoverySession** | `DiscoverySession` | sessão na agenda | Discovery Session | sessão de Discovery | Meeting |
| **ProcessObservation** | `ProcessObservation` | — | Process Observation | — | Evidence |
| **Evidence** | `Evidence` (split de `Evidencia`) | Evidence (só a revisada) | Evidence | evidência | Finding, Achado, Conclusão |
| **Finding** | `Finding` (split de `Evidencia`) | Finding | Finding | achado / descoberta | Evidência, Opinião, Insight |
| **PainPoint** | `PainPoint` | Pain Point | Pain Point | gargalo / dor | Oportunidade, "problema" solto |
| **ImprovementOpportunity** | `ImprovementOpportunity` · `/improvement-opportunities` | Improvement Opportunity (no backlog) | Improvement Opportunity | oportunidade (no Opportunity Map) | Commercial Opportunity, Projeto |
| **PriorityAssessment** | `PriorityAssessment` | Opportunity Score | Priority Assessment | Opportunity Score | Prioridade (campo), `ai_score` |
| **SolutionHypothesis** | `SolutionHypothesis` | Solution Hypothesis | Solution Hypothesis | hipótese de solução | Solução, Proposta, Escopo |
| **FeasibilityAssessment** | `FeasibilityAssessment` | Technical Feasibility (o laudo) | Feasibility Assessment | Technical Feasibility Brief | Feasibility (a fase), POC |
| **ProveExperiment** | `ProveExperiment` | PROVE | PROVE | PROVE | Piloto, POC, MVP |
| **KPI** | `KPI` (extraído de `DigitalEmployee`) | KPI | KPI | indicador | Outcome, Meta |
| **Measurement** | `Measurement(kind=…)` | leitura do KPI | Measurement | medição | KPI |
| **Baseline** | `Measurement(kind=baseline)` | Baseline | Baseline | Baseline | Meta, Outcome, estimativa |
| **Outcome** | `Measurement(kind=outcome)` | Outcome | Outcome | resultado medido | Gate, promessa, ROI projetado |
| **Value** | `ValueLedgerEntry` → Value Ledger | Value Ledger | Value · Client Value Ledger | valor gerado | ROI projetado, Case |
| **GateDecision** | `GateDecision` (era `GateOutcome`) | decisão da fase | Gate Decision | GO / CONDITIONAL GO / REDESIGN / NO-GO | Outcome |
| **DigitalEmployee** | `DigitalEmployee` | Digital Employee | Funcionário Digital | Funcionário Digital | Solução, SolutionHypothesis, Agente |
| **Service** | `Service` (catálogo de ofertas) | nome do produto contratado | degrau / produto | Discovery Sprint, PROVE… | Estágio, Fase, Tier de trabalho |
| **JourneyPhase / ProjectPhase** | idem | timeline da fase | fase FDE | DISCOVER · PRIORITIZE · … | os agregados Feasibility/PROVE |
| **Case** | `Case` | só com autorização | Case Library | Case | Outcome, Value |

---

## 3. O que o One mostra — e o que nunca mostra

O One é uma **projeção de leitura** do Pulse. Ele não tem vocabulário próprio: se um termo não existe no Pulse, não existe no One.

| No One | Nunca no One |
| --- | --- |
| Engagement · Project · fase e progresso | Lead |
| Process · ProcessStep (o AS-IS validado) | Qualification e seu resultado |
| Finding · PainPoint (revisados) | CommercialOpportunity, `PipelineStage`, valor, probabilidade |
| Evidence marcada como revisada e publicável | Evidence não revisada, transcrição bruta |
| ImprovementOpportunity + Opportunity Score | `PriorityAssessment.rationale` interno |
| SolutionHypothesis · FeasibilityAssessment · GateDecision | preço de tabela, margem, `Service.price` |
| ProveExperiment · KPI · Baseline · Outcome | Case de outros clientes |
| Value Ledger · Deliverables · DigitalEmployee | qualquer dado de outra Account |

Três regras que sustentam isso:

1. **Nada aparece no One antes de ser revisado por humano.** Finding com `epistemic_status=hypothesis` aparece rotulado como hipótese ou não aparece — nunca aparece como fato.
2. **O One nunca renomeia.** O que o Pulse chama de Engagement, o One chama de Engagement.
3. **O One nunca é fonte primária.** Nenhuma medição nasce lá.

---

## 4. Enums canônicos

| Campo | Valores | Observação |
| --- | --- | --- |
| `qualification.outcome` | `qualified` · `nurture` · `disqualified` | Só `qualified` abre CommercialOpportunity (D2) |
| `finding.epistemic_status` | `fact` · `hypothesis` · `unknown` | Extração por IA nasce `hypothesis` (D6) |
| `gate_decision` | `go` · `conditional_go` · `redesign` · `no_go` | Vale para Feasibility e PROVE (D7) |
| `measurement.kind` | `baseline` · `outcome` · `monitoring` | Uma única `baseline` por KPI e janela |
| `journey_phase.canonical_stage` | `discover` · `prioritize` · `feasibility` · `prove` · `scale` · `optimize` | Já existe no Pulse |
| `account.lifecycle_status` | `prospect` · `active` · `inactive` | Rótulo "cliente" só em `active` |
| `service.category` | `acquisition` · `commercial` | `qualification_call` é `acquisition` (D4) |
| `engagement.status` | `active` · `paused` · `closed` | |

---

## 5. Termos banidos

| Termo | Por quê | Usar |
| --- | --- | --- |
| `Opportunity` sem qualificador | Colide entre venda e melhoria operacional | `CommercialOpportunity` ou `ImprovementOpportunity`. Únicas exceções: os rótulos de artefato **Opportunity Score**, **Opportunity Map** e **Improvement Opportunity Backlog** — nomes de entregável, não entidades |
| `Client` como nome de modelo | A organização é Account desde prospect | `Account` (rótulo "cliente" só na UI, com `lifecycle_status=active`) |
| `Evidencia`, `Processo`, `ProcessoEtapa` | Nomes em português no modelo | `Evidence`, `Process`, `ProcessStep` |
| `GateOutcome` | Colide com Outcome de negócio | `GateDecision` |
| "Cockpit", "portal do cliente" | Nome antigo/genérico do One | **One** |
| "portal Biahflow", "o CRM" | Nome genérico do Pulse | **Pulse** |
| "POC", "piloto" para o PROVE | PROVE é produção controlada com critério prévio | **PROVE** |
| "Opportunity Score" de uma venda | O score mede melhoria operacional, não receita | Score só em ImprovementOpportunity |
| `Lead.ai_score` como qualificação | É score de aquisição, insumo — não decisão | `Qualification.outcome` |
| `Project.ai_opportunity` como prioridade | É maturidade de IA da conta | `PriorityAssessment` |
| "ROI" como resultado | ROI projetado não é resultado medido | `Outcome`, depois `Value` |

---

## 6. Invariantes de linguagem

Estas viram teste automatizado no Pulse e revisão de PR nos dois repos.

1. Nenhum identificador novo (modelo, campo, rota, componente, prop) contém `opportunity` sem qualificador.
2. Nenhum identificador novo contém `client` como sinônimo de organização.
3. Nenhum identificador novo contém `outcome` referindo-se a decisão de gate.
4. Nenhum modelo novo tem nome em português.
5. `Qualification.outcome != qualified` não abre CommercialOpportunity.
6. Nenhum Project nasce de um `Service` com `category=acquisition`.
7. Todo Project tem `engagement_id` não nulo.
8. `Finding` criado por extração de IA nasce `epistemic_status=hypothesis`.
9. `Finding` com `epistemic_status=fact` tem ao menos uma `Evidence` viva e revisor humano.
10. Nenhum endpoint do One expõe `Lead`, `Qualification`, `CommercialOpportunity` ou `PipelineStage`.
11. Todo texto voltado ao cliente que diga "Outcome" aponta para um `Measurement(kind=outcome)` com `Baseline` comparável.
12. `ValueLedgerEntry` aponta para um `Outcome` e registra método de atribuição.

---

## 7. O que muda em cada superfície

### Pulse (repo `pulse`)
Seis fatias, na ordem do gap doc: Qualification antes de CommercialOpportunity → Engagement entre Account e Project → split Evidence/Finding → PainPoint/ImprovementOpportunity/Priority/SolutionHypothesis → KPI/Measurement/ValueLedger → renomes físicos e remoção de aliases.

### One (repo `one`)
Renomear a superfície para o vocabulário canônico antes de crescer: `Client`→`Account`, introduzir Engagement como raiz de navegação, expor Finding/PainPoint/ImprovementOpportunity com o rótulo certo, e implementar o guard de visibilidade da seção 3.

### Notion
**Feito em 28/08/2026.** Ontology v1 corrigida (§3, §4, §9, §10, §13 — bump para v1.1); Sistema Operacional — PULSE com pipeline de dois trilhos, seis degraus vendáveis e "Opportunity" sempre qualificado; Metodologia FDE com o enum de Qualification, `finding.epistemic_status` e `gate_decision`; Material Comercial com os três resultados de Qualification. O que sobra daqui em diante é manutenção: termo novo entra primeiro nesta página.

### Biahflow (mercado)
Script de Qualification passa a terminar em `qualified` / `nurture` / `disqualified`. Escada comercial mostra seis degraus. Executive Readout chama o número de Opportunity Score e nunca aplica a palavra a uma venda.

---

## 8. Evolução

Mudança de significado gera **nova versão desta página e da Ontology**, com registro explícito. Nunca se altera em silêncio o sentido de um termo já persistido. Termo novo entra primeiro aqui, depois no Pulse, depois no One.
