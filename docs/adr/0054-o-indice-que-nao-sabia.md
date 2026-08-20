# ADR 0054 — O índice que não sabia

**Status:** aceito
**Data:** 19/08/2026
**Relacionadas:** ADR 0029 (o que ninguém consome é pergunta para a API), ADR 0033 (a
guarda que parecia cobrir o contrato), ADR 0034 (o evento nomeado e o runbook que o
conhece), ADR 0035 (a guarda escrita à mão), ADR 0052 (a guarda nomeada e deixada sem
dono)

## Contexto

O `AGENTS.md` chama o `ROADMAP.md` de **índice canônico de descoberta de trabalho**, e o
próprio arquivo repete a frase na segunda seção. Entre 07 e 13/08/2026 a implantação na
nuvem foi construída inteira — dez ADRs aceitas, da 0044 à 0053 — e **o índice não soube de
nenhuma**. Nesse intervalo o produto saiu do ar por decisão de produto (ADR 0053), e o
arquivo que uma sessão lê para descobrir o que existe continuava descrevendo um portal
servindo cliente.

O conserto foi feito à mão em 19/08: uma seção nova, "Homologação na nuvem", e um item no
`AGENTS.md` mandando atualizar o roadmap no mesmo commit da fatia. É exatamente o estado em
que a ADR 0034 encontrou o `alerts.md` — a ADR 0028 tinha corrigido uma linha à mão e não
deixado portão, e **em dois dias o arquivo divergiu de novo pelo outro lado**. Um conserto
manual num arquivo que ninguém verifica é uma afirmação sobre o dia em que foi escrito.

Esta ADR é o portão. E, pela doutrina da ADR 0033, ele não pode ser uma lista digitada: o
corpus sai de `docs/adr/`.

## Os defeitos, todos medidos

Medidos com o predicado de `apps/api/tests/test_roadmap_index.py`, sobre o texto do arquivo
em memória — os auxiliares recebem `text: str` e nunca `Path`, o que permitiu medir contra
`git show HEAD:ROADMAP.md` sem tocar no working tree.

### 1. Catorze ADRs aceitas, e o índice não conhecia nenhuma

Contra o estado pré-conserto (`HEAD`), **14** das 53 ADRs aceitas não tinham citação:
1, 2, 3, 4, 5, 44, 45, 46, 47, 48, 50, 51, 52 e 53. Dez delas são a implantação; as outras
quatro são fundação, e a diferença entre os dois grupos é o que a allowlist abaixo registra.

Contra o roadmap já consertado à mão sobram **5** (1, 2, 3, 4, 5) — e a ADR 0003 sai da
lista pelo defeito 3, restando **4**, idênticas à allowlist.

### 2. O casamento frouxo nasceria verde

A primeira forma óbvia da guarda é procurar quatro dígitos no texto. Medida: com
`\b(\d{4})\b` no lugar das duas formas, as faltantes do disco caem de **4 para 1** — sobra
só a ADR 0001 —, e contra `HEAD` caem de **14 para 11**.

O que as come são os nomes de migração Alembic que o roadmap cita como token nu entre
crases: `` `0002` ``, `` `0004` `` e `` `0005` `` fazem as ADRs de mesmo número parecerem
citadas (contra `HEAD` são a `0003`, a `0004` e a `0005`). **Três das quatro** isenções
desta guarda desapareceriam sem que ninguém as tivesse decidido — é o `.priority` da ADR
0033 outra vez, e a razão de o prefixo `ADR`/`ADRs` ser obrigatório na forma em prosa.

Uma **faixa** (`ADRs 0044 a 0053`) também não casa, e isso é escolha: o que a regra do
`AGENTS.md` pede é linha por decisão, não um parágrafo dizendo que elas existem.

### 3. A ADR 0003 local parecia citada por um documento de outro repositório

As duas únicas ocorrências de "ADR 0003" no roadmap são `mais emenda na ADR 0003 de lá` e
``mais emenda na ADR 0003 do `biahflow-portal` `` — as duas apontando para o **outro**
repositório. A ADR 0003 daqui é *Identidade*, e não era citada em lugar nenhum.

