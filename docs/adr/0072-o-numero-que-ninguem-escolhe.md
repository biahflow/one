# ADR 0072 — O número que ninguém escolhe

**Status:** aceito
**Data:** 25/08/2026
**Fase:** 7 — e a quarta ADR aceita neste dia, depois da 0069, da 0070 e da 0071
**Completa:** ADR 0054

## Contexto

O número de uma ADR era escolhido quando a branch nascia: alguém olhava `docs/adr/`, via
que o maior era `0066` e escrevia `0067` no nome do arquivo. E era **reivindicado** só no
merge, quando aquele arquivo finalmente entrava em `main`. Entre os dois momentos existe uma
janela — horas, dias — em que o número parece livre para todo mundo que olhar. Quem olha,
escolhe o mesmo.

Isto não é descuido de ninguém: **é uma corrida**, na acepção literal. O estado consultado
(`docs/adr/` em `main`) não é o estado no qual a escrita vai acontecer (`main` no momento do
merge), e nada entre a leitura e a escrita impede que outro escritor passe. É a forma exata
do defeito que o `chat_limit.py` documenta sobre contadores — "um contador subconta sob
concorrência" — com um agravante: aqui o intervalo entre ler e escrever não é uma transação
de milissegundos, é o tempo de vida de um pull request.

**Aconteceu três vezes em 25/08/2026**, e as três estão registradas no repositório:

1. **`0067`.** `0067-one-como-projecao-client-facing.md` e a ADR que hoje é a `0071`
   conviveram no mesmo `main` com o mesmo número **sem nada reprovar**. `_adrs()`, em
   `test_roadmap_index.py`, chaveia o corpus por número: o arquivo que ordena depois
   sobrescreve o outro dentro do dicionário, e a guarda de índice passava verde por cima da
   colisão. Uma decisão apagava a outra em silêncio.
2. **`0070`.** A fatia que consertou (1) acrescentou
   `test_no_two_adr_files_share_the_same_number`, e a asserção **pegou a própria fatia que a
   introduziu**, horas depois: o número tinha sido conferido livre contra uma `main` que
   ainda não continha o PR #51, mergeado minutos antes. A retificação daquela ADR diz a
   frase que dá nome a esta: *"o número livre de dez minutos atrás não é o número livre de
   agora"*.
3. Duas branches consertando (2) **ao mesmo tempo**, sem se ver — que é (1) outra vez, agora
   sobre o conserto.

**E o que a segunda manifestação prova é que detecção não fecha corrida.** A guarda da
manifestação (1) está certa e continua necessária, mas ela só pode falar depois que as duas
ADRs estão no mesmo commit — isto é, depois do merge, quando o custo já é renomear arquivo,
cabeçalho e toda citação, às vezes atravessando outro repositório (foi por isso que a ADR
0070 não pôde ser a renumerada). Um portão que detecta é um portão que chega tarde por
construção. O que falta não é enxergar melhor: é ter um **ponto de coordenação**.

## Decisão

**(a) O número é alocado num ledger que força conflito de merge.** `docs/adr/number-registry.tsv`
tem uma linha por ADR, `NNNN<TAB>slug`, ordenada, e toda ADR nova acrescenta a sua **no fim**.
Duas branches concorrentes escrevem na mesma posição do mesmo arquivo, e o git recusa
mesclá-las: o conflito **é** a coordenação. É o mecanismo do `db/schema.rb` do Rails e do
`max_migration.txt` do django-linear-migrations, e a razão de ele existir naqueles dois
projetos é a mesma daqui — número sequencial escolhido antes do merge.

**(b) O formato é texto puro, uma entrada por linha, de propósito.** JSON tem vírgulas e
colchetes que dão ao git material para auto-mesclar dois appends: a chave nova de uma branch
e a da outra podem entrar as duas sem conflito nenhum. O objetivo aqui é o **oposto** de
auto-mesclar, e por isso o arquivo é a estrutura mais burra possível — nenhum delimitador
que sobreviva à mesclagem, nenhuma sintaxe que o git saiba costurar.

