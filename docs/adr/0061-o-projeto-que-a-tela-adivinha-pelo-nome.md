# ADR 0061 — O projeto que a tela adivinhava pelo nome

**Status:** aceito
**Data:** 20/08/2026
**Fase:** 7 — fecha a ponta que a ADR 0059 deixou aberta com todas as letras

## Contexto

A ADR 0059 deu `?project=` a nove rotas de cliente, e o BFF passou a mandar `activeProject.id`
em todas elas. Quem decide qual é o `activeProject` é `app/page.tsx` — e quando a URL **não**
traz `?project=`, ele decidia comparando o **nome**:

```ts
projects.map((project) => ({ ...project, current: project.name === overview.project }))
```

O nome, porque `MyDashboardOut` não publicava o id do projeto que a rota serviu.

**E o nome era a única coisa ligando duas rotas que ordenam por critérios diferentes.**
`GET /me` lista por `Project.created_at.desc()` (`access.visible_projects`).
`GET /me/dashboard` resolve por `Membership.created_at.desc()`, com prioridade ao vínculo
direto (`access.default_project`). São perguntas diferentes com respostas diferentes, e nada
no contrato as reconciliava.

Com dois projetos **homônimos** no mesmo tenant — mesma organização, mesmo nome, ids
diferentes —, o casamento pega o primeiro da lista, que não é necessariamente o servido. A
partir daí a escolha errada é herdada por tudo o que a ADR 0059 acabou de escopar:

1. o sino mostra os avisos do outro projeto;
2. a busca responde pelo outro projeto;
3. abrir os comentários de uma pendência do projeto **servido** responde **404** — o item é
   procurado sob o tenant do outro, e a resposta é indistinguível da negação de um estranho.

É o mesmo trio que a ADR 0059 corrigiu, reintroduzido um andar acima: ela consertou *quem
recebe o parâmetro* e deixou intacto *quem escolhe o valor*. A ponta está escrita na
`Consequências` daquela ADR e repetida no `ROADMAP.md`.

**A queda em `projects[0]` é a mesma heurística com outro nome.** `DashboardClient.tsx`
escrevia `projects.find((p) => p.current) ?? projects[0] ?? null`: falhado o casamento, a tela
elegia o primeiro da lista e o mandava, com cara de escolha, para as nove rotas.

## Decisão

**Quem serviu o projeto o diz; a tela lê em vez de adivinhar.**

### `MyDashboardOut.project_id`, e só ali

`GET /api/v1/me/dashboard` acrescenta `project_id` ao lado de `organization`, no mesmo lugar e
pelo mesmo mecanismo — na rota, nunca em `build_dashboard`.

**`GET /projects/{project_id}/dashboard` não ganha o campo**, e o argumento é o da própria
docstring de `my_dashboard`: quem chama por lá **escolheu** o id e já o tem no caminho.
Devolvê-lo é o sedimento que a ADR 0029 recusa. O id é publicado exatamente no caminho em que o
cliente não pôde escolhê-lo — que é onde a pergunta "qual projeto foi este?" existe.

Tipo `str` e não `UUID`, pela regra de `schemas.py`: o produtor já entrega texto
(`str(project.id)`), e o tipo rico faria o Pydantic reserializar o byte.

O nome é `project_id`, o mesmo que `AssistantSignalOut` e `PendingCommentsOut` já usam. Um
sinônimo para escapar da colisão de guarda (abaixo) seria um segundo vocabulário para o mesmo
conceito, o que custa mais do que a guarda corrigida.

### A leitura mora em `app/page.tsx`

E isso é a guarda de consumo mandando, não estilo: o corpus de `MyDashboardOut` é aquele
arquivo sozinho. Passar o campo adiante por prop sem desreferenciá-lo ali reproduziria o
defeito `.priority` da ADR 0033 — campo entregue, tipado e jogado fora, com a rota respondendo
200 e nada vermelho.

### O `?? projects[0]` cai

Se o id servido não casa com nenhum item de `me.projects`, isso é divergência real entre duas
rotas, e eleger o primeiro escoparia sino, busca e comentários por um projeto que ninguém
afirmou. Sem casamento, `activeProject` fica `null`, `projectParam` fica `""`, o parâmetro é
**omitido** (nunca vazio — vazio é 422, ADR 0059) e as nove rotas voltam a `default_project`,
que é justamente o projeto que o dashboard serviu. A degradação aponta para o lugar certo.

### O que esta fatia **não** faz

`default_project` e `visible_projects` continuam com as ordens que têm. A divergência é
**registrada**, não corrigida: igualá-las mudaria o projeto que clientes existentes veem ao
entrar, o que é mudança de comportamento visível disfarçada de arrumação.

## O que foi medido

**A guarda de consumo nasceu falso-verde nesta fatia, e por colisão de substring.** A asserção
era `reachable.includes(".${key}")`, e **`.project_id` contém `.project`**. É a família do
`.priority` da ADR 0033, do `date`/`dated_at` da ADR 0038 e do `.item`/`.items` da ADR 0057
pela quarta vez — só que as duas anteriores foram resolvidas **renomeando o campo**, saída que
aqui custaria um vocabulário novo.

Medido apagando o único consumidor de `DashboardOut.project` (`data.project` em
`app/page.tsx:161`), com o `project_id` já publicado:

