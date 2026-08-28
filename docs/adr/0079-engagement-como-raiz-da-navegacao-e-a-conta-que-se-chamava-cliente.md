# ADR 0079 — Engagement como raiz da navegação, e a conta que se chamava cliente

**Status:** aceito
**Data:** 28/08/2026
**Fase:** 7

> Primeira fatia da adoção do [Language Map v1.1](../ontology/language-map.md) neste
> repositório (Issue #86). O documento normativo entra versionado com ela: até aqui ele
> vivia só no Notion e num arquivo não rastreado, e as issues o citavam como se fosse
> alcançável. A ADR par é a [0080](0080-o-link-do-aviso-que-a-rota-renomeada-deixa-para-tras.md),
> sobre o que o rename de rota custa a um dado já gravado.

## Contexto

O Language Map v1.1 fixa o vocabulário nas quatro superfícies em que a Biahflow fala, e a
regra de ouro dele é **um conceito, um nome, quatro superfícies**. Três coisas dele não
valiam aqui:

1. **`Engagement` não existia.** Nem neste repositório, nem no Pulse. O One navegava direto
   de organização para projeto, e o nível do meio — o programa que a conta contrata, e do
   qual Discovery, Feasibility, PROVE e Scale são degraus — não tinha modelo, coluna,
   contrato nem tela. A §7 do Language Map manda "introduzir Engagement como raiz de
   navegação" no One, e a §2 diz que o cliente vê o termo pelo nome.
2. **`Client` ainda era nome de domínio.** O mapa bane `Client` como nome de modelo (§5) e a
   invariante 2 proíbe identificador novo com `client` como sinônimo de organização. Havia
   exatamente um sobrevivente no front: `ClientRow`, o tipo do funil de onboarding.
3. **As rotas de domínio estavam em português.** `/admin/funil`, `/admin/conhecimento`,
   `/admin/organizacao`, `/admin/resultados`, `/admin/assistente`. O `AGENTS.md` já dizia
   "código, nomes de API e banco em inglês; experiência e documentação em PT-BR", e um
   caminho de rota é identificador — mas ele não estava nomeado na regra, então cinco
   nasceram em português sem que nada reprovasse.

O que torna a hora boa é o que a ADR 0053 registrou: **o portal está fora do ar desde
13/08/2026**. Renomear rota sem redirect custa quase nada com zero sessão de cliente aberta,
e custaria uma camada de compatibilidade permanente depois.

A sessão que trabalha no Pulse confirmou o contrato por mensagem em 28/08/2026:
`project.engagement = {"id", "name", "status"}` com o enum `active`/`paused`/`closed`, e
`project.account = {"id", "name"}` saindo **em paralelo** com `project.client`, que
sobrevive até a `/api/v2/` deles. Nada disso está implementado lá ainda.

## Decisão

### 1. `Engagement` entra como agregado, entre a Account e o Project

Modelo novo (`models/engagement.py`), escopado **só pela organização** — sem `project_id`,
porque ele é pai de projeto e não filho. `Project` ganha `engagement_id` **nullable**, com
`ondelete='SET NULL'`.

**Por que nullable, sendo que a ontologia diz obrigatório** (invariante 7, decisão D3 do
mapa): porque este lado **projeta** e não origina. Um projeto sincronizado antes de o
Biahflow mandar a chave não tem programa, e `NOT NULL` exigiria um valor de aterro para toda
linha existente — a falsa precisão que `results.py` recusa ao declarar base ausente em vez
de dividir por zero, e que a ADR 0026 apagou da tela ao remover um "Atualizado há 2 dias"
que ninguém tinha como sustentar. A obrigatoriedade é invariante **da origem**; aqui ela
chega como consequência, não como constraint. O `null` tem começo e fim declarados: é a
janela entre a migração que cria a coluna lá e a que a torna `NOT NULL`.

`SET NULL` e não `CASCADE`: apagar o programa não pode apagar o projeto do cliente — ele
volta a não ter agrupamento, que é o estado de toda linha anterior a esta fatia.

### 2. A policy do `portal_app` é a de vínculo, não a de tenant — e isso foi medido

A forma óbvia seria `organization_id = portal.current_org()`, que é o que `document_chunk` e
`pending_item` usam. Ela **devolveria zero linhas em `GET /api/v1/me`**:
`access.visible_projects` documenta que deliberadamente não fixa tenant — a listagem
atravessa projetos enquanto as GUCs de segundo estágio guardam exatamente um. O nome do
programa viria nulo em todo projeto, **em silêncio**, justamente na rota que alimenta o
seletor; o seletor agruparia tudo no bloco sem cabeçalho e nada ficaria vermelho.

O predicado é o de `project_member_read` (migração 0007) **transposto para o programa**:
vínculo organizacional (`project_id IS NULL`) alcança todo engagement da conta, e vínculo
escopado a um projeto alcança só o engagement **daquele** projeto. Não recursa: a policy de
`project` consulta `membership`, cuja policy é GUC pura, sem subconsulta.

A revisão desta fatia recusou uma versão uma linha mais curta, que era a primeira escrita: o
predicado de `organization_member_read` — "existe vínculo com esta organização" — basta para
o `GET /me` funcionar e é **largo demais**. Numa conta com dois programas, quem foi convidado
para um projeto passaria a ler o nome do outro programa, apagando exatamente a distinção
entre projetos que a 0007 se deu ao trabalho de fazer. A regra que decidiu: **a segunda
barreira não pode ser mais frouxa que a primeira** — `visible_projects` só alcança o programa
por um projeto visível, e a policy passa a dizer a mesma coisa.

*Medido por mutação, nas duas direções:*

1. trocando a policy pelo predicado de **tenant** no banco e rodando a bateria, reprovam
   exatamente duas asserções — `test_the_engagement_is_readable_without_the_tenant_gucs` e
   `test_o_me_devolve_o_programa_de_cada_projeto` —, a segunda com
   `assert None == 'Transformação Financeira'`;
2. trocando-a pelo predicado **só de organização**, reprova
   `test_the_app_role_does_not_read_the_other_programme_of_its_own_account`, com o programa
   vizinho da própria conta aparecendo na leitura:

   ```
   E  AssertionError: assert UUID('8d6e7c28-…') not in {UUID('2189e852-…'), UUID('8d6e7c28-…')}
   ```

   Restaurada, verde. A segunda mutação é a que separa esta policy da versão ingênua: a
   primeira só prova que o predicado de tenant não serve.

`portal_app` fica **sem nenhuma escrita**: o programa nasce do snapshot sob `portal_system`,
como fase e entregável (ADR 0006/0008). `portal_admin` lê pela GUC de terceiro estágio, como
`project` na 0008.

### 3. `account` vence `client` na leitura, e o slug **não muda**

`sync_snapshot` passa a ler `project_data.get("account") or project_data["client"]`. Sem
nenhuma das duas, falha alto: sem organização não há tenant, e inventar um é o que a regra 1
do `AGENTS.md` proíbe.

`org_slug()` continua produzindo `biahflow-client-{id}`. **O slug é chave de persistência,
não vocabulário.** Toda organização já sincronizada está gravada com esse prefixo; trocá-lo
faz o `select` por slug não achar nenhuma delas, e o sync cria uma organização nova ao lado
— órfã de membership, de projeto e de índice. A regra que fica escrita é a distinção: o
vocabulário muda na **leitura**, a chave não. Há um teste que afirma o literal, para o
próximo rename ser decisão e não acidente.

### 4. Rotas de domínio em inglês, sem redirect

Cinco diretórios renomeados (`funil→funnel`, `conhecimento→knowledge`,
`organizacao→organization`, `resultados→results`, `assistente→assistant`), com `git mv`.
Todos os apontadores foram atualizados: os links do índice de administração, o `revalidatePath`
das server actions, o `link` explícito de `onboarding.py`, o `GOOGLE_DRIVE_REDIRECT_URI` nos
quatro lugares em que ele aparece, os runbooks e os specs de e2e (dois deles renomeados
junto).

**O que fica em português é texto visível**, e isso inclui o rótulo de aba que a URL carrega
em `?tab=Visão%20geral`: ali o valor **é** o que o cliente lê, e traduzi-lo mudaria a tela.
`tabs.py` não foi tocado.

**Nenhuma rota nova foi criada.** Não há `/engagements`, `/projects` ou `/processes`: a
superfície do cliente é uma página só com abas, e uma rota vazia seria especulação.

### 5. `Client` sai do domínio, e as duas sobrevivências são decisão

`ClientRow` virou `AccountRow`. Os componentes `*Client.tsx` continuam com o nome: eles são
React Client Components, e `FunnelClient` não é vocabulário de domínio.

Nos textos visíveis, `cliente` virou `conta` **onde o sujeito é a organização** ("Clientes
travados" → "Contas travadas"; "Nenhum cliente parado além do limiar" → "Nenhuma conta
parada"), e ficou onde o sujeito é a **contraparte humana** ("Ninguém do cliente foi
convidado", "TRAVOU NO CLIENTE"). O critério é o do próprio mapa: `Account` é a entidade,
"cliente" é rótulo de relação.

Duas sobrevivências ficam, nomeadas:

- **`client_member`** é papel de **pessoa**, não a organização. A invariante 2 fala de
  `client` como sinônimo de organização, e este não é. Trocá-lo exigiria migração de enum e
  mudança no realm do Keycloak, para nenhum ganho de significado.
- **`biahflow-client-{id}`**, pelo argumento da decisão 3.

## Consequências

- O contrato cresce: `EngagementOut`, `MeProjectOut.engagement_id`/`engagement_name` e
  `DashboardOut.engagement`. O artefato foi regerado no mesmo commit, e a guarda de consumo
  cobrou leitor para cada campo — o que a tela faz de verdade, e não por allowlist.
- O topo da barra lateral passa a desenhar a hierarquia inteira: Account → Engagement →
  Project. O rótulo do programa sai do **dashboard** e não da lista, porque quando o projeto
  da tela não está em `me.projects` (ADR 0062) só o dashboard sabe de qual programa ele é.
- A troca de contexto agrupa por programa. Projeto sem programa cai num grupo **sem
  cabeçalho, no fim** — não ganha rótulo inventado e não some da lista: a ausência é do
  Biahflow ainda não ter dito qual, não de "não pertencer a nenhum".
- Uma migração aplicada (`0020_assistant_signal_read.py`) cita `/admin/conhecimento` num
  docstring e **não foi tocada**: migração aplicada é imutável por guardrail, e ali a frase é
  registro histórico. É a mesma regra que deixou as ADRs e FDDs antigas com os nomes que
  tinham no dia.
- **O `GOOGLE_DRIVE_REDIRECT_URI` mudou.** O valor registrado no console do Google precisa
  acompanhar, ou o consentimento do Drive passa a falhar em `redirect_uri_mismatch`. É
  configuração de ambiente, fora do alcance deste repositório.

### Fica aberto

- O guard de visibilidade por campo (§3 do mapa) não existe — é a Issue #87.
- Fases canônicas e `GateDecision` (#88), KPI/Baseline/Outcome/Value Ledger (#89),
  Finding/PainPoint/ImprovementOpportunity (#90) e o lint de linguagem (#91) continuam
  abertos, nesta ordem.
- Nada disto está implementado no Pulse ainda. Os leitores são `.get()` e o snapshot de hoje
  continua válido — o que **não** é motivo para fabricar engagement quando a chave não vem.
- `EngagementStatus` chega ao contrato e a tela só usa `paused`/`closed` para qualificar o
  rótulo. Nenhuma regra de negócio depende dele deste lado, e não deve depender: quem decide
  o que um programa pausado significa é a origem.
