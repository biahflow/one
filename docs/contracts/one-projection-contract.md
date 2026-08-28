# One — contrato de projeção

**Status:** normativo · **Vocabulário:** [Language Map v1.1](../ontology/language-map.md) ·
**Atualizado:** 28/08/2026 (ADR 0079)

## O que este documento é

O One é uma **projeção de leitura**. O Biahflow (Pulse) é a fonte da verdade do dado; o
portal espelha um recorte dela e não origina status (ADR 0006/0008). Este arquivo descreve
o recorte que **existe hoje** no código, com os nomes canônicos da ontologia.

Ele foi reescrito porque descrevia um payload que nunca existiu — `approvals`,
`dependencies`, `next_steps`, e fontes chamadas "ClickUp" e "BiahflowOS". Um contrato que
descreve o que não há é pior que nenhum: ele é citado como se fosse verdade.

## Os nomes

| Termo canônico | O que é aqui |
| --- | --- |
| **Account** | A organização do cliente. Tabela `organization`; o slug é `biahflow-client-{id}` e **não muda** — é chave de persistência, não vocabulário (ADR 0079). |
| **Engagement** | O programa contratado. Tabela `engagement`, escopada pela Account, com `status` em `active` · `paused` · `closed`. |
| **Project** | Um projeto dentro do programa. Tabela `project`, com `engagement_id` **nullable**. |

`Client` não é nome de modelo em lugar nenhum do domínio deste repositório. As duas
sobrevivências são deliberadas e estão registradas na ADR 0079: o papel de pessoa
`client_member` (que não é a organização) e o slug histórico acima.

## A entrada: o snapshot do Biahflow

`portal_api.integrations.biahflow.sync_snapshot` é o único lugar onde o snapshot vira read
model. As chaves que o portal lê do envelope `project`:

```json
{
  "project": {
    "id": 7,
    "name": "Automação Financeira",
    "status": "active",
    "archived_at": null,
    "account": { "id": 3, "name": "Acme Brasil" },
    "client": { "id": 3, "name": "Acme Brasil" },
    "engagement": { "id": 11, "name": "Transformação Financeira", "status": "active" }
  },
  "completion": 68,
  "observed_at": "…", "projection_version": 12,
  "milestones": [], "journey": {}, "roi": {}, "next_meeting": {},
  "digital_employees": [], "documents": [], "meetings": [], "decisions": [],
  "pendencias": [], "artifact_accepted_at": null
}
```

Três regras governam a leitura:

1. **`account` vence `client`**, nesta ordem. O Biahflow manda as duas em paralelo até a
   `/api/v2/` dele. Sem nenhuma das duas o sync falha alto: sem organização não há tenant.
2. **Ausência não é negação.** Toda chave opcional é lida com `.get()`, e o que não vem não
   apaga o que já foi afirmado — é o caso de `engagement` e de `artifact_accepted_at`. A
   exceção é `archived_at`, cuja atribuição é incondicional porque a origem sabe desfazer o
   arquivamento e `None` ali é um valor, não silêncio.
3. **Regressão é recusada por inteiro** (ADR 0076): snapshot mais velho que o aplicado — por
   `projection_version`, ou por `observed_at` no empate — é ignorado, com
   `projection.stale_rejected` no log.

## A saída: o que o cliente lê

O contrato publicado é `docs/api/openapi.json`, gerado de `portal_api/schemas.py` por
`python -m portal_api.openapi --write` e com gate de deriva em `test_openapi_contract.py`.
Este documento não o duplica; ele explica as regras que o esquema não consegue dizer.

- `GET /api/v1/me` devolve a lista de projetos com `engagement_id` e `engagement_name` —
  é o que o seletor de contexto usa para agrupar.
- `GET /api/v1/me/dashboard` devolve `engagement` (id, nome e estado) do projeto servido.
- `GET /api/v1/projects/{id}/dashboard` devolve o mesmo, sem `organization`/`project_id`.
- Cada fase da jornada traz `canonical_stage`, `gate_decision` e `requires_gate`
  (ADR 0081). Os dois primeiros são nulos por motivos **diferentes**, e é isso que faz o
  terceiro existir: `canonical_stage` nulo quer dizer que a fase **não tem equivalente na
  FDE** — uma fase operacional da Biahflow, e a origem manda `""` para dizer isso —,
  enquanto `gate_decision` nulo quer dizer que **ninguém decidiu ainda**. `requires_gate`
  é propriedade do *template* da fase na origem; sem ele, "fase sem gate" e "gate por
  decidir" seriam indistinguíveis na tela. O degrau **nunca** é derivado do nome da fase:
  só a origem o afirma, e um valor que este lado não conhece vira nulo em vez de virar
  exceção — a fase aparece sem degrau, e o sync não morre por uma palavra nova.

Duas regras de tipo, herdadas da ADR 0020: onde o produtor já entregou texto, o modelo
declara texto; e `extra="forbid"`, para um campo novo estourar na resposta em vez de sumir
em silêncio.

## O que nunca atravessa

O recorte de visibilidade é o da §3 do Language Map, e o que o código já garante hoje:

- nada de `Lead`, `Qualification`, `CommercialOpportunity` ou `PipelineStage` — nenhuma
  dessas entidades existe neste repositório;
- nada de preço, margem, custo ou probabilidade;
- nada de outra Account: o isolamento é por `TenantScopedRepository` (primeira barreira) e
  por Row-Level Security (segunda), e a negação responde **404, nunca 403**;
- do artefato comercial atravessa **só a data** de aceite (`artifact_accepted_at`),
  qualificada em emenda na ADR 0003 do Biahflow.

Desde a ADR 0082 isso deixou de ser prosa: [`one-visibility.json`](one-visibility.json) é a
lista **positiva** do que pode sair, campo a campo, com a razão escrita de cada um — e a
regra é a **negação por omissão**, campo que ninguém classificou não passa. Duas guardas
leem aquele arquivo: `apps/api/tests/test_visibility.py` afirma a cobertura, e
`tests/api-contract.test.mjs` afirma as nove proibições, sobre o contrato e sobre as
fixtures do BFF.

O recorte do corpus mora no mesmo arquivo, com a razão de cada exclusão: `/api/v1/admin/*` é
superfície interna, as sondas e os dois webhooks não são leitura de cliente, e a rota de
eventos é entrada. Filtrar campo **no BFF** foi decidido contra e está registrado: as seis
rotas de `app/api/**` são passagem crua, e filtrar lá criaria uma segunda autoridade sobre a
mesma pergunta.

O que o `extra="forbid"` faz continua valendo e é outra coisa: ele fecha o contrato por
construção, para um campo não declarado estourar em vez de sumir. O que a ADR 0082
acrescenta é a revisão humana de cada campo **declarado**.

## Homologação de entregável

O cliente decide sobre um entregável em `POST /api/v1/me/deliverables/{external_ref}/acceptance`
(ADR 0077). O registro é **append-only e imutável por privilégio**: uma segunda decisão
acrescenta linha, e a primeira aparece superada em vez de reescrita. Os valores são
`accepted` e `changes_requested`; `done` nunca entra, porque quem conclui a entrega é o
lifecycle do Biahflow — o One registra o evento e não conclui nada (ADR 0067).

## Evolução

Campo novo opcional é retrocompatível e entra com leitor no mesmo commit — um campo que
ninguém consome é pergunta para a API, não para o BFF (ADR 0029/0033), e
`npm run test:contract` reprova. Mudança incompatível pede versão de contrato e ADR.
Termo novo entra primeiro no Language Map, depois no Pulse, depois aqui.