Medido **contra `HEAD`**, e é ali que a cláusula se mede: no texto de hoje a ADR 0003 já é
citada de verdade, na Fase 1, e devolver uma menção *cross-repo* à forma nua não moveria
nada. Contra `HEAD` move — devolvendo `mais emenda na ADR 0003 de lá` à forma nua, as
faltantes caem de 14 para 13, e a ADR 0003 sai da lista **pelo motivo errado**. A cláusula segue
indispensável pela direção inversa, também medido: `ADR 0060 de lá` acrescentado ao texto não
pendura nada, e `ADR 0060` nu pendura `{60}` — cobrando deste repositório um arquivo que ele
não tem por que possuir. Daí a cláusula que descarta a citação seguida de "de lá" ou do nome
do outro repositório, aplicada por **posição no texto** e não sobre uma fatia de N
caracteres — o markdown quebra a linha no meio das duas (`ADR 0003 de\n      lá.`), e
qualquer versão que corte um número fixo de caracteres perde o caso.

A cláusula foi medida contra si mesma, e a primeira versão reprovou: a linha que esta fatia
escreveu no roadmap diz `ADR 0003 **do `biahflow-portal`**`, e aceitar só espaço entre o
número e o "do" fazia os asteriscos de ênfase quebrarem o casamento — a menção *cross-repo*
passava a contar como citação da ADR 0003 local, e a medição dava 5 onde ela é 6. O casador
engole marcadores de ênfase por isso, e não por precaução.

A correção honesta não foi uma isenção: o item "Integrar Keycloak ao BFF Next.js e à API
FastAPI com OIDC/PKCE" **é** aquela decisão, e passou a citar `ADRs 0003 e 0010`.

### 4. Ler o status como "aceito" encolheria o corpus em silêncio

`docs/adr/0021`, `0022` e `0023` **não têm linha `**Status:**`** — o cabeçalho delas é
`Data: 2026-08-05 · Fase 5 · FDD 015`. Um predicado `status == "aceito"` tiraria as três do
corpus sem dizer nada, e a guarda passaria a cobrir 50 ADRs afirmando cobrir 53. Seria a ADR
0033 cometida dentro da guarda que a cita.

Consertar aqueles três cabeçalhos ficou fora do recorte de propósito, e uma asserção "toda
ADR tem linha de status" nasceria vermelha com três ADRs por motivo alheio a esta guarda.

### 5. A primeira versão pagou em allowlist o que faltava no predicado

Esta guarda nasceu lendo **uma** forma de citação, a prosa `ADR 0009`, e isentando a ADR 0009
por uma linha de allowlist com motivo bem escrito. O motivo era **falso**: o roadmap conhece
aquela decisão, tem a seção "Concluído — Migração do runtime web (04/08/2026)" inteira sobre
ela e aponta para `docs/adr/0009` — e isso já era verdade em `HEAD`, não é linha desta fatia.
O arquivo faz o mesmo com a ADR 0008, em `Ver também `docs/adr/0008``.

`Ver `docs/adr/0009`` é citação, e **mais apertada** que a prosa: não há como um nome de
migração Alembic se disfarçar atrás de um caminho. Manter a isenção seria exatamente o que
esta ADR recusou para a ADR 0003 — allowlist onde bastava reconhecer a citação é sedimento
(ADR 0029) —, com o agravante de o cabeçalho da lista dizer "decisões que o roadmap não cita"
e a entrada refutá-lo em seguida.

Reconhecida a forma de caminho, a medida de `HEAD` cai de 15 para **14**, a do disco de 5
para **4**, e a asserção de obsolescência prova a morte da entrada sozinha: devolvendo o `9`
à lista, ela acusa *"ADR 0009: o roadmap passou a citá-la"*.

## Decisão

### 1. O corpus sai de `docs/adr/`, e a leitura do status é *fail-closed*

`_adrs()` lê **só a primeira palavra** depois de `**Status:**` — a data que vem depois
aparece em quatro formatos ao longo das 53 ADRs, e ler a palavra dispensa conhecê-los.
Ausência de linha devolve `""`, e `""` **conta como aceita**: só uma palavra do vocabulário
de recusa isenta uma ADR de precisar de linha no roadmap.

`_NOT_ACCEPTED` está **sem ocupante hoje** (rejeitada, revogada, substituída, obsoleta,
proposta) e existe para que a primeira ADR recusada não caia num `else` silencioso. Uma
palavra fora dos dois vocabulários reprova em
`test_every_adr_status_is_a_word_this_guard_knows`, em vez de virar "aceita" por omissão.

### 2. As duas direções, com um extrator só

`test_every_accepted_adr_has_a_line_in_the_roadmap` cobra a citação;
`test_every_adr_the_roadmap_cites_exists` cobra o inverso. As duas reusam
`_adrs_the_roadmap_knows` **inteiro** — e ele reconhece as **duas** formas, a prosa e o
caminho —, que é o que impede as duas direções de divergirem sobre o que conta como citação.

