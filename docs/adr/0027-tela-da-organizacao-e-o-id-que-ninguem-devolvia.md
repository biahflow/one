# ADR 0027 — A tela da organização, e o id que nenhuma resposta devolvia

**Status:** aceita — 06/08/2026
**Contexto:** Fase 6. Dá caller às seis rotas cujo escopo é a organização, que existiam
completas desde as ADRs 0017 e 0022 e não tinham como ser chamadas.

## Contexto

Seis rotas de administração por **organização** existem em `admin.py`, completas, testadas e
sob `portal_admin`:

| Rota | ADR |
|---|---|
| `GET / PUT /api/v1/admin/organizations/{id}/retention` | 0017 |
| `POST / GET /api/v1/admin/organizations/{id}/erasure` | 0017 |
| `GET / PUT /api/v1/admin/organizations/{id}/ai-quota` | 0022 |

Nenhuma tela as chamava. Mas o achado não é uma tela faltando:

```
grep organization_id apps/api/src/portal_api/schemas.py  →  nada
```

**`organization_id` não aparecia em resposta nenhuma da API.** `MeOut.organization` é o *nome*
da organização, uma string; `MeProjectOut` traz id de projeto. As seis rotas são chaveadas por
um UUID que endpoint algum devolvia a chamador algum — elas não estavam sem tela, estavam
**estruturalmente inalcançáveis** por qualquer coisa que não consultasse o Postgres à mão.

É a forma da ADR 0022, onde `ANTHROPIC_API_KEY` existia no `.env.example`, era lida pelo
`config.py` e nenhum compose a passava ao contêiner: código completo, correto, e sem caller
possível. A diferença é que lá faltava uma linha de YAML e aqui faltava uma rota.

### O desenho sabia da tela que não veio

Os docstrings da própria API descrevem um consumidor que não existia:

- `RetentionPolicyOut` devolve prazo escolhido **e** efetivo porque *"a tela precisa mostrar o
  que vale e poder distinguir 'escolhido' de 'herdado', senão editar o formulário fixaria o
  padrão sem querer"*.
- `ErasureRequestIn.confirm_slug` existe para *"obrigar quem **clica** a olhar **qual** tenant
  está **na tela**"*.
- `AiQuotaOut` devolve gasto, tokens, chamadas e `gaps` — payload de painel, não de máquina.
- `GET .../erasure` é *"o histórico de pedidos — é o que faz o apagamento ser auditável"*.

### E duas instruções escritas mandavam usar o que ninguém conseguia usar

- `runbooks/load-test.md` — *"Suba o teto daquela organização pelo
  `/api/v1/admin/organizations/{id}/ai-quota`"*.
- `runbooks/alerts.md` — diz que o `extra` do alerta basta *"para decidir **sem abrir a
  tela**"*, e manda o operador ao `deploy.md`, que não menciona a rota em lugar nenhum.

O caso mais caro é o expurgo: obrigação contratual que, na prática, só se cumpria por `curl`
com um token que o portal nunca mostra — ele vive no cookie cifrado do Auth.js (ADR 0010) e
não há CLI que o emita.

## Decisão

### 1. `GET /api/v1/admin/organizations`, e sem ela nada mais é possível

Lista as organizações onde o chamador é `internal_admin`, com `id`, `name` e `slug` — plural de
`require_organization`, na forma de `visible_projects`.

**Lista vazia com 200, e não 404** — a única rota de `admin.py` que não responde 404 na ausência.
Ali não há recurso nomeado cuja existência se possa vazar: "não administro nenhuma" é uma
verdade sobre o chamador, do mesmo feitio que `projects` vazio em `GET /api/v1/me`.

**Não chama `bind_admin_org`, e isso é o desenho.** A GUC de terceiro estágio guarda *uma*
organização, e a pergunta aqui é *quais*. Antes dela a transação enxerga apenas os vínculos do
próprio chamador — a mesma propriedade que impede `_authorized_org` de ser circular, usada agora
como recorte em vez de como pré-condição.

**Medido, e vale registrar:** removendo o predicado `Membership.user_id == user.id` do
`administered_organizations`, os dois testes de isolamento **continuam passando**. Não é falha do
teste: é a RLS segurando. Com `portal_admin` e nenhum contexto publicado, `SELECT` em
`membership` devolve **zero linhas** — as policies leem `current_setting(..., true)`, que é NULL.
O predicado da aplicação é a primeira barreira, na forma do `TenantScopedRepository`, e a policy
é a segunda; a asserção prova o comportamento, e quem o garante é a segunda.

### 2. Não entra no `GET /api/v1/me`

Seria uma linha em `MeOut`. Poria um id de tenant na resposta de **todo cliente** para servir a
uma tela de administração, e `MeOut.organization` é singular — não cobriria quem administra mais
de uma, que é o caso que a ADR 0025 tornou comum ao permitir a segunda organização.

