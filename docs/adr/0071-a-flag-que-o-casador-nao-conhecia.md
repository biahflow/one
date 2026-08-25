# ADR 0071 — A flag que o casador não conhecia

**Status:** aceito
**Data:** 20/08/2026
**Fase:** 7 — e a sétima ADR aceita neste dia, depois da 0061, da 0062, da 0063, da 0064, da 0065 e da 0066

## Contexto

A ADR 0063 pôs portão na pinagem de código de terceiro e escreveu a regra que o sustenta:
**cada superfície é fail-closed** — "glob vazio reprova, porque verde por não ter olhado é o
`dependency-review` da ADR 0033". Quatro superfícies entraram por glob, e uma quinta entrou
por casador próprio: as imagens que um `docker run` nomeia dentro de um `run:` de workflow,
que nenhum casador de `image:` alcança e que no `ci.yml` puxa o MinIO do job `backup-restore`.

Essa quinta cumpria a regra pela metade, e a própria ADR 0063 registrou o buraco:

> **E fica aberto o que a tabela de flags não cobre:** um `docker run` com flag de valor
> separado que o casador não conhece toma o valor dela por imagem em vez de reprovar. Foi
> medido e está no comentário do código: o fail-closed cobre o caso de *nenhum* token sobrar,
> não o de sobrar o token errado.

**O mecanismo era uma lista de dezesseis flags digitada à mão**, duplicada em dois arquivos
que precisavam ficar idênticos — `_DOCKER_VALUE_FLAGS` no portão em pytest e
`DOCKER_VALUE_FLAGS` no `scripts/pins.mjs`. O casador percorria os tokens depois do
subcomando: quem começa com `-` é flag; quem está na tabela consome **dois** tokens; o
primeiro token que sobra é a imagem.

É o defeito que as ADRs 0033 e 0035 catalogaram — **lista escrita à mão é o defeito** —
sobrevivendo dentro do portão mais novo do repositório, e o comentário de cada uma das duas o
declarava sem rodeios: "a única lista digitada à mão deste arquivo". A defesa escrita ali era
que a tabela "não envelhece com o repositório, envelhece com a forma da CLI do Docker". A
defesa é verdadeira e não salva: `docker run --help` lista dezenas de flags de valor separado,
e a tabela tinha dezesseis.

**O que acontecia.** Escrito `docker run --memory 512m minio/minio:…@sha256:…`, o casador não
achava `--memory` na tabela, tratava-a como booleana, consumia um token só, e tomava `512m`
por imagem. A imagem verdadeira nunca era conferida. O resultado é um vermelho que aponta para
o token errado — mandando o próximo leitor procurar defeito onde não há — ou, quando o token
errado casa a forma de pino ou uma chave de `PINNED_BY_EXCEPTION`, um verde sobre uma imagem
que ninguém olhou. Nos dois casos **a imagem real sai do corpus sem que nada diga isso**, que
é a forma exata do defeito que o portão existe para não repetir.

## Decisão

Matar a tabela nos dois arquivos e decidir pela **forma do token**.

O casador passa a percorrer os tokens assim: quem começa com `-` é flag e consome **um**
token, sem exceção e sem tabela; o primeiro token que não começa com `-` é o **candidato**; e
o candidato só vira imagem se tiver forma de referência de imagem. Se não tiver, a guarda
**reprova nomeando o token**, em vez de tomá-lo por imagem "provavelmente" — e não continua
procurando, porque continuar seria adivinhar qual dos tokens é a imagem, que é o defeito de
origem com outra roupa. O fail-closed que já existia (nenhum token sobrou depois do
subcomando) fica intacto ao lado do novo.

**A forma exigida** é nome com namespace opcional, tag opcional, digest opcional, mais a
exigência de conter `/` **ou** `@sha256:`. É essa exigência que separa uma referência de
imagem de um valor de flag: `9000:9000`, `512m` e `FOO=bar` casam "nome" ou "nome:tag" numa
sintaxe solta, e nenhum tem barra nem digest. É o mesmo movimento da ADR 0066 — trocar
julgamento por **gatilho estrutural** —, e ele vale aqui porque a pergunta "isto é uma
referência de imagem?" tem resposta na gramática do token, não numa lista de nomes.

**O que fica de fora de propósito:** uma imagem oficial de nome curto sem digest
(`postgres:17`) não passa nessa exigência. A saída legítima é o nome canônico
(`library/postgres:17`), e está escrita na mensagem de erro. Preferir isso a afrouxar a regra
é a mesma escolha que a ADR 0063 fez ao recusar `latest` mesmo com digest.

