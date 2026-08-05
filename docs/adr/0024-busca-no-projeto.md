# ADR 0024 — A busca do projeto

**Status:** aceita — 05/08/2026
**Contexto:** Fase 6. Fecha o critério de aceite da Fase 1 que dependia de uma busca que não
existia, e o último controle de demonstração na tela do cliente.

## Contexto

O topbar do portal tem uma lupa desde a primeira versão da tela. Ela abre um popover com um
campo e uma frase:

```tsx
<input autoFocus placeholder="Buscar documentos, reuniões, pendências..." aria-label="Buscar no projeto" />
<p className="popover-hint">Comece a digitar para buscar no contexto do projeto.</p>
```

O `<input>` não era controlado, não tinha `onChange`, não tinha handler e não tinha resultado.
Digitar não fazia absolutamente nada — e a frase abaixo dele afirmava que faria.

**É o mesmo padrão das sete fatias da Fase 5, com uma diferença que pesa:** as outras promessas
não cumpridas estavam em documentos, e esta estava **na tela do cliente**. Um `.env.example`
com uma variável que nenhum compose passa (ADR 0022) é uma promessa que só quem lê o
repositório encontra. Um campo de busca que não busca é uma promessa que a pessoa que paga pelo
produto encontra sozinha, no primeiro dia, e que ela não tem como distinguir de um defeito.

Não é só a tela. O **critério de aceite da Fase 1** diz, textualmente:

> um cliente autenticado só consegue consultar os projetos aos quais pertence; tentativas de
> acesso cruzado falham na API, no banco **e na busca**. *Atendido para API e banco (…); a busca
> ainda não existe — chega com o RAG da Fase 4, e o filtro por organização/projeto é requisito
> dela.*

A Fase 4 veio e passou. O RAG chegou, o índice existe, a recuperação é escopada — e nenhuma
busca foi construída, porque a recuperação da Fase 4 alimenta o **chat**, que é outra coisa. O
critério ficou parcialmente atendido com a ressalva em itálico servindo de marcador que ninguém
voltou a ler. A regra 6 do `AGENTS.md` — "adicione caso negativo de permissão para qualquer
endpoint **ou busca** nova" — nunca teve uma busca para cobrar.

## Decisão

### 1. A rota é `GET /api/v1/me/search`, sem identificador de projeto

Como `/me/dashboard`, `/me/notifications` e `/me/documents/{id}/download`: o projeto sai de
`access.default_project`, que já fixa o contexto de tenant no caminho feliz. O navegador não
manda id de projeto nenhum — e o que ele não manda é o que ninguém precisa validar (regra 1 do
`AGENTS.md`).

A negação é 404 e nunca 403, como toda rota escopada, e `test_openapi_contract.py` cobra isso
da rota nova sem que ninguém precise lembrar: as asserções dele são sobre **toda** rota, não
sobre uma lista.

### 2. Um módulo só, `portal_api/search.py`

Mesma forma de `notifications.py`, `conversations.py` e `retention.py`, e pelo mesmo motivo: a
consulta nasce em cinco repositórios diferentes, e espalhá-la faria "o que a busca alcança"
deixar de caber num arquivo — que é exatamente a pergunta de quem revisa isolamento.

O filtro de tenant **não** é montado no módulo. `TenantScopedRepository` ganhou `matching()`,
que aceita um predicado por espécie e continua aplicando `_tenant_filters()` por dentro.
Montar o filtro em `search.py` seria reimplementar a primeira barreira em outro arquivo, e o
dia em que as duas divergissem ninguém veria: a RLS continuaria certa e o teste de isolamento,
verde.

### 3. Nenhuma extensão de Postgres — a dobra de acento sai de `translate()`

`unaccent` era o caminho óbvio e foi recusado por dois motivos independentes, e os dois já
estavam medidos no repositório:

- **Extensão é objeto de banco.** Não entra num `pg_dump -n portal`, então teria de nascer em
  `infra/postgres/bootstrap/roles.sql`, em `infra/postgres/init/001-extensions.sql` **e** na
  migração — que é literalmente o defeito que a ADR 0019 encontrou no `btree_gist` no dia em
  que alguém restaurou um backup de verdade pela primeira vez.
- **`unaccent()` é `STABLE`.** Um índice funcional sobre ela exige envolvê-la numa função
  `IMMUTABLE` própria: mais um objeto de banco, que o `roles.sql` teria de possuir e o restore,
  de recriar.

