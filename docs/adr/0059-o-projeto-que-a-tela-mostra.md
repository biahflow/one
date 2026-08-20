# ADR 0059 — O projeto que a tela mostra, e o parâmetro que ninguém mandava

**Status:** aceito
**Data:** 20/08/2026
**Fase:** 7 — fecha o item F1 que a ADR 0057 mediu, nomeou e não corrigiu

## Contexto

`access.default_project` devolve a membership **mais recente** da pessoa. Onze rotas de
cliente resolviam o projeto assim, e nenhuma aceitava o projeto que está na tela —
enquanto o dashboard ao lado vem de `/api/v1/projects/{project_id}/dashboard`, que o BFF
escolhe a partir do `?project=` da URL.

Para um cliente com dois projetos, vendo B por `?project=B`, isso significa três coisas
diferentes, e a terceira é a que dói:

1. o sino mostra os avisos de **A**;
2. a busca responde por **A**, e a FDD 018 dizia por escrito *"o topbar é do projeto
   corrente"*;
3. abrir os comentários de uma pendência de B responde **404** — o item é procurado sob o
   tenant de A, e a resposta é indistinguível da negação de um estranho.

A ADR 0057 mediu isso ao construir a âncora, escreveu o mecanismo com os arquivos, **se
defendeu** dele (o link do aviso carrega `?project=` e a navegação in-app recusa interceptar
quando o projeto não é o desenhado, caindo no `href`) e deixou o item aberto com todas as
letras, porque corrigi-lo é mudança de contrato de outra superfície. É esta fatia.

**De quebra, e é o achado que carrega a guarda nova:** `POST /api/v1/chat` **já** aceitava
`project_id` no corpo e o honrava com `access.scoped_project` desde a Fase 3 — e o BFF
**nunca o mandou**. O corpo saía com `{question, conversation_id}`, e o projeto acabava
sendo, também ali, a membership mais recente. É o espelho exato do achado da ADR 0033: lá um
painel publicado sobre um campo que nunca teve escritor; aqui um campo de **entrada**
publicado que nunca teve remetente. A guarda de consumo daquela ADR não o pega, e não por
descuido: ela pergunta se o BFF **lê** o que a API entrega, e este é o outro sentido.

## Decisão

**Quem nomeia o projeto é a tela; quem não nomeia continua caindo no padrão; quem nomeia um
projeto que não alcança recebe 404.**

### `access.chosen_project`, e ele não inventa política nenhuma

Com id, delega a `scoped_project` — que já valida a membership, já registra `authz.denied`
com razão e já chama `bind_tenant`. Sem id, delega a `default_project`. É a generalização
literal da ramificação que `POST /chat` escrevia à mão desde a Fase 3: as duas metades já
existiam, e o que faltava era o lugar onde a escolha acontece.

**Alheio ou inexistente é 404, nunca queda silenciosa no padrão.** Cair no padrão devolveria
a lista de *outro* projeto com 200, que é o `.get(kind, _CLIENT_ONLY)` da ADR 0040 na mesma
forma: o esquecimento entrega ao cliente a coisa errada em vez de recusar. E é 404 e nunca
403, como toda negação deste contrato.

O parâmetro é **opcional** de propósito: as onze rotas respondiam pelo padrão desde a Fase 1,
e um parâmetro obrigatório transformaria uma correção em quebra de contrato.

### Nove rotas ganham `?project=`; a décima não, e está escrito por quê

`GET /api/v1/me/dashboard` **fica sem o parâmetro**. O caminho por id já existe em
`/projects/{project_id}/dashboard` e é o que o BFF usa quando a URL nomeia projeto; publicar
um segundo caminho para a mesma coisa é sedimento (ADR 0029). As outras ganharam justamente
por **não** terem esse caminho.

`POST /chat` mantém o projeto no **corpo**, e a assimetria é deliberada: o campo é publicado
desde a Fase 3 e trocá-lo por query quebraria o contrato para consertar uma inconsistência de
estilo.

O nome publicado é `project` — o mesmo da barra de endereço e o mesmo que o `deep_link`
escreve. Em Python ele é `project_id` com `alias="project"`, porque `project` colidiria com a
variável local das nove funções; o precedente é o `from_ … alias="from"` do mesmo arquivo.

### A guarda: todo parâmetro de entrada publicado tem quem o envie

Espelha a guarda de consumo da ADR 0033, na direção que faltava. Alcance: `query` e
`requestBody`; parâmetro de caminho fica de fora, porque a URL o carrega por construção.
Allowlist `NOT_SENT` com motivo escrito por linha e asserção de obsolescência, como as duas
allowlists vizinhas.

Ela **nasceu vermelha sobre o defeito real**, antes de o BFF ser tocado:

```
✖ o BFF envia todo parâmetro que /api/v1/chat recebe
  estes parâmetros existem no contrato e nenhum chamador de /api/v1/chat os envia:
  POST /api/v1/chat project_id.
```

