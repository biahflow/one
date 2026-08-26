# ADR 0076 — O snapshot que precisava de versão e hora

**Status:** proposto
**Data:** 26/08/2026
**Fase:** 7

> **Rascunho pendente de gate humano.** Esta ADR é o pré-requisito arquitetural da `F-028`
> ([FDD 028](../fdd/028-o-frescor-que-a-jornada-nunca-teve.md), Issue #62): a migração que a fatia
> escreve toca contrato de integração e é `test_migration_rules.py` que exige uma ADR **aceita** a
> citar (regra 4 do `AGENTS.md`, ADR 0066). Enquanto esta estiver `proposto`, o build da F-028 não
> começa. Nenhum código foi escrito por esta ADR.

## Contexto

A ADR 0067 decidiu que One é **projeção client-facing** do estado de Delivery, não sua fonte da
verdade, e escreveu a consequência: *"o webhook/snapshot existente evolui para contrato de projeção
versionado."* Essa evolução ficou por fazer. O snapshot de hoje (`integrations/biahflow.py`,
`sync_snapshot`) é idempotente por **substituição** — o webhook ignora o corpo e re-busca o snapshot
inteiro, apagando e reinserindo fases, entregáveis, marcos, decisões e pendências — e isso deixou
três lacunas medidas (dossiê da Issue #62):

1. **Não há frescor.** Não existe `observed_at`/`synced_at` no `Project` nem no snapshot. A tela
   mostra `source` **hardcoded** `"live"`. A ADR 0026 já **removeu** um "Atualizado há 2 dias" que era
   frescor inventado — a decisão vigente é *não* carimbar, por falta de timestamp honesto. Se o
   Biahflow parar de sincronizar, o cliente vê o último estado como se fosse o de agora, sem
   indicação.
2. **Não há defesa contra snapshot fora de ordem.** O sync não compara versão nem observação: a única
   monotonicidade explícita do módulo é `mark_project_deleted` ("a primeira observação é a
   verdadeira"; só grava se ainda `None`). O único dedup por evento do repositório é o
   `external_event_id` do `AgentEvent`, que é outro caminho (ADR 0013).
3. **O contrato não é versionado**, e não há guarda que impeça um campo internal-only de atravessar —
   a fronteira da ADR 0067 (GitHub/CI/ClickUp/LangGraph/LangSmith/margens) é hoje só convenção em
   prosa.

## Decisão

O snapshot passa a ser um **contrato de projeção versionado**, com quatro peças. Nenhuma delas dá ao
One a autoria da fase de Delivery — ele continua espelhando (ADR 0006/0008); o que ganha é **saber e
dizer quando** o dado foi observado e **recusar** aplicar um estado mais velho do que o que já tem.

### 1. Duas grandezas novas no contrato: `observed_at` e `projection_version`

O snapshot passa a carregar, no envelope (não por entidade):

- **`observed_at`** — o instante em que o **Biahflow observou** aquele estado, carimbado na origem.
  É a idade do dado, não a da cópia. Carimbar a hora em que o One copiou (`now()` no fim do
  `sync_snapshot`) seria a falsa precisão que `results.py` recusa e que a ADR 0026 removeu; só entra
  como **fallback declarado** (ver *Fallback* abaixo), nunca disfarçado de observação da origem.
- **`projection_version`** — um inteiro **monotônico por projeto**, incrementado na origem a cada
  mudança de estado projetável. É o que torna a reconciliação determinística mesmo quando dois
  `observed_at` empatam ou o relógio da origem regride.

Ambos são persistidos em colunas novas do `Project` (migração aditiva, ADR 0066) e projetados por
`build_dashboard`.

### 2. Frescor honesto, e um estado *stale* explícito

`build_dashboard` projeta `observed_at`; o BFF calcula a idade e a tela renderiza "Atualizado há X".
Acima de um **limiar** (parâmetro de operação, não de design — decisão de quem opera, não desta ADR),
a projeção entra em estado **stale**: pill + mensagem "pode estar desatualizado", reusando o padrão
honesto de `readOnlyReason` (o mesmo de "Projeto encerrado"/"Projeto removido na origem", ADR
0036/0037). Stale, **indisponível** (falha de fetch, que já sobe para `app/error.tsx`) e
**encerrado/removido** são três estados **distintos** — cores e mensagens diferentes —, porque
colapsá-los mentiria sobre qual é o caso. Sem `observed_at` real, **não há carimbo** (a implementação
não pode fabricá-lo).

### 3. Reconciliação anti-regressão, generalizando `mark_project_deleted`

`sync_snapshot` passa a **recusar** aplicar um snapshot cujo `projection_version` seja **menor** que o
já persistido para aquele projeto (empate de versão resolve por `observed_at`; ausência dos dois cai
no comportamento atual, declarado). É a regra de `mark_project_deleted` — "a primeira observação é a
verdadeira" — estendida de uma coluna para o snapshot inteiro: um webhook atrasado ou reentregue
dispara um fetch, e o fetch de um estado mais velho é **ignorado**, não aplicado por cima do mais
novo. A recusa emite `projection.stale_rejected` (nome de evento sem interpolação, detalhe em `extra`;
linha em `runbooks/alerts.md`, ADR 0018/0034), para que "o Biahflow parou de avançar" seja
observável e não silencioso.

### 4. O filtro client-safe vira contrato **e teste**

A lista de campos que **não** atravessam a fronteira (ADR 0067: IDs de GitHub Issue/PR, internals de
branch/CI, custom fields internos de ClickUp, estado bruto de LangGraph, prompts/traces de LangSmith,
custos/margens comerciais) passa a ser verificada por uma guarda que deriva do contrato os campos
client-safe e **reprova** se um campo internal-only aparecer na projeção — no espírito das guardas de
consumo e de telemetria já existentes. A fronteira deixa de ser prosa e vira portão.

## O que esta decisão **não** faz

- **Não** torna o One autoritativo sobre a fase de Delivery. Ele recusa regressão e carimba frescor;
  não origina nem edita fase (ADR 0006/0008). A recusa de um snapshot velho não é o One "decidindo"
  o estado — é o One não desaprendendo o que já observou.
- **Não** decide o **limiar** do stale: é parâmetro de operação.
- **Não** implementa o laço de aceite de volta (`client.accepted`) — isso é a `F-027`/ADR própria.
  Esta ADR é só a direção Pulse→One.
- **Não** fixa a ancoragem decisão→fase como esquema rígido (ver *Aberto*).

## Fallback declarado

Se o Biahflow **não** carimbar `observed_at`/`projection_version` na primeira versão do contrato, o
One grava `synced_at = now()` (a hora da cópia) e o **rotula como tal** na projeção — "sincronizado
há X", não "observado há X". A reconciliação, sem versão da origem, fica limitada à comparação de
`synced_at`, que ordena as *cópias* e não os *estados*; o limite é declarado, não fingido. A
preferência é a origem carimbar; o fallback existe para a fatia não travar esperando o outro
repositório, no precedente do embedder offline e do `scan_state=skipped`: uma resposta pior à mesma
pergunta, dita honestamente, em vez de uma inventada.

## Consequências

- Migração aditiva no `Project` (`observed_at`, `projection_version`, e/ou `synced_at` do fallback);
  sem tocar RLS/policy (só colunas), mas **citando esta ADR** no corpo do arquivo porque a mudança é
  de contrato de integração (regra 4).
- O contrato de snapshot ganha versão, o que permite ao Biahflow evoluí-lo sem quebrar o One em
  silêncio — a consequência que a ADR 0067 antecipou.
- A tela passa a ter três estados honestos de saúde de dado onde antes tinha `source="live"` fixo.
- A reconciliação fecha a porta que o dossiê mediu: hoje o One não tem defesa se o snapshot vier
  fora de ordem.

## Aberto

- **Ancoragem decisão→fase na timeline** (o "gates/decisões que desbloquearam a fase" da Issue #62):
  por marcação explícita do Pulse (preferido) ou heurística por `decided_on` × janela da fase? Se
  ambíguo, o que fica de fora precisa ser declarado. Fica para o gate/plano.
- **O limiar do stale** — operação.
- **Formato exato do `projection_version`** (inteiro por projeto vs vetor/relógio lógico) — a decidir
  com o lado do Biahflow, que é quem o incrementa; o inteiro monotônico é o mínimo que resolve o caso
  medido.
