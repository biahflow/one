# ADR 0062 — O robô que abria o PR que ninguém mergeava

**Status:** aceito
**Data:** 20/08/2026
**Fase:** 7 — e uma emenda à ADR 0061, aceita no dia anterior

## Contexto

Duas coisas sem relação entre si, na mesma fatia porque as duas são a mesma pergunta em
escalas diferentes: **um mecanismo que parecia cobertura e não era**.

### O robô

A ADR 0023 montou o portão de dependências vulneráveis e deu a ele um segundo andar. Quem
**reprova** é o job `dependency-audit`, que roda `scripts/audit.mjs` a cada push; quem
**conserta** era o Dependabot, com quatro ecossistemas declarados em `.github/dependabot.yml`
— npm, pip, `github-actions` e `docker`. A ordem era deliberada e está escrita lá: os alertas
de segurança nativos do GitHub dependem da mesma configuração de repositório que o `codeql`
não tem, então confiar neles seria confiar num controle que este repositório não pode ligar.

O arquivo previa a forma pela qual o mecanismo se estraga, e a previsão está no comentário do
próprio `dependabot.yml`:

> *Semanal e com teto baixo de PRs abertos de propósito: um robô que abre vinte PRs por semana
> treina a equipe a fechá-los sem ler, que é a forma de este mecanismo virar o oposto do que é.*

**O que ele não previu é que o teto transformaria o desuso em bloqueio.** Havia 16 PRs abertos,
os mais antigos de 05/08, e três dos quatro tetos estavam saturados ou estourados:

| Ecossistema | `open-pull-requests-limit` | PRs abertos |
|---|---|---|
| npm | 5 | **5** |
| `github-actions` | 3 | **3** |
| pip | 5 | **6** |
| docker | 3 | 2 |

Com o teto cheio o Dependabot **não abre PR novo naquele ecossistema**. Inclusive o que
consertaria um aviso futuro. O mecanismo que a ADR 0023 chama de "quem abre o PR que conserta"
estava, na prática, travado por PRs que ninguém mergeava — três dos quatro ecossistemas mudos,
e o quarto a um PR de ficar. Um robô que não pode abrir o PR do próximo aviso não é o segundo
andar do portão: é uma linha de configuração que parece ser.

### Os três pontos que a ADR 0061 deixou nomeados

A ADR 0061 tirou do BFF o casamento por **nome** de projeto e publicou `MyDashboardOut.project_id`.
Ela fechou o defeito e deixou três coisas escritas nas próprias `Consequências`:

**(a) A divergência de ordem continua de pé.** `GET /me` lista por `Project.created_at.desc()`
(`access.visible_projects`); `GET /me/dashboard` resolve pela membership mais recente com
prioridade ao vínculo direto (`access.default_project`). Duas perguntas, dois critérios, zero
código em comum — e o que as reconciliava era exatamente o nome que a ADR 0061 acabara de
proibir. A frase de lá é literal: *"o primeiro projeto da lista" e "o projeto da tela" são
perguntas diferentes, e todo código novo que precisar da segunda tem de ler `project_id`.*

**(b) A degradação é silenciosa.** Sem casamento de id, `activeProject` fica `null`, o
`?project=` é omitido e as nove rotas da ADR 0059 caem em `default_project` — que é o mesmo
projeto que o dashboard serviu. A tela é coerente, e é por isso que a ADR 0061 chamou aquilo de
degradação e não de erro. Só que **nada em lugar nenhum diz que aconteceu**: nem uma linha de
log, nem um pixel na tela. Duas rotas discordando sobre a mesma membership é fato sobre o
servidor, e ele não tinha por onde aparecer.

**(c) O rótulo do topbar mistura duas coisas.** Na **mesma linha de UI** do
`project-switcher`, com o mesmo `activeProject` nulo, o logo caía para `user.org` e o `<small>`
ao lado caía para `overview.project`. Dois fallbacks de naturezas diferentes para um estado só,
e o do logo errado: ali é o lugar do projeto, não da organização.

## Decisão

### O Dependabot sai, e o arquivo é apagado

`git rm .github/dependabot.yml`. **Não esvaziado** — um arquivo de configuração vazio é
ambíguo, e a próxima pessoa a abri-lo não tem como distinguir "desligado por decisão" de
"alguém começou e não terminou". A ausência do arquivo é a única forma que o GitHub reconhece e
a única que se lê sem contexto.