`translate(lower(col), 'áàâ…', 'aaa…')` é builtin, `IMMUTABLE` e indexável, e resolve o caso
real — "reuniao" achar "Reunião" — sem acrescentar nada ao inventário do banco.

A expressão vive em `portal_api/textfold.py`, módulo folha pela razão de `scanner.py` ser um.
Ela aparece em três lugares que **têm** de ser idênticos ou o índice deixa de ser usado sem
nada ficar vermelho: a declaração em `DocumentChunk.__table_args__`, o `CREATE INDEX` da
migração 0019 e a consulta. Os dois primeiros já seriam texto duplicado pela regra que o índice
parcial do Drive escreveu no próprio modelo; o módulo é o que impede o terceiro de divergir por
conta própria. Que o índice é de fato usado foi verificado, não deduzido:

```
Bitmap Index Scan on ix_document_chunk_text_fts
  Index Cond: (to_tsvector('portuguese'::regconfig, translate(lower(text), …)) @@ '''rescisa'''::tsquery)
```

### 4. Duas fontes, e a segunda é a que faz a promessa valer

As **linhas** do read model — documento, reunião, pendência, marco — casam por título e rótulo
com `ILIKE` sobre a expressão dobrada. Os **trechos** de `document_chunk` casam por full-text,
com índice GIN funcional.

Sem os trechos, "buscar no contexto do projeto" entregaria uma lista de títulos: a versão do
controle que parece funcionar e não responde à pergunta que alguém realmente faz, que é onde
está a cláusula de rescisão. Com eles, a busca alcança o conteúdo pelo mesmo par de barreiras
que tudo o mais — o filtro do repositório e a RLS —, e o trecho volta com a página, que é
verdade pela razão de sempre: o chunk nunca cruza a virada de página (ADR 0014).

### 5. Só entra o que o cliente já alcança por alguma aba

`Decision` tem modelo, repositório e migração desde a Fase 1, e **não** é projetada em
`build_dashboard`: não existe aba de decisões. Um hit de decisão levaria a lugar nenhum — a
mesma classe de defeito que a ADR 0017 corrigiu ao transformar a citação num link, e que a
ADR 0016 evitou ao não deixar o cliente ver uma conexão de Drive que ele não administra.

A busca não é uma segunda porta para o read model: é um atalho para o que já está na tela. O
dia em que a aba de decisões existir, o teste que fixa esta decisão
(`test_a_decision_is_not_reachable_because_no_tab_shows_one`) é o que muda junto.

E o hit carrega o **rótulo da aba**, resolvido na API. A tela navega por rótulo desde a Fase 2;
um segundo mapa no navegador seria uma cópia que envelhece sozinha.

### 6. A varredura vale aqui também, e o título não some por causa dela

Um documento barrado pelo scanner continua achável **pelo título** — ele já está na aba
Documentos, e escondê-lo da busca seria a tela mentir sobre o que o projeto tem. O que não sai
é o **conteúdo**: sem `document_chunk` não há trecho, e o hit de título vem com `document_id`
vazio, de modo que não há URL assinada a pedir. É a regra de `document_download`, na mesma
forma e conferida duas vezes — o repositório já filtrou por tenant, e a varredura é um portão
separado do isolamento.

### 7. O termo digitado não vai para o log, e a busca não vira `audit_log`

`search.performed` leva `hits`, `kinds`, `term_length` e `duration_ms`. Nunca `q`: o termo é
conteúdo do cliente (`docs/data-classification.md`), e o comprimento já explica uma lista vazia
sem gravar o que a pessoa procurava.

Auditar foi recusado, não esquecido. O download é auditado porque **tira o arquivo do portal**;
procurar é ler o que a pessoa já vê nas abas, e uma linha de auditoria por tecla afogaria a
trilha que o `incident-response.md` manda ler — tornando o controle pior, não melhor.

### 8. Sem limite de taxa, com argumento

`chat_rate_window` existe porque cada turno do chat custa dinheiro num provedor (ADR
0021/0022). A busca é uma consulta ao Postgres com `LIMIT` e um índice. A defesa proporcional é
o debounce de 250 ms mais o teto de resultados — por espécie antes de geral, para um projeto
com duzentos documentos não esconder a única reunião que casou.

Pôr limitador onde não há recurso escasso é o que faz o limitador do chat parecer arbitrário, e
é assim que um controle deixa de ser levado a sério.

### 9. O estado da busca vive num componente que monta com o popover

