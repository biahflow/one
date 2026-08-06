# ADR 0026 — Os controles inertes, e a guarda que é sobre o botão e não sobre o dado

**Status:** aceita — 06/08/2026
**Contexto:** Fase 6. Corrige a afirmação de que a busca era o último controle de demonstração
na tela do cliente — havia mais onze — e fecha a categoria inteira com um portão.

## Contexto

A ADR 0024 termina dizendo que o `<input>` da lupa era *"o último controle de demonstração na
tela do cliente"*. O `ROADMAP.md` repete a frase e o `CLAUDE.md` a repete uma terceira vez,
como *"o último resto de casca de demonstração no produto"*.

**As três estavam erradas, e pela mesma quantidade: onze.** Em `app/DashboardClient.tsx`, todos
na tela do cliente, nenhum no `/admin`:

| Linha | Controle | O que havia atrás |
|---|---|---|
| 967 | "Ver cronograma" | nada — mas a aba existia e `goTo()` existia |
| 989 | "Ver todas as pendências" | nada — idem |
| 941 | "Ver detalhes" (status-card) | nada, e nenhum destino a inventar |
| 1337 | "Editar" (Meu perfil) | nada, e o banco recusa por desenho |
| 1457 | "Salvar alterações" (Configurações) | nada, sob três valores fixos |
| 984, 995, 1077, 1109, 1116, 1518 | seis menus `⋯` | nenhum handler, nenhum menu |

Isto **não** é a oitava repetição do padrão da Fase 5, em que um documento prometia o que o
código não fazia. É a segunda repetição do padrão da ADR 0024, que é pior: a promessa está onde
quem paga pelo produto a encontra sozinho, no primeiro dia, e sem forma de distingui-la de um
defeito. Clicar em "Ver todas as pendências" e não sair do lugar é indistinguível de um bug de
navegação.

### Por que sobreviveram à fatia que dizia tê-los eliminado

Porque **toda guarda deste repositório é sobre dado, e nenhuma é sobre affordance.**

`tests/rendered-html.test.mjs` casa strings do HTML do SSR e varre o código-fonte atrás de
literais fabricados: o `answerFor()` que inventava citação (ADR 0021), os três cards da Fase 3,
o `sources: ["…"]` no cliente, o `hits: [{…}]` da busca. Todas perguntam *"este valor foi
inventado?"*. Nenhuma tem como perguntar *"este botão faz alguma coisa?"* — e o motivo é
estrutural: um `<button>` sem `onClick` renderiza HTML byte a byte idêntico a um que funciona.
Não há string a casar. O Playwright tampouco: ele clica e nada acontece, que é exatamente o
que um teste de clique sem asserção posterior espera.

O array `prefs` de Idioma/Fuso/Tema escapou até da guarda de dado, e pela fuga que o comentário
daquele teste **já documenta**: a asserção é `^const (documents|meetings|…) = `, ancorada no
topo do módulo, e `prefs` era array local dentro de `SettingsView` — literalmente a razão que o
comentário dá para os três cards da Fase 3 terem durado duas fases.

### A regra já estava escrita, no arquivo, uma função acima

`SettingsView` abre com um comentário que decide o caso inteiro:

> Uma preferência, e ela é real. As outras duas que existiam aqui eram decorativas — **um
> interruptor que não liga nada é pior do que não ter.**

Ela foi aplicada a dois switches e não aos onze controles em volta, incluindo o "Salvar
alterações" a quinze linhas de distância. Uma regra que vale onde alguém lembrou de aplicá-la é
uma preferência de estilo; esta fatia a torna mecânica.

## Decisão

### 1. Ligar dois, apagar nove — o critério é ter destino, não ter rótulo plausível

"Ver cronograma" e "Ver todas as pendências" apontam para abas que existem, com um `goTo` que
existe desde a Fase 2 e que `ProfileMenu` já recebe como `onNavigate`. Eram uma linha cada. Não
ligá-los seria escolher a leitura preguiçosa da regra.

Os outros nove não têm destino, e **inventar um seria o defeito de novo com melhor acabamento.**

### 2. "Editar" não é feature faltando — é feature errada

Este é o único que pareceria uma pendência legítima de backlog, e não é. Nome e e-mail vivem no
Keycloak (ADR 0010/0011), e o GRANT de coluna de `portal_app` em `user` é
`(external_subject, notify_by_email, updated_at)` — **deliberadamente** sem nome e sem e-mail,
pela mesma razão que "marcar como lida" não pode virar "reescrever o aviso" (ADR 0012). O botão
prometia uma escrita que não tem rota, e que a policy recusaria se tivesse.

Implementá-lo exigiria uma rota de escrita de perfil contra a ADR 0010, ou um proxy para a
Account API do Keycloak — decisão de produto com ADR própria, não um `onClick`. No lugar ficou
uma frase dizendo de onde o dado vem e como se muda, que é a informação que a pessoa que clicaria
no botão estava procurando.

### 3. Os seis `⋯` estão errados por arquitetura, não por implementação

Um menu de contexto num painel de marcos ou de pendências teria de oferecer ações sobre o
andamento do projeto. **O portal não origina status** (ADR 0006/0008): a digitação vive no
Biahflow e chega por snapshot. Não há ação para pôr ali sem dividir a fonte da verdade — o
mesmo argumento que a Fase 2 usou para riscar o CRUD interno do roadmap.

### 4. Idioma, fuso e tema são constantes do produto, e a tela passa a dizer isso