A inversa **nasce verde**, e pela ADR 0033 verde de nascença não prova nada — então foi
medida uma vez por forma: trocando `ADR 0053` por `ADR 0099` ela acusa `{99}`, e
acrescentando um ``Ver `docs/adr/0098` `` ela acusa `{98}`. A segunda é ganho da forma de
caminho: um link para ADR que não existe passa a reprovar, coisa que a versão em prosa não
alcançava. Existe pelo precedente da ADR 0034, onde as duas direções já falharam em
documentos diferentes: o runbook nomeava um evento que ninguém emitia, e doze eventos
emitidos não tinham runbook.

### 3. Sem `_HISTORICAL_NOTE`, ao contrário das guardas irmãs

`test_agents_rules.py` e a guarda de eventos ignoram as notas históricas, porque no
`alerts.md` a nota é **instrução que deixou de valer** e lê-la como instrução faria a guarda
cobrar o que o repositório corrigiu. Aqui o texto do roadmap é **conhecimento**: uma ADR
citada dentro de "*Fechados, para não serem reabertos por leitura de ADR:*" continua sendo o
índice sabendo dela, que é a única coisa que esta guarda pergunta.

### 4. Uma allowlist de quatro linhas, com motivo por linha e sem prazo

`FOUNDATION_WITHOUT_A_LINE` isenta 1, 2, 4 e 5. O motivo é escrito por decisão e é
**contestável de propósito** — quem discordar escreve a linha no roadmap, e a asserção de
obsolescência cobra a remoção da entrada:

- **1** (monorepo e stack) é a forma do repositório, dentro da qual toda fase existe;
- **2** (isolamento multitenant) é o *aceite* da Fase 1 e de todas as seguintes, não um
  trabalho que se conclui — quem tem linha é a ADR 0010, que o implementa por transação;
- **4** (RAG e contexto) é o princípio 3 do `AGENTS.md` na forma de arquitetura; quem tem
  linha é a ADR 0014, que construiu o índice, e a ADR 0038, que datou a citação;
- **5** (jobs) é anterior à ADR 0016, que trouxe o `beat`, e à ADR 0045, que decidiu onde o
  worker roda;
A quinta entrada que houve aqui — a ADR 0009 — foi apagada, e o defeito 5 conta por quê: o
roadmap a cita, e o que faltava era o predicado ler a forma de caminho. É a única entrada que
esta ADR removeu, e o caminho de saída dela é o que a asserção de obsolescência automatiza
para todas as outras.

**Sem `review_by`**, ao contrário de `docs/security/advisories.json` (ADR 0023): decisão de
fundação não caduca por prazo. O vencimento dela é
`test_the_roadmap_allowlist_does_not_keep_a_line_that_stopped_being_needed`, que reprova por
três caminhos — a ADR ganhou citação, foi recusada por escrito, ou o arquivo dela sumiu. Os
dois primeiros foram medidos em memória: com `33` na lista a asserção acusa "o roadmap passou
a citá-la", com `77` acusa "não há arquivo em `docs/adr/`" — e devolver o `9` à lista produz a
mesma acusação do `33`, que é a guarda demonstrando por si a remoção do defeito 5. O precedente é o `_CANNOT_ANSWER_404` do `test_authorization.py` e o `stale` do
`scripts/audit.mjs`.

### 5. O predicado é sobre **estado**, nunca sobre commit

A guarda não lê `git log` para exigir "no mesmo commit". Exigir isso reprovaria rebase,
squash e a própria correção retroativa que esta fatia é. O que ela afirma é que **hoje** o
índice conhece toda decisão aceita.

### 6. O `CLAUDE.md` fica declaradamente sem guarda

E o argumento é o mesmo que sustenta a existência desta: o índice canônico é o `ROADMAP.md`,
por escrito no `AGENTS.md`. O `CLAUDE.md` é orientação de trabalho, e cobrar dele toda ADR o
faria crescer sem limite — medido, ele hoje deixa de citar **15** ADRs aceitas (1, 2, 4, 5,
7, 30, 31, 32, 45, 46, 47, 48, 50, 51, 52), e essas ausências são deliberadas: ele narra o
mecanismo que sobreviveu, não a história de cada decisão. Duplicar a cobrança criaria dois
índices canônicos, que é o que a `workflows/feature.md` chama de anti-padrão ao proibir
`STATUS.md` como fonte independente de verdade.

O que o `CLAUDE.md` ganhou nesta fatia foi o que faltava e não era história: ele descrevia
**no presente** um produto que serve cliente, e é o arquivo que toda sessão carrega. Agora
diz que o portal está fora do ar desde 13/08/2026 por decisão de produto, que nada foi
revogado, e que a implantação existe como código nas ADRs 0044 a 0053.