**(c) A ordenação é parte do mecanismo, e não estética.** Uma linha escrita no **meio** do
arquivo devolve ao git a chance de mesclar dois appends sem conflito — as duas alterações
deixam de tocar a mesma região. Por isso "está ordenado" é asserção de guarda, e não
convenção: quem escreve no meio desarma a coordenação sem que nada mais fique vermelho.

**(d) O registro não é um índice de decisões.** O índice canônico de descoberta continua
sendo o `ROADMAP.md`, e a linha de lá continua sendo obrigatória e escrita por uma pessoa
(ADR 0054). O registro responde uma pergunta só — *quem reivindicou este número* —, e o
cabeçalho comentado do arquivo diz isso, para que ninguém o transforme no segundo lugar onde
o estado do projeto mora.

**(e) Quem escreve a linha é `npm run adr`.** Em `scripts/` pelo precedente do `audit.mjs` e
do `pins.mjs`: é operação. Ele lê o registro, calcula o próximo número a partir do maior
reivindicado **dos dois lados** (registro e diretório, unidos — na dúvida o número seguinte,
nunca o buraco), deriva o slug do título em kebab-case sem acento, escreve o esqueleto de
cabeçalho da casa e acrescenta a linha. As duas escritas saem do mesmo comando porque
separá-las reintroduz o defeito: um arquivo sem linha é um número que ninguém reivindicou.
Sem dependência nova, Node puro, como os outros dois.

**(f) A guarda é bidirecional, e fail-closed.** Todo arquivo de ADR tem exatamente uma linha
e toda linha tem arquivo, com o slug batendo nos dois lados; o registro está ordenado e não
repete número; e registro ausente, registro vazio ou diretório de ADR vazio **reprovam**. As
duas direções porque as duas já falharam neste repositório — é o argumento da ADR 0034 sobre
o `alerts.md` —, e o fail-closed porque verde por não ter conseguido olhar é o
`dependency-review` da ADR 0023. `test_no_two_adr_files_share_the_same_number` **fica onde
está**: ela é o backstop, e a mensagem dela é o que ensina a renumerar.

**(g) E uma asserção defende o mecanismo de ser desligado em silêncio.** Não existe
`.gitattributes` neste repositório. Se alguém criar um com `merge=union` para o registro, o
git passa a mesclar os dois appends sem dizer nada: as duas linhas entram, as duas ADRs
ficam com o mesmo número, e o arquivo continua **parecendo íntegro**. A guarda afirma que
nenhum `.gitattributes` declara driver de merge para o registro — nem `merge=<driver>`, nem
`-merge`, nem o macro `binary`, que o próprio git expande para `-diff -merge -text`.

**Nenhum, e não o da raiz.** O git lê `.gitattributes` de **qualquer** diretório e o aplica
dali para baixo, com o padrão resolvido em relação ao diretório do arquivo. A primeira versão
desta guarda olhava um caminho só, `REPO_ROOT / ".gitattributes"`, e a revisão mediu o buraco:
um `docs/adr/.gitattributes` de quatro palavras desarmava o mecanismo com as nove asserções
verdes — no diretório mais óbvio para quem fosse desarmá-lo. Perguntar por um arquivo só é
perguntar por um arquivo que não é o que decide. Desligar a coordenação continua possível;
passa a exigir apagar a asserção junto, que é uma linha de diff que uma pessoa lê.

## Medição

**O mecanismo, antes da guarda.** Repositório de teste, um `reg.tsv` com duas linhas, três
branches saindo do mesmo commit base e cada uma acrescentando uma linha ao fim:

| Caso | Esperado | Obtido |
| --- | --- | --- |
| duas branches, **mesmo** número (`0003`/`0003`) | conflito | `CONFLICT (content): Merge conflict in reg.tsv`, saída 1 |
| duas branches, números **diferentes** (`0003`/`0004`) | conflito | `CONFLICT (content): Merge conflict in reg.tsv`, saída 1 |
| o mesmo, com `.gitattributes` dizendo `reg.tsv merge=union` | sem conflito | `Merge made by the 'ort' strategy`, saída 0 |