### 3. `/admin/organizacao` — três painéis, e um ausente de propósito

Retenção, teto de IA e apagamento. **Documento não aparece**, e a ausência é a decisão: ele é a
evidência que sustenta uma citação já dada, e apagá-lo num aniversário tornaria uma resposta
antiga impossível de conferir (ADR 0017). Sai por decisão de alguém, nunca por idade — e a tela
diz isso, em vez de deixar a pessoa procurar o campo.

A entrada é pelo `/admin`, **sem `?project=`**, e é a diferença que importa: as outras duas telas
de administração são de um projeto, esta é da organização inteira.

### 4. O botão de apagar não parece com os outros

`.admin-submit--danger`, e o `confirm_slug` digitado com o slug visível ao lado do campo. Mostrar
o slug não enfraquece a confirmação: o que ela protege é o erro de olhar para o tenant errado,
não o segredo do nome — é o "digite o nome do repositório" de qualquer serviço que apague de
verdade.

Continua sem rota que apague. A tela grava intenção; quem cumpre é o worker sob `portal_system`.

### 5. O argumento que adiou a quota estava trocado

O FDD 016 adiou a tela da quota com o argumento da ADR 0015 — *"sem consumo acumulado ela
mostraria zero"*. Isso vale para o **painel de gasto** e não para o **controle de teto**, que
mostra um número no primeiro dia e é o que o `alerts.md` manda mexer quando `ai_quota.exhausted`
dispara às três da manhã. Os dois foram tratados como uma coisa só, e por isso o controle ficou
esperando o dado do painel.

## Consequências

- **As seis rotas passam a ter caller**, e as duas instruções de runbook passam a ser
  executáveis. `tests/e2e/organizacao.spec.ts` percorre o caminho num navegador com sessão real.
- **O expurgo por organização deixa de depender de `curl` com um token que o portal não emite.**
  É a mudança de risco desta fatia, nas duas direções: a obrigação contratual vira cumprível, e
  aparece um botão capaz de apagar um tenant. O que o segura é o que já estava desenhado — o
  slug digitado, o pedido gravado em vez do apagamento imediato, e o worker como executor.
- **O e2e não pede um expurgo de verdade**, e não é timidez: o worker cumpriria, o tenant
  semeado sumiria e todos os outros specs cairiam junto. O que ele afirma é a recusa da
  confirmação errada — que é a asserção interessante de qualquer forma, porque o 422 do
  `confirm_slug` é a única negação do portal que não é 404.
- **Nenhuma migração, nenhum modelo novo, nenhum GRANT novo.** A fatia acrescenta uma rota de
  leitura e uma tela; toda a autoridade já existia.
- **De quebra, o defeito que só apareceu ao subir a pilha:** `seed._upsert_membership` procurava
  a linha por `user_id` + `project_id IS NULL` **sem filtrar a organização**. Isso era correto
  enquanto havia uma organização só. O bootstrap da ADR 0025 dá um vínculo de escopo
  organizacional na organização nova, então quem administra duas acumula um `project_id IS NULL`
  por organização — e o `scalar_one_or_none` estourava `MultipleResultsFound`, derrubando o
  serviço `api-seed` **a cada `docker compose up`**. Não é sujeira de máquina: é o estado normal
  de qualquer instalação onde o sync do Biahflow criou uma segunda organização, que é justamente
  o caminho que a ADR 0025 abriu. A correção é o predicado de organização; o teste que a segura
  vive em `test_grant_access.py`, porque o defeito é a interação daquela ADR com o seed e não uma
  propriedade do seed sozinho.

## Alternativas recusadas

**`organization_id` no `GET /api/v1/me`.** Ver decisão 2.

**Um `GET /api/v1/admin/organizations/{slug}/...`, resolvendo por slug em vez de uuid.** Tiraria
a necessidade da listagem, porque o slug aparece em lugares que o cliente já vê. E faria o
identificador de rota ser um campo **editável** — o dia em que o Biahflow renomear uma
organização, todo link salvo aponta para 404, e o `confirm_slug` do expurgo deixaria de ser uma
segunda coisa a conferir para virar a repetição da primeira.

**Expurgo fora da tela, só retenção e quota.** Deixaria de pé a única obrigação contratual que
hoje não se cumpre pela interface, e deixaria o `confirm_slug` sem o clique que ele existe para
proteger — uma trava desenhada para uma tela que ninguém construiu é a mesma classe de coisa que
esta ADR está corrigindo.

**Um painel de gasto de IA na tela do cliente.** O cliente não escolheu o teto nem paga por
token; mostrar-lhe consumo transformaria uma decisão comercial em ansiedade de uso. O que ele vê
quando o teto acaba continua sendo a mensagem do chat.