`ProjectSearch` é componente próprio, e o motivo não é organização: ele desmonta quando a lupa
fecha, então fechar esquece o que foi digitado **sem efeito de limpeza nenhum**. O termo é a
pergunta de alguém; retê-lo entre aberturas seria guardá-lo sem que ninguém tenha pedido, pela
mesma razão pela qual ele não vai para o log.

O resultado é guardado junto do termo que o produziu (`{ query, hits }`), de modo que a lista de
um prefixo antigo nunca é exibida como se fosse do termo atual. E os quatro estados são quatro
frases diferentes de propósito — "comece a digitar", "buscando", "não consegui buscar" e "nada
encontrado para X" respondem a perguntas distintas, e uma frase só faria a tela mentir sobre
por que a lista está vazia.

## Consequências

- O critério de aceite da Fase 1 passa a ser atendido nas três camadas que ele nomeia. A prova é
  `test_a_term_only_the_other_project_uses_finds_nothing`, e o que a torna significativa é a
  segunda metade: o **dono** do outro projeto acha o mesmo termo pela mesma rota. Um vazio que
  ninguém consegue transformar em cheio não prova isolamento, prova bug.
- `test_the_database_refuses_even_when_the_app_filter_points_elsewhere` exercita a segunda
  barreira sozinha: contexto de tenant fixado num projeto, `TenantContext` forjado apontando
  para o outro, zero linhas. É o teste que continuaria vermelho se alguém trocasse os
  repositórios por SQL cru.
- **Um defeito de empilhamento apareceu ao clicar no primeiro resultado**, e ele é anterior a
  esta fatia: `.topbar` tem `backdrop-filter`, que cria contexto de empilhamento sozinho, então
  o `z-60` de qualquer popover do topo vale só **dentro** da barra — e quem disputa com o
  `.menu-backdrop` (`fixed z-40`, fora dela) é o z-index da barra, que é 20. Enquanto os
  popovers do topo eram só leitura ninguém notou; o primeiro conteúdo clicável dentro de um
  deles esbarrou nisso na hora, e o clique ia para o backdrop. A correção é
  `.topbar--menu-open`, que é o que `.sidebar--menu-open` já fazia do outro lado da tela — e
  ela conserta junto o "Ver todas" da caixa de avisos e o menu de perfil do topo, que estavam
  igualmente mortos.
- A fixture do teste de SSR ganhou `SEARCH`, e ela é validada contra o contrato publicado
  (`tests/api-contract.test.mjs`) como as outras três — a API de mentira continua sem liberdade
  para mentir (ADR 0020).
- A guarda de forma de `rendered-html.test.mjs` cresceu: um array de literais atribuído a
  `results`/`hits` no cliente reprova, pelo argumento que já valia para `sources` (ADR 0021).
  Toda lista de resultados vem da API, que é onde o tenant é conhecido.
- **O que continua faltando, declarado:** a busca é lexical e não semântica, então "quanto tempo
  temos para cancelar" não acha "cláusula de rescisão". Quem responde essa pergunta é o chat, e
  ele já responde; unificar as duas superfícies é uma decisão de produto que pede sua própria
  ADR, não um `if` a mais aqui. E a busca é de **um** projeto: quem tem mais de um troca pela
  URL, que é a decisão que a Fase 2 já tomou para o dashboard inteiro.

## Alternativas recusadas

**Busca semântica sobre os embeddings.** Cobraria da Voyage a cada tecla com chave configurada,
e sem chave devolveria ruído — o embedder offline é uma projeção por hashing, boa para casar
uma pergunta inteira com um trecho e péssima para um prefixo de duas letras. Além do custo, é a
recuperação do chat: a diferença entre as duas superfícies é que uma **responde** (com citação,
corte de distância e pendência na lacuna) e a outra **aponta**. Fundi-las por baixo faria a
busca herdar as garantias do chat sem herdar suas obrigações.

**`unaccent` ou `pg_trgm`.** Ver decisão 3: extensão é objeto de banco, e este repositório já
pagou uma vez, num restore, o preço de uma extensão que existia só na migração.

**Índice só na migração, sem declarar no modelo.** O `alembic check` proporia removê-lo a cada
`autogenerate` — o terceiro gate de deriva do repositório passaria a acusar deriva verdadeira
que ninguém deve corrigir, que é como um gate deixa de ser lido.

**Limite de taxa na busca.** Ver decisão 8.

**Auditar cada busca.** Ver decisão 7.

**Ler o termo no log "só em `debug`".** Um nível de log é configuração, e configuração muda em
incidente — exatamente quando mais gente está lendo o log. O termo não sai do processo, ponto.