O `docs/runbooks/dependency-advisory.md` afirmava que "o Dependabot abre o PR que conserta,
semanalmente". Passa a dizer que o conserto é **manual**, com nota de correção datada — a
convenção deste repositório para documento comum, cujo precedente é `docs/ai/context-contract.md`
sob a ADR 0038. A ADR 0023 **não** é reescrita: uma retificação de ADR aceita é ADR nova, que é
a regra que a ADR 0060 mediu e escreveu. A linha dela fica onde está; esta é o que a corrige.

### `preferred_project`, e só a ordem de `/me`

A escolha que estava dentro de `default_project` sai para `access.preferred_project`, que
responde *qual projeto* sem publicar GUC nenhuma. `default_project` passa a ser ela mais
`bind_tenant`, e essa é toda a diferença entre as duas funções. `visible_projects` — que
deliberadamente **não** faz bind, porque a listagem atravessa projetos enquanto as GUCs de
segundo estágio guardam um — chama a mesma função e põe o projeto escolhido **em primeiro**,
mantendo o resto por `Project.created_at.desc()`.

**Qual projeto `default_project` devolve não muda, e é isso que separa emendar a ADR 0061 de
revertê-la.** Aquela ADR recusou igualar as duas rotas com o argumento de que "igualá-las
mudaria o projeto que clientes existentes veem ao entrar, o que é mudança de comportamento
visível disfarçada de arrumação" — e o argumento continua valendo, integralmente. O que muda
aqui é a **ordem de uma lista**, não a resolução do dashboard. Os dois critérios seguem
distintos, e é por isso que a asserção que os separa continua no teste.

O reordenamento **move, nunca acrescenta**: um projeto que a listagem não carrega é um projeto
que a membership não cobre, e prependê-lo publicaria uma linha que `GET /me` não tem base para
mostrar.

### O evento nasce no servidor, e a tela diz

`web.project_unmatched`, emitido em **`app/page.tsx`**. O sítio não é estilo: `DashboardClient.tsx`
é `"use client"`, e um `logWarn` ali roda no browser e nunca chega ao stdout do BFF. `page.tsx`
já é server component, já emite `api.failed` e é onde `servedProjectId` e `projects` coexistem.
`extra` traz `requested_project_id` (nulo quando a URL não nomeou projeto), `served_project_id`
e `listed` — e a distinção importa: com `?project=` quem respondeu foi
`/projects/{id}/dashboard`, que por desenho da ADR 0061 **não** publica `project_id`, de modo
que o id pedido é o único que se tem.

Linha nova em `docs/runbooks/alerts.md` no mesmo commit, sob "avisam, sem acordar", limiar de 3
em 1 h. A guarda de eventos é bidirecional desde a ADR 0034 e enxerga o BFF desde a ADR 0035;
as duas direções foram medidas abaixo.

E o `project-switcher` ganha sinal quando `activeProject` é nulo: borda e fundo de estado
(`warning-50`/`warning-600`, tokens do `@theme` — nenhum hex no componente), um `title` e a
linha "Fora da sua lista de projetos". **Ele afirma só o que se sabe** — que o projeto da tela
não está na lista —, nunca qual deveria ser: inventar o segundo é o `answerFor()` da ADR 0021
com outra roupa. A borda sobrevive à sidebar recolhida, que esconde o bloco de texto.

### O fallback do logo passa a ser o do `<small>`

Os dois textos daquela linha falam do projeto, então os dois leem `overview.project` — o nome
que a API serviu, que é factualmente o projeto na tela. `<strong>{user.org}</strong>` continua
sendo a organização, porque ali é o lugar dela.

**Unificar é seguro agora e não era antes.** O nome segue sendo **rótulo** e nunca identidade:
a identidade é o `project_id` da ADR 0061, e enquanto o nome *era* o elo entre as duas rotas,
usá-lo em mais um lugar era ampliar a superfície do defeito. Com o elo desfeito, o nome só
precisa ser legível.

Os outros dois usos de `overview.project` (`ProfileView`, `ViewHero`) já estavam certos e ficam.

## O que foi medido