```
✔ o BFF consome todo campo que DashboardOut entrega (0.033458ms)
✔ o BFF consome todo campo que MyDashboardOut entrega (0.0365ms)
ℹ tests 92
ℹ pass 92
ℹ fail 0
```

**E o sufixo sozinho não bastou** — a correção prevista (exigir que o caractere após
`.${key}` não seja `[A-Za-z0-9_]`) deixou a mesma mutação **verde**, com a mesma contagem. A
medição achou uma segunda frouxidão, esta anterior à fatia: `...project` é um *spread* da
variável de iteração, não uma leitura do JSON, e contém `.project`. `app/page.tsx` tem um, na
linha vizinha à corrigida — de modo que o campo se dava por consumido por causa da sintaxe que
copia o objeto.

Com as duas âncoras (nada de `.` antes, nada de `\w` depois), a mesma mutação nomeia o campo:

```
✖ o BFF consome todo campo que DashboardOut entrega (0.631ms)
  AssertionError [ERR_ASSERTION]: o BFF recebe estes campos de DashboardOut e não os lê: project.
  + [ 'project' ]
  - []
ℹ tests 92
ℹ pass 90
ℹ fail 2
```

Restaurado o consumidor, 92 de 92. Nenhuma das duas âncoras é suficiente sozinha, e um acesso
encadeado legítimo (`a.b.project`) segue casando, porque ali o caractere antes do ponto é uma
letra.

**A marca `current` não tinha uma asserção sequer neste repositório** — medido por ausência,
em `tests/` inteiro. O teste novo precisou de um mundo que nenhuma fixture tinha: **dois
projetos homônimos no mesmo tenant**. É o irmão exato do achado da ADR 0059 ("o teste que
faltava era um ator com duas memberships"): com um projeto por pessoa, "o do nome igual", "o
primeiro da lista" e "o que a API serviu" são sempre a mesma linha, e a diferença não tem como
aparecer. As duas direções são exercitadas — servindo ora o primeiro, ora o segundo —, senão
"sempre o último" passaria verde numa delas.

**A marca não chega ao DOM, e isso é fato do produto e não do teste:** a `ProjectsView` só
existe depois de o cliente trocar de aba (`Trocar projeto` não está em `navItems`, então
`?tab=` não a alcança), e com nomes iguais os dois cartões teriam o mesmo texto de qualquer
forma. O que a asserção lê é o payload de hidratação que o SSR embute, que é por onde
`projects` viaja para o cliente.

**E o tenant da fixture nova precisou ser sorteado — achado na revisão, não na
construção.** `sync_snapshot` chaveia a organização por `org_slug(client["id"])`, de modo que
um `client_id` escrito à mão é uma linha **compartilhada** com todo teste que use o mesmo
número. A primeira versão desta fixture usava `client_id=71`, que `test_chat_ai.py:761`
também usa — e o teardown dela apaga a organização inteira, com cascata. A bateria passava,
nas duas ordens e em repetição, porque a coleta alfabética põe o chat antes; ou seja, o verde
dependia da ordem, que é exatamente o que as ADRs 0058 e 0060 acabaram de tirar daqui. O
`client_id` passou a sair do mesmo `uuid4` que já etiquetava o sujeito e o e-mail, numa faixa
alta que não encosta nos números baixos escritos à mão pelas outras fixtures. O defeito não
era a asserção nem o teardown: era o teardown apagar algo que a fixture não tinha criado.

**Do lado da API, o carimbo explícito é parte do teste.** `created_at` é
`server_default=func.now()`, que é o relógio da **transação**: montada a fixture numa sessão
só, as quatro linhas empatam e a divergência entre `visible_projects` e `default_project` não
acontece. Sem as datas escritas à mão, o teste passaria por sorte e continuaria passando com o
defeito de volta.

## Consequências

- **`DashboardOut` e `MyDashboardOut` deixam de ter o mesmo conjunto de chaves**, e agora há
  teste afirmando a assimetria nos dois sentidos: a rota por id **não** publica `project_id`.
  A assimetria já existia por causa de `organization`; a diferença é que agora ela é
  deliberada e verificada, e não herdada.
- **A guarda de consumo ficou mais apertada para todos os 56 esquemas**, não só para este
  campo. Nenhum outro ficou vermelho ao apertá-la, o que é uma medida da guarda e não uma
  garantia: ela continua sendo por corpus.
- **A divergência de ordem entre `GET /me` e `GET /me/dashboard` continua de pé**, agora
  escrita. Enquanto ela existir, "o primeiro projeto da lista" e "o projeto da tela" são
  perguntas diferentes, e todo código novo que precisar da segunda tem de ler `project_id`.
- **Sem casamento de id, a tela fica sem projeto nomeado** e as nove rotas caem em
  `default_project`. É degradação e não erro: o cliente vê o dashboard que a API serviu, com o
  sino e a busca do mesmo projeto, porque é o mesmo padrão dos dois lados.
- Nenhum evento de log novo, portanto nenhuma linha em `docs/runbooks/alerts.md` — a guarda de
  eventos é bidirecional desde a ADR 0034.

**E o que esta fatia não é.** O portal está fora do ar desde 13/08/2026 (ADR 0053). O defeito
exige um cliente com dois projetos de mesmo nome, e não houve cliente nenhum para observá-lo.