Persisti-los custaria migração, policy, GRANT de coluna e uma rota, para guardar três valores
que ninguém pode mudar. O painel "REGIÃO" declara os três em prosa e não tem botão. É a mesma
escolha da decisão 2: quando não há o que salvar, a resposta honesta é a frase, não o botão.

### 5. A guarda é sobre a forma do controle, e é isso que a torna nova

`inertButtons()` em `tests/rendered-html.test.mjs` varre todo arquivo sob `app/` e
`components/` e exige que **todo `<button>` carregue `onClick=` ou `type="submit"`**. É a
primeira asserção do repositório que não olha um valor.

`type="submit"` conta porque o `<form action={…}>` do Server Action é o que o aciona — handler
declarado do outro lado. É o caso do "Sair", e o `/admin` inteiro depende dele.

**O regex ingênuo não serve, e isso foi medido, não deduzido.** `<button[^>]*>` dá falso
positivo no sino, cujo `aria-label={unreadCount > 0 ? … }` tem um `>` dentro da expressão: o
casamento fecha a tag cedo e esconde o `onClick` da linha seguinte. Um portão que acusa um
controle correto é um portão que alguém desliga. A varredura balanceia `{}` e pula strings até
o `>` de verdade — dez linhas, e com elas os sete componentes dão exatamente os onze de cima e
zero depois da fatia.

Junto, os literais `"Português (Brasil)"` e `"(GMT-3) São Paulo"` entram no laço de proibidos
que já existe, fechando a fuga do array local.

## Consequências

- **Nenhum controle inerte na tela do cliente, e a afirmação virou verificável.** "O último
  controle de demonstração" deixou de ser uma frase que já errou duas vezes e passou a ser uma
  asserção que reprova no `npm test`.
- **A guarda nasceu vermelha e há prova disso.** Antes das correções ela listava os onze; um
  `<button className="icon-button">` reintroduzido faz o teste apontar arquivo e linha. É o
  argumento que a ADR 0020 usou contra as asserções de backup que pulavam em silêncio: uma
  guarda que nasce verde não demonstra nada.
- **A tela ficou menor.** Saíram nove controles e não entrou nenhum. Duas frases substituíram
  dois botões, e em ambos os casos a frase carrega a informação que o botão prometia buscar.
- **CSS morto foi junto:** `.details-link` (e sua regra de breakpoint) e `.settings-save`
  ficaram sem uso. `.panel-note` divide a declaração de `.empty-note` em vez de duplicá-la:
  mesma aparência, semântica diferente — a lista não está vazia, o painel é que explica de onde
  vem o que ele mostra.
- **De quebra, um dado fabricado no caminho do demo:** o status-card mostrava "Atualizado há 2
  dias" quando a fonte não era `live`. É alcançável só pela casca de demonstração, que é
  legítima e fica atrás de `demoShellEnabled()` — mas um carimbo de frescor inventado é
  exatamente o que aquele portão não deveria deixar passar. Virou "Dados de demonstração".
- **O que a guarda não pega, declarado:** um `onClick={() => {}}` passa. Ela distingue controle
  ligado de controle inerte, não handler útil de handler vazio — e a segunda pergunta não tem
  resposta sintática. O que ela garante é que reintroduzir um botão morto exige escrever um
  handler vazio de propósito, que é uma coisa que não se faz por distração.
- **Nada mudou no servidor.** Sem migração, sem rota, sem contrato: `docs/api/openapi.json` não
  se move e o `alembic check` não tem o que dizer.

## Alternativas recusadas

**Ligar os nove.** Exigiria inventar destino para "Ver detalhes", rota de escrita de perfil
contra a ADR 0010, três colunas para preferências imutáveis, e ações de menu que o portal não
pode ter por não originar status. Seria a casca de demonstração de novo, agora com backend.

**Deixar os `⋯` como "em breve".** Um rótulo de espera é a mesma promessa com prazo implícito,
e este repositório já mediu quanto tempo uma ressalva em itálico sobrevive sem ser lida: duas
fases, no critério de aceite da Fase 1 (ADR 0024).

**A guarda no ESLint, com `jsx-a11y` ou regra própria.** Seria o lugar canônico, e é a opção que
eu escolheria num repositório sem esta história. Aqui não: as guardas de fabricação vivem todas
no mesmo teste, com o comentário explicando qual defeito cada uma segura, e é o conjunto delas
que se lê para responder "o que impede a casca de voltar". Espalhar a oitava por outra ferramenta
custaria a única coisa que faz as sete anteriores funcionarem. Além disso, o `eslint .` deste
repositório varre o `.venv` e já emite avisos que ninguém lê — acrescentar um erro ali seria
pô-lo no lugar de menor atenção.

**Asserção sobre o HTML renderizado ("o botão X leva à aba Y").** Cobre os dois que foram
ligados e nenhum dos nove que saíram, porque um botão apagado não deixa HTML para afirmar sobre.
Pega regressão de comportamento, não a categoria. Os dois cliques novos ganham cobertura no e2e,
que é onde a navegação real pode ser observada.

**Varrer também `<a>` sem `href` e `<input>` sem `onChange`.** O segundo é a lupa da ADR 0024, e
o teste já o cobre nominalmente. Generalizar agora seria escrever um portão contra defeitos que
não foram medidos neste repositório — e a lição das duas fatias anteriores é que o portão bom
nasce de uma varredura que achou alguma coisa.