## O que foi medido, e é o que dá valor à guarda

**Três frouxidões independentes, cada uma capaz de deixá-la verde sobre um defeito real.**
As três foram observadas, não deduzidas, e as três precisaram ser fechadas — com qualquer uma
aberta a guarda passa.

1. **Corpus único dá falso verde** (a terceira ocorrência desta família, depois do
   `.priority` da ADR 0033 e do `date`/`dated_at` da ADR 0038). Com um corpus único sobre
   `app/**`, `ChatIn.project_id` passa verde: as três ocorrências de `project_id` em `app/`
   são leitura de **resposta** — o painel de `/admin/assistente` e o callback do Drive —,
   nunca envio. E o mesmo corpus declara obsoletas três isenções legítimas do produtor de
   eventos, então ele erra nas duas direções ao mesmo tempo.
2. **Nome solto casa onde não há envio.** `\bproject\b` casa com `projects.map((project) =>`
   em `app/page.tsx`, o que daria o `?project=` da caixa de avisos como enviado **antes de
   ele existir**. O casamento é por posição de envio: query dentro de uma URL ou montada peça
   por peça; corpo como chave de objeto.
3. **Ler não é mandar, e o corpus tinha de encolher junto.** Estas duas saíram da revisão,
   depois de a guarda já estar verde, e por isso importam: com o corpus incluindo os
   *consumidores* da rota — que é o certo para a guarda de "alguém chega a esta rota?" —,
   apagar o repasse de `?project=` **dentro** de `app/api/search/route.ts` deixa tudo verde,
   porque o `&project=` do `DashboardClient.tsx`, que fala com o proxy e não com a API,
   satisfaz a busca do nome. Encolher o corpus para quem **monta a requisição** não bastou:
   o proxy contém `query.get("project")` — o parâmetro que ele recebe e descarta —, e a aspa
   solta o dava como enviado. Só com as duas correções a mutação fica vermelha:

   ```
   ✖ o BFF envia todo parâmetro que /api/v1/me/search recebe
     …nenhum chamador de /api/v1/me/search os envia: GET /api/v1/me/search project.
   ```

   Medido em separado: mantendo o casamento apertado e devolvendo os consumidores ao corpus,
   a mesma mutação volta a passar verde. As duas são necessárias, e nenhuma é suficiente.

**O caso negativo tem controle positivo, e é ele que dá sentido ao 404.** As nove rotas são
exercitadas com um alvo **real** do tenant do chamador — documento, pendência, conversa e
mensagem existentes —, e a única coisa que muda entre a chamada negada e a aceita é o
`?project=`. Sem isso, um id inventado daria 404 pelos dois motivos ao mesmo tempo, e uma
rota que negasse por engano — ou que nem existisse — passaria igual: é a frouxidão que a ADR
0035 mediu ao dar `POST /chat` como coberto por um 404 que era de outra rota. A mutação que
prova o par (`chosen_project` → `default_project` nas nove) devolve `200` em sete rotas e
`503` numa oitava, todas onde se esperava `404`.

**O teste que faltava neste repositório inteiro era um ator com duas memberships.** Com um
projeto por pessoa — que é como todas as fixtures nasceram —, "o mais recente" e "o que está
na tela" são sempre o mesmo projeto, e a diferença entre `default_project` e `chosen_project`
**não tem como aparecer**. É por isso que o defeito atravessou seis fases sem nada ficar
vermelho.

## Consequências

- **`?project=` vazio é 422, não "sem parâmetro"** — e é por isso que todo remetente do BFF
  **omite** o parâmetro quando não há projeto conhecido, em vez de mandá-lo vazio. Há teste.
- **`projectQuery()` fica duplicado em quatro arquivos do BFF**, e a recusa de extraí-lo é
  medida: o corpus da guarda é o arquivo que monta a requisição, e o literal num módulo
  compartilhado sairia do corpus de quem chama — a prova de que cada chamador manda o
  parâmetro se perderia. A duplicação é o preço da verificabilidade, ao contrário da de
  `textfold.py`, onde a divergência é que era invisível.
- **Fica aberto e nomeado:** `activeProject` cai em `projects[0]` quando o casamento por nome
  de `app/page.tsx` falha — dois projetos homônimos no mesmo tenant fariam a tela nomear um
  projeto diferente do que a API serviu. É pré-existente a esta fatia e não foi tocado.
- Nenhum evento de log novo, portanto nenhuma linha em `docs/runbooks/alerts.md`: a negação
  já é registrada por `scoped_project` como `authz.denied`, com razão e prefixo do sujeito, e
  a guarda de eventos é bidirecional desde a ADR 0034.

**E o que esta fatia não é.** O portal está fora do ar desde 13/08/2026 (ADR 0053). O defeito
que ela corrige exige um cliente com dois projetos, e não houve cliente nenhum para observá-lo.