## Consequências

- Uma fatia que aceita uma ADR e não escreve a linha no roadmap **reprova no CI**, no job
  `api-quality`. Sem banco: as quatro asserções são sobre arquivos.
- A allowlist é a única saída, e ela obriga a escrever por que aquela decisão não mudou
  estado publicado. Uma entrada que perde o motivo reprova sozinha — e a primeira a perdê-lo
  foi a que esta própria ADR escreveu, a da ADR 0009, morta pelo reconhecimento da forma de
  caminho antes de o arquivo ser commitado.
- Um `docs/adr/NNNN` escrito no roadmap passa a ter **duas** obrigações: conta como citação
  e tem de resolver para arquivo existente. Um link quebrado para ADR reprova, o que a
  versão em prosa não alcançava.
- A ADR 0003 local passou a ser citada, e as duas citações da ADR 0003 do `biahflow-portal`
  continuam sendo o que sempre foram — a cláusula que as distingue é a única parte do
  predicado que depende de como o texto nomeia o outro repositório. Uma terceira forma de
  dizer "de lá" passaria despercebida, e o custo disso é uma ADR local parecendo citada.
- **A guarda que a ADR 0052 nomeou foi medida como não construível neste repositório hoje.**
  Ela compararia variável declarada no compose com variável declarada no Terraform; o commit
  `9e2d61d` (13/08) apagou o `infra/terraform/ambientes/hml-portal/` inteiro, de modo que a
  comparação não tem lado direito — o `docker-compose.homolog.yml` continua descrevendo
  `api`, `worker`, `beat`, `web`, `keycloak` e `caddy` do portal, e nenhum `.tf` os declara
  (as ocorrências de `portal-api` e `keycloak` que restam em `infra/terraform/` são
  comentários de histórico). Escrita aqui hoje, ela nasceria **verde por vacuidade**, que é o
  defeito da ADR 0033. A ponta continua **aberta** no roadmap, agora com o motivo medido, e
  volta a ser possível quando o portal voltar — ou mora no repositório onde os dois lados
  coexistem.

## Alternativas recusadas

**Casar quatro dígitos em qualquer lugar do texto.** Simples e medido como falso verde: as
faltantes caem de 4 para 1 porque os tokens nus de migração comem as ADRs de mesmo número. É
o formato que a ADR 0033 combate, cometido dentro da guarda que a cita.

**Ler só a forma em prosa e isentar por allowlist quem o roadmap cita por caminho.** Foi a
primeira versão desta guarda, e o motivo escrito na entrada não a salvava: uma isenção que
descreve uma citação existente é sedimento, e a asserção de obsolescência nunca a mataria,
porque ela mede a forma que o predicado enxerga. Reconhecer a segunda forma custou uma
expressão regular e devolveu uma cobrança nova — link para ADR inexistente.

**Aceitar a faixa `ADRs 0044 a 0053` como citação de dez decisões.** Custa uma linha e
devolve exatamente o estado que esta ADR conserta: um parágrafo dizendo que as decisões
existem, sem que nenhuma delas tenha dono no índice.

**Ler `git log` e exigir a linha no mesmo commit da ADR.** É o que o `AGENTS.md` pede por
escrito, e um predicado sobre commit reprovaria rebase, squash e esta própria correção
retroativa. O predicado é sobre estado; a disciplina do commit continua sendo texto, com a
guarda cobrando o resultado dela.

**Estender o corpus a FDDs e RFCs.** Uma FDD é contrato detalhado e dona do próprio estado de
ciclo, e uma RFC preserva contexto sem afirmar implementação — cobrar linha no roadmap para
as duas confundiria três papéis que o `AGENTS.md` separa de propósito.

**Cobrar também o `CLAUDE.md`.** Criaria um segundo índice canônico e o faria crescer sem
limite, com quinze ausências deliberadas virando quinze linhas de allowlist que ninguém
consegue defender uma a uma.

**Isentar a ADR 0003 pela allowlist, já que "ADR 0003" aparece no arquivo.** Teria ficado
verde afirmando o que não é: aquelas duas menções são de outro repositório, e o item da Fase 1
sobre OIDC é exatamente a decisão de identidade. A citação verdadeira custou uma palavra.

**Consertar os cabeçalhos sem `**Status:**` de `0021`, `0022` e `0023` nesta fatia.** É
conserto de outro assunto, e o desenho *fail-closed* já as mantém no corpus — que é a
propriedade que importa aqui.