**Os tetos, que são o argumento da metade A.** npm 5/5, `github-actions` 3/3, pip 6/5, docker
2/3, com 16 PRs abertos e os mais antigos de 05/08. Três dos quatro ecossistemas não abririam
PR novo nem para um aviso crítico. Não é uma inferência sobre o robô: é o estado dele.

**A mutação da ordem reprova o teste da ADR 0061, e reprova nomeando ids.** Desfeito o bloco de
reordenamento em `visible_projects`:

```
......F..                                                                [100%]
E       AssertionError: assert '80c9fd5d-592...-1130be49360f' == '87c2dcec-bd9...-bf1dc34f512c'
E         - 87c2dcec-bd9a-4900-ac5c-bf1dc34f512c
E         + 80c9fd5d-592a-42bc-990b-1130be49360f
apps/api/tests/test_dashboard_scope.py:258: AssertionError
```

**O teste que quebrou é o de ontem, e quebrou por desenho.** `test_dashboard_scope.py` afirmava
`listed[0]["id"] != body["project_id"]` — escrito pela ADR 0061 *para provar que as duas ordens
divergiam*. Com esta fatia ele passa a estar errado sobre o produto, e a asserção não foi
apagada: foi **movida**. O que ela cobria de verdade é que os dois critérios são distintos, e
isso continua afirmado — o mais recente por `Project.created_at` não é o servido, e segue na
lista, agora na segunda posição. Sem esse par, igualar os dois critérios (recusado acima)
passaria verde aqui.

O campo `Homonyms.listed_first_id` foi renomeado para `newest_id` pela mesma razão que fez a ADR
0038 renomear `date` para `dated_at`: o nome antigo descrevia a **posição**, a posição mudou, e
um nome que mente é pior que um nome longo. O campo passou a nomear o **critério**.

**As duas direções da guarda de eventos, uma de cada vez.** Apagando a linha nova do
`alerts.md`:

```
E       AssertionError: estes eventos são emitidos e não têm linha em `docs/runbooks/alerts.md`:
        web.project_unmatched. Dê limiar e destino a cada um, ou declare em NOT_AN_ALERT por que
        ninguém precisa ser avisado (ADR 0034).
E       assert ['web.project_unmatched'] == []
```

Apagando o `logWarn` de `page.tsx` e mantendo a linha do runbook:

```
E       AssertionError: o `alerts.md` manda vigiar estes eventos e nenhum código os emite:
        web.project_unmatched. Emita-os, ou tire a linha — um limiar sobre um contador pinado em
        zero é pior que nenhum, porque parece cobertura (ADR 0028/0034).
E       assert ['web.project_unmatched'] == []
```

As duas passam pela varredura de `_WEB_DIRECTORIES`, que só existe desde a ADR 0035 — antes
dela a guarda parava na fronteira do pacote Python e um evento do BFF era invisível para os dois
lados.

**E um efeito colateral que a medição encontrou e que não é defeito.** `GET /me` deriva
`MeOut.organization` de `visible[0][0].organization_id` (`main.py:779`). Com a lista reordenada,
o nome da organização publicado passa a ser o do projeto **servido** em vez do projeto mais
recente. Para quem tem membership em uma organização só — todo cliente do produto — é a mesma
linha. Para um interno com vínculo em duas, a resposta melhora: a organização nomeada passa a
ser a do dashboard que está na tela, que era a única leitura em que aquele campo fazia sentido.

**Portões, todos verdes:** 643 testes de API (0 pulados, sem `test_backup_restore.py`),
`alembic check` sem deriva, `npm run test:contract` 92/92, `node --test tests/rendered-html.test.mjs`
22/22, `npm run build` e `npm run lint` (0 erros; os 4 avisos são de `coverage_html.js`, dentro
do `.venv`, e são anteriores a esta fatia).

## Consequências

- **`github-actions` e `docker` ficam sem detecção e sem atualização.** É perda de cobertura
  real e está aceita, não contornada. A ADR 0023 já registrava que `npm audit` e `pip-audit`
  medem só o que conhecem, e que o Dependabot cobria aqueles dois "por atualização, nenhum dos
  dois por detecção". Sem ele, as actions do `ci.yml` — que executam **com o token do workflow**,
  a única dependência que roda *dentro* do CI em vez de ser auditada por ele — e as duas imagens
  base, fixadas em versão exata pela ADR 0022, congelam na CVE do dia em que foram escolhidas até
  alguém subir o pin à mão. Não é verdade que nada se perde.