**O segundo caso é o preço, e está aceito.** Duas ADRs simultâneas conflitam mesmo quando os
números não colidem, porque o git não sabe que são linhas independentes — ele sabe que são a
mesma região do arquivo. A resolução é trivial (ficar com as duas linhas, na ordem) e o
custo é pago por quem abre a segunda ADR do dia, que é raro; o que se compra em troca é a
impossibilidade de as duas entrarem sem ninguém olhar.

**O terceiro é a razão de (g) existir.** Com `merge=union` o merge passa liso e o arquivo
final fica com `0003 slug-p` e `0003 slug-q` — duas linhas, um número, nenhum conflito,
nenhuma mensagem. A solução inteira evapora numa linha de configuração de quatro palavras.

**A guarda, medida por mutação** (harness em Python, `re.sub`, asserção de que o estado
pretendido foi produzido, `subprocess` do pytest, restauração byte a byte — ADR 0065):

| Mutação | Esperado | Obtido |
| --- | --- | --- |
| baseline intacto | verde | verde |
| linha do registro apagada, arquivo presente | VERMELHA | VERMELHA, em `test_every_adr_file_has_a_line_in_the_number_registry` |
| linha no registro sem arquivo (`0099`) | VERMELHA | VERMELHA, em `test_every_line_in_the_number_registry_has_an_adr_file` |
| slug do registro divergindo do arquivo | VERMELHA | VERMELHA, em `test_every_adr_file_has_a_line_in_the_number_registry` |
| duas linhas trocadas de lugar (fora de ordem) | VERMELHA | VERMELHA, em `test_the_adr_number_registry_is_ordered_and_claims_each_number_once` |
| registro esvaziado | VERMELHA, **fail-closed** | VERMELHA, nas três asserções que dependem do corpus |
| `.gitattributes` **na raiz** com `merge=union` para o registro | VERMELHA | VERMELHA, em `test_the_number_registry_is_not_disarmed_by_a_merge_driver` |
| `docs/adr/.gitattributes` com `number-registry.tsv merge=union` | VERMELHA | VERMELHA, na mesma asserção, nomeando `docs/adr/.gitattributes:1` |
| tudo revertido | verde | verde |

O vermelho que dá nome à fatia, literal:

```
AssertionError: estes arquivos de ADR não têm linha no registro de números:
0071-a-flag-que-o-casador-nao-conhecia.md. A linha é escrita por `npm run adr` no mesmo
commit do arquivo — sem ela o número não foi reivindicado em lugar nenhum, e a próxima
branch o toma sem que nada conflite (ADR 0072).
```

**As duas mutações de (g) foram conferidas contra o próprio git**, e é o que prova que a
guarda pergunta o que o git responde: em cada uma,
`git check-attr merge -- docs/adr/number-registry.tsv` respondeu `merge: union`, e no estado
final respondeu `merge: unspecified`. Antes do conserto, a mutação em `docs/adr/` era um
**falso verde medido** — `9 passed` com o `check-attr` já dizendo `union`.

E o de (g), que é a asserção sobre a própria defesa do mecanismo:

```
AssertionError: o `.gitattributes` declara mesclagem para o registro de números:
.gitattributes:2: `docs/adr/number-registry.tsv merge=union`. O conflito em
`docs/adr/number-registry.tsv` **é** o mecanismo (ADR 0072) — um driver de merge ali faz
duas branches receberem o mesmo número com o arquivo parecendo íntegro. Apague o atributo;
se a intenção é mesmo desligar a coordenação, isso é decisão de ADR, não de linha de
configuração.
```

**O bootstrap foi derivado, não digitado**: as 71 linhas iniciais saíram de um glob sobre
`docs/adr/`, e a sequência não tem buraco — 0001 a 0071, sem número ausente. Uma lista
escrita à mão aqui seria o defeito que as ADRs 0033, 0035 e 0071 catalogaram, dentro do
arquivo cuja função é ser confiável.