**A consequência na fonte, e ela é parte da decisão.** O único `docker run` do repositório
passa a escrever as flags na **forma colada**:

```yaml
docker run -d --name=minio --publish=9000:9000 \
  --env=MINIO_ROOT_USER=portal-minio \
  --env=MINIO_ROOT_PASSWORD=portal-minio-local-only \
  minio/minio:RELEASE.…@sha256:… server /data
```

Não é preferência de estilo: a forma colada é a que **não produz um token separado capaz de
ser confundido com a imagem**. A guarda passa a exigi-la por consequência da regra de forma, e
não por uma segunda regra escrita em cima dela — quem escrever `-e FOO=bar` recebe um vermelho
que nomeia `FOO=bar` e ensina `--env=FOO=bar`.

**As aspas saem antes da conferência, e não depois.** Isto veio da revisão do diff, e é o
único ponto em que a primeira implementação estava errada: ela conferia a forma com a aspa
ainda no token, de modo que um `docker run "minio/minio:…"` — forma legítima — reprovaria
**a imagem verdadeira**. Trocar um falso-verde por um falso-vermelho não é o negócio desta
fatia, e a medição abaixo traz as duas leituras.

## Medição

Toda mutação foi aplicada ao `ci.yml` real por um harness em Python (`re.sub` sem limite,
asserção de que o estado pretendido foi produzido, `subprocess` do pytest, restauração byte a
byte), e o portão rodou contra o repositório inteiro.

| Mutação | Esperado | Obtido |
| --- | --- | --- |
| baseline intacto | verde | verde |
| `--memory 512m` na forma separada | VERMELHA | VERMELHA |
| `-e FOO=bar` na forma separada | VERMELHA | VERMELHA |
| `--sysctl net.ipv4.ip_forward=1` | VERMELHA | VERMELHA |
| imagem trocada por `minio/minio:latest` | VERMELHA, **por pino** | VERMELHA, em `test_every_image_is_pinned_by_digest_with_its_tag` |
| `docker run --rm`, sem imagem | VERMELHA, **fail-closed de origem** | VERMELHA |
| `-d --rm -it --init` em fila | verde | verde |
| imagem entre aspas | verde | verde |
| `server /data` depois da imagem | verde | verde |
| `docker build` no mesmo arquivo | verde | verde |

O vermelho que dá nome à fatia, literal:

```
AssertionError: `512m` (linha 128) não tem forma de referência de imagem — nome com `/` ou
digest `@sha256:` — e por isso não é a imagem de `docker run|pull|create` em `docker run -d
--memory 512m --name=minio --publish=9000:9000 \` (linha 128): `-d --memory 512m
--name=minio --publish=9000:9000 …`. Provavelmente é o valor de uma flag escrita na forma
separada; escreva-a colada (`--memory=512m`, `--env=FOO=bar`, `--publish=9000:9000`) para
que o casador não tome o valor por imagem (ADR 0063).
```

**As mutações verdes provam mais que as vermelhas**, e duas delas são o motivo. A fila de
booleanas (`-d --rm -it --init`) é o que separa esta regra de uma versão ingênua: uma regra
que consumisse dois tokens por flag comeria `minio/minio`. E a imagem entre aspas é o
falso-vermelho que a revisão fechou — com a conferência feita **antes** de tirar a aspa, o
mesmo `ci.yml` reprovava assim:

```
AssertionError: `minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:14cea493…` (linha 131) não
tem forma de referência de imagem — nome com `/` ou digest `@sha256:` — e por isso não é a
imagem de `docker run|pull|create` …
```

Ou seja: a guarda acusando de "não ter forma de imagem" uma imagem corretamente pinada. Fica
registrado porque é o tipo de defeito que passa por revisão — o teste continua verde enquanto
ninguém escrever aspas — e porque a ADR 0064 já tinha estabelecido que a mensagem de uma
guarda é parte do produto: ela precisa dizer o que fazer **e** ser verdadeira sobre o token
que nomeia.

**Uma armadilha do harness, e não da guarda.** A mutação das aspas foi a única que reprovou a
asserção do próprio harness: envolver o token em aspas não faz o padrão buscado desaparecer do
arquivo, então "o padrão sobreviveu à mutação" disparou sobre uma mutação que estava correta.
É a terceira ocorrência da armadilha que as ADRs 0065 e 0066 registraram, agora pelo outro
lado — lá a mutação parecia guarda fraca, aqui a mutação correta pareceu mutação malformada.