- **npm e pip continuam cobertos, e por quem reprova.** O `dependency-audit` roda em `push` e
  em `pull_request`, sem limiar de severidade, e a única forma de um aviso não reprovar continua
  sendo uma linha datada em `docs/security/advisories.json`. O andar que caiu é o do conserto
  automático, não o da detecção — e era o andar que estava travado.
- **O conserto passa a ser trabalho de pessoa**, e o runbook diz isso com todas as letras,
  incluindo a instrução de revisar as actions e as imagens base junto, porque nada mais o fará.
- **A ordem de `GET /me` mudou; a resolução de `GET /me/dashboard` não.** Um cliente com dois
  projetos vê a lista começando por outro item a partir daqui. É mudança visível, e é a menor
  que fecha o ponto (a) sem cair na que a ADR 0061 recusou.
- **Os dois critérios continuam distintos**, e isso é deliberado: `preferred_project` é uma
  função só, mas `Project.created_at` e `Membership.created_at` seguem respondendo a perguntas
  diferentes. Igualá-los de verdade continua fora de escopo, agora com um teste que reprovaria
  quem o fizesse por acidente.
- **O ponto (b) deixou de ser silencioso nos dois canais** — log no servidor, sinal na tela — e
  a ADR 0061 podia registrar "nenhum evento de log novo, portanto nenhuma linha em
  `docs/runbooks/alerts.md`". Esta acrescenta o evento e a linha.
- **Uma ocorrência de `web.project_unmatched` significa outra coisa a partir de hoje.** Antes
  desta fatia ela seria ordem divergente, que era o caso comum e benigno; com a lista abrindo
  pelo projeto servido, o que sobra é `/me` e `/me/dashboard` discordando sobre a própria
  membership. O limiar do runbook foi escrito para o caso raro, não para o antigo.

**E o que esta fatia não é.** O portal está fora do ar desde 13/08/2026 (ADR 0053). A metade B
corrige um defeito que exige um cliente com dois projetos, e não houve cliente nenhum para
observá-lo; a metade A é sobre um mecanismo de repositório, que continua valendo com o produto
fora do ar — o código é mantido, e dependência vulnerável não espera o produto voltar.

## Alternativas recusadas

**Subir os tetos de `open-pull-requests-limit`.** Trocaria dezesseis PRs não lidos por trinta.
O teto não é a causa: a causa é que ninguém mergeia, e o próprio arquivo já argumentava contra
o volume alto. Um teto maior compra tempo até saturar de novo, e o estado saturado é
indistinguível do estado normal olhando o CI.

**Deixar o Dependabot ligado só em `github-actions` e `docker`**, que é onde ele era único.
Tem apelo — são exatamente os dois que ficam descobertos. Mas `github-actions` era um dos três
ecossistemas **saturados** (3/3), então manter a linha manteria a aparência da cobertura com o
mesmo bloqueio por trás. Ligar de novo é uma linha de YAML no dia em que houver quem mergeie; o
que não se pode é chamar de cobertura o que está travado.

**Igualar `default_project` e `visible_projects`.** É a correção "de verdade" do ponto (a), e é
justamente a que a ADR 0061 recusou por mudar o projeto que clientes existentes veem ao entrar.
Nada mudou nesse argumento em um dia. A ordem da lista é o que se pode corrigir sem tocar em
qual dashboard a API serve.

**Emitir o evento no `DashboardClient`, onde `activeProject` de fato é calculado.** É o sítio
óbvio e é o errado: o arquivo é `"use client"`, e a linha sairia no console do browser. O que se
quer é uma linha no stdout do BFF, filtrável por `event` junto das da API (ADR 0018).

**Reescrever a ADR 0023 e a ADR 0061.** As duas afirmam hoje coisas que deixaram de valer — o
Dependabot como mecanismo secundário ativo, e a divergência de ordem "de pé". Corrigi-las no
lugar apagaria o registro de por que cada uma decidiu o que decidiu, que é a memória que faz
estas ADRs valerem alguma coisa. A regra está escrita na ADR 0060 e é seguida aqui.