**E esta ADR é a primeira prova da ferramenta**: o arquivo que você está lendo foi criado por
`npm run adr -- "O número que ninguém escolhe"`, que alocou o `0072`, escreveu o esqueleto e
acrescentou a linha `0072<TAB>o-numero-que-ninguem-escolhe` ao fim do registro.

## Consequências

- **O número deixa de ser escolhido e passa a ser alocado.** Quem abre uma ADR não olha
  `docs/adr/` nem decide nada: roda o comando. A colisão, quando duas fatias andam juntas,
  chega como conflito de merge — no momento em que o custo de resolvê-la é uma linha, e não
  como renomeação atravessando citações de outro repositório.
- **A resolução do conflito é sempre a mesma, e é trivial:** fique com as duas linhas, em
  ordem, e renumere o arquivo da ADR que perdeu a corrida (`git mv` mais a linha 1). É o
  mesmo procedimento que a mensagem de
  `test_no_two_adr_files_share_the_same_number` já ensinava — a diferença é que agora ele
  acontece **antes** de as duas decisões coexistirem em `main`.
- **Duas ADRs simultâneas conflitam mesmo com números diferentes.** Medido, declarado e
  aceito: é o preço do mecanismo, e evitá-lo exigiria um formato que o git saiba mesclar,
  isto é, exatamente o que se quer impedir.
- **O registro é mais um gate de deriva**, ao lado do `alembic check`, do `openapi.json` e
  do `prompt-registry.json`. Diferente do `advisories.json` (ADR 0023), ele **não** tem
  entrada que expira, e diferente do `prompt-registry.json` ele não é append-only por
  digest: a linha some se o arquivo da ADR sumir, porque a guarda bidirecional cobra as duas
  direções.
- **O casador de `.gitattributes` ganhou teste próprio, puro.**
  `test_the_merge_driver_matcher_reads_a_pattern_the_way_git_does` fixa as duas metades em
  casos escritos — o **diretório** (o mesmo texto alcança ou não o registro conforme onde
  mora) e o **padrão** (sem barra casa pelo nome em qualquer profundidade, com barra é
  ancorado) —, na forma do `_TEMPLATE_SAMPLE` do registro de prompts: a cobertura de um
  portão é a dos ramos que a amostra percorre, e a amostra é parte do portão.
- **Fica aberto, e foi achado ao escrever isto:** os bullets de "mexeu em X, Y vem junto" do
  `AGENTS.md` e do `CLAUDE.md` são gêmeos por convenção e **nada cobra que sejam os mesmos**.
  A guarda da ADR 0035 compara as duas listas de *princípios*, não as de checklist de PR — de
  modo que uma regra escrita num arquivo e esquecida no outro deixa a instrução errada de pé
  no lugar de maior alcance, que é justamente o arquivo que um agente lê antes de mexer no
  repositório. Esta fatia escreveu a linha nos dois; o portão continua não existindo.
- **Fica aberto, e nomeado:** o mecanismo protege o **número**, não o **slug**. Duas ADRs com
  o mesmo título produziriam a mesma linha e o mesmo arquivo — o `wx` do `writeFile` recusa
  sobrescrever, e é só isso; não há asserção de slug único, porque não há defeito medido
  ali. E nada aqui alcança quem escrever o arquivo à mão sem rodar o comando: o que existe
  contra isso é a guarda bidirecional, que reprova no `api-quality` do mesmo PR.
- **O RFC e a FDD continuam com número escolhido à mão.** A corrida é a mesma e o mecanismo
  serviria igual, mas os três defeitos medidos são de ADR, e generalizar sem defeito medido é
  o que a ADR 0029 chama de sedimento. Quando morder, o registro é o mesmo formato com outro
  nome de arquivo.

## O que esta fatia não é

O portal do cliente está fora do ar desde 13/08/2026 (ADR 0053). Isto é processo de
repositório: nenhum comportamento de produto mudou, nenhuma rota, nenhuma migração, nenhum
byte servido a cliente. E não é uma reescrita da numeração existente — as 71 ADRs anteriores
entram no registro exatamente com o número que já têm, e nenhum arquivo foi renomeado por
esta fatia.