`npm run pins` devolve as mesmas **41 referências, 40 pinadas e 1 isenta** de antes da fatia,
com a mesma referência do MinIO: a mudança de forma não mudou o que o inventário enxerga, que
é a prova de que o `ci.yml` reescrito continua dizendo a mesma coisa. A bateria da API roda
com `CI=1` em **659 passados, zero pulados**.

## Consequências

- **A última lista digitada à mão do portão de pinagem deixou de existir.** `grep -rn
  "VALUE_FLAGS"` volta vazio, e a regra que sobrou é computada sobre a gramática do token.
  As duas metades — o portão em pytest e o inventário do `pins.mjs` — continuam obrigadas a
  ler a mesma regra, pelo motivo que o comentário de lá já dizia: divergir faria o inventário
  e o portão discordarem sobre o mesmo comando.
- **O `ci.yml` passou a escrever flag colada**, e isso é agora uma consequência verificada da
  regra, não uma convenção que alguém precisa lembrar. Quem escrever a forma separada recebe
  vermelho com a saída legítima na mensagem.
- **Quatro casos novos no `tests/pins-harness.test.mjs`**, que é onde a regra é exercida sem
  build, sem rede e sem docker: a forma separada reprovando por `--name` e por `-e`, a fila de
  booleanas, a imagem entre aspas e o `--memory 512m` da ADR 0063. São 22 casos ali agora.
- **Fica aberto, e nomeado:** a regra decide pela forma do **primeiro** token não-flag, então
  uma flag de valor separado cujo valor *tenha forma de imagem* continua sendo tomada por
  imagem — `--platform linux/amd64` é o exemplo, porque `linux/amd64` tem barra. Nenhum
  comando deste repositório está nessa forma hoje, e fechá-lo exigiria de volta uma tabela de
  flags, isto é, o defeito que a fatia removeu. É a assimetria que a ADR 0064 declarou em (d)
  e a 0065 em (f): o portão cobre o que consegue computar e diz o que não cobre.
- **E fica aberto o que a ADR 0063 já tinha declarado e esta fatia não toca:** nada afirma que
  um pino é *recente*. Um digest de 2025 e um de ontem passam igual, e a detecção de
  vulnerabilidade em action e em imagem base — que a ADR 0062 declarou perdida ao desligar o
  Dependabot — continua sem nenhum mecanismo. Esta fatia conserta *quem o portão olha*, não
  *o que ele sabe sobre o que olhou*.

## O que esta fatia não é

O portal do cliente está fora do ar desde 13/08/2026 (ADR 0053). Isto fecha uma ponta de
código num portão de CI e deixa a guarda medida; nada aqui foi observado servindo cliente,
nenhum comportamento de produto mudou, nenhuma imagem ou action trocou de versão, e nenhum
defeito de dependência foi encontrado — o que a fatia entrega é o portão deixando de olhar
para o token errado.

*Retificado duas vezes em 25/08/2026, e a segunda vez é a que vale a pena registrar.*

*Esta ADR nasceu com o número **0067**, que `main` já usava para outra decisão
(`0067-one-como-projecao-client-facing.md`): a branch foi aberta antes de a outra existir e
mergeada depois. `test_roadmap_index.py` não via a colisão, porque `_adrs()` chaveia por número e
o arquivo que ordena depois sobrescrevia o outro em silêncio. Renumerada para **0070**, e a fatia
daquele conserto acrescentou a asserção que faz número duplicado reprovar.*

***E a asserção pegou esta mesma ADR, horas depois.*** *O `0070` foi verificado livre contra
`main` num commit que ainda não continha o PR #51 — que criou o seu próprio
`0070-o-rename-que-a-guarda-atravessou.md` e entrou primeiro. Duas branches, cada uma conferindo o
próximo número livre contra um `main` que envelheceu antes do merge: **é o mesmo modo de falha da
primeira colisão, um nível acima**, e desta vez ele nasceu vermelho no CI em vez de ficar invisível.
Renumerada para **0071**; quem chegou primeiro em `main` fica com o número, e a outra tem duas
citações contra uma desta. O texto da decisão não foi tocado nas duas vezes.*

*A lição não é sobre número: conferir "o próximo livre" contra um `main` que pode ter envelhecido entre
a verificação e o merge é uma corrida, e o que resolve corrida não é cuidado — é portão.*
