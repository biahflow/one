# ADR 0063 — O pino que ninguém conferia

**Status:** aceito
**Data:** 20/08/2026
**Fase:** 7 — e a continuação direta da ADR 0062, aceita no mesmo dia

## Contexto

A ADR 0062 desligou o Dependabot e escreveu a perda com todas as letras, em vez de suavizá-la:

> **`github-actions` e `docker` ficam sem detecção e sem atualização.** […] as actions do `ci.yml`
> — que executam **com o token do workflow**, a única dependência que roda *dentro* do CI em vez
> de ser auditada por ele — e as duas imagens base […] congelam na CVE do dia em que foram
> escolhidas até alguém subir o pin à mão. Não é verdade que nada se perde.

E transferiu o conserto para uma pessoa, pelo runbook (`dependency-advisory.md:128-131`):

> E há duas coisas que ele **não** detecta, agora sem nada por trás: as actions do `ci.yml` e as
> duas imagens base do compose. […] as imagens estão **fixadas em versão exata** (ADR 0022) —
> congelam na CVE do dia em que foram escolhidas até alguém subir o pin. **Quem revisa dependência
> revisa essas duas listas junto, porque nada mais o fará.**

Esse parágrafo tem três defeitos, e eles são de naturezas diferentes.

**1. Não existe lista.** "Essas duas listas" não são duas listas: são 25 linhas `uses:` espalhadas
por três workflows e 16 referências de imagem espalhadas por dois Dockerfiles, dois composes, os
`services:` do próprio `ci.yml`, um `variables.tf` e um `docker run` escrito dentro de um `run:`.
Quem for revisá-las não tem o que abrir. É a forma do defeito que a ADR 0033 achou no
`dependency-review` e que a ADR 0035 achou nas guardas digitadas à mão: um mecanismo que descreve
o ponto cego em vez de fechá-lo.

**2. Nada verifica a instrução.** É instrução escrita para humano, e a ADR 0034 já mediu o que
acontece com essas: o `alerts.md` foi corrigido à mão e **divergiu de novo em dois dias**. Aqui
nem correção houve — a instrução nasceu sem portão.

**3. "Fixadas em versão exata" é falso.** `docker-compose.yml:78` era `minio/minio:latest`, tag
totalmente móvel; e `pgvector/pgvector:pg16`, `redis:7-alpine` e `python:3.13-slim` flutuam minor
ou patch. A frase descrevia um estado que o repositório não tinha.

**O inventário, medido antes de escrever qualquer linha de código:**

| Superfície | Referências | Pinadas |
|---|---|---|
| `uses:` em `.github/workflows/*.yml` | 25 | **0** |
| `FROM` em `Dockerfile` e `apps/api/Dockerfile` | 4 | **0** |
| `image:` em `docker-compose*.yml` | 8 | **0** |
| `image:` nos `services:` do `ci.yml` | 2 | **0** |
| `default` de `variable "imagem_*"` em `infra/terraform/` | 1 | **0** |
| `docker run` dentro de um `run:` do `ci.yml` | 1 | **0** |

As três actions do `deploy-hml.yml` e do `infra-hml.yml` são o caso mais caro da tabela e nenhum
documento as citava: aqueles dois workflows rodam com `id-token: write` e `packages: write`, isto
é, com credencial de nuvem e de registro. Uma tag `@v2` é um ponteiro que o publicador reescreve.

## Decisão

**Toda referência a código de terceiro que este repositório executa é pinada por identidade
imutável, e um portão derivado do próprio repositório reprova quem despinar.** Action por SHA de
40 hex com a versão legível ao lado (`# v4`); imagem por digest `@sha256:` com a tag ao lado
(`redis:7.4.6-alpine@sha256:…`).

**O corpus é derivado, nunca digitado.** É a regra que a ADR 0033 estabeleceu e a ADR 0035
generalizou: uma guarda cujo corpus é uma lista de nomes escritos à mão prova o que alguém lembrou
de digitar. Aqui as quatro superfícies entram por glob — `.github/workflows/*.yml`, `**/Dockerfile*`,
`docker-compose*.yml` e as `variable "…imagem…"` do Terraform —, e **glob vazio reprova**: uma
guarda que fica verde por não encontrar arquivo é exatamente o `dependency-review` que passou meses
verde sem olhar nada.

**A versão fica ao lado do digest, e isso é predicado e não convenção.** Um SHA sozinho é ruído
hexadecimal: quem for revisar a lista precisa saber que `actions/checkout` está na v4 e que o
Postgres é o `pg16`. Por isso `# vN` é cobrado, e por isso a tag `latest` reprova mesmo acompanhada
de digest — ela não diz versão nenhuma.

**O portão é um teste do pytest, e não um job novo no CI.** O precedente de job próprio
(`backup-restore`, `dependency-audit`) vale para quem precisa de toolchain, credencial ou rede;
isto é varredura de texto sobre arquivos versionados, sem banco e sem rede, e cabe no `api-quality`
que já roda a cada push. A forma é a do `test_roadmap_index.py`: auxiliares puros que recebem
`text: str` e não `Path`, o que é o que permite medir a guarda contra texto arbitrário — inclusive
contra `HEAD`.

**O custo está declarado, não contornado: digest congela.** Hoje `python:3.13-slim` recebe patch de
segurança em todo rebuild, e a partir daqui não recebe mais. Trocar patch automático por
reprodutibilidade só é defensável se o descongelamento for barato, e é isso que `scripts/pins.mjs`
existe para ser: sem flag ele **imprime a lista** que o runbook manda revisar e que não existia;
com `--update` ele resolve os SHAs pela API do GitHub e os digests pelo registro e reescreve os
pins. Não é o robô que a ADR 0062 desligou — aquele abria vinte PRs por semana e treinava a equipe
a fechá-los sem ler. Este é um comando que uma pessoa roda de propósito, e o portão é quem lembra
que ela existe.

**A isenção é uma linha com motivo, sem prazo.** `PINNED_BY_EXCEPTION` segue o
`FOUNDATION_WITHOUT_A_LINE` do `test_roadmap_index.py` e não o `advisories.json`: isenção de pin
não caduca por data — o vencimento dela é a asserção de obsolescência, que reprova a entrada que
deixou de ser necessária. Nasce com uma entrada só, o placeholder do Cloud Run
(`us-docker.pkg.dev/cloudrun/container/hello`), publicado apenas em `latest` e substituído no
primeiro deploy.

## Medição

**A guarda nasceu vermelha, contra a árvore ainda não pinada**, com dois dos quatro predicados
acusando — 25 actions e 15 imagens, uma linha por referência:

```
E  AssertionError: estas actions estão em tag ou branch, e não em SHA de commit:
   .github/workflows/ci.yml:19 → actions/checkout@v4;
   .github/workflows/ci.yml:20 → actions/setup-node@v4; […]
   .github/workflows/deploy-hml.yml:49 → google-github-actions/auth@v2; […]
E  assert [...] == []
E    Left contains 25 more items

E  AssertionError: estas imagens não estão fixadas por digest com a tag ao lado:
   .github/workflows/ci.yml:33 → pgvector/pgvector:pg16;
   .github/workflows/ci.yml:131 → minio/minio:latest;
   docker-compose.yml:78 → minio/minio:latest; […]
   apps/api/Dockerfile:13 → python:3.13-slim.
E  assert [...] == []
E    Left contains 15 more items

2 failed, 2 passed in 0.31s
```

*(A saída acima é a da guarda **desta** fatia rodada contra `HEAD` numa cópia da árvore
pré-pinagem — não a do primeiro rascunho dela. As reticências marcam elisão de linhas do mesmo
formato; os totais, 25 e 15, são os que o pytest imprime.)*

**Um dos quatro predicados nasceu verde, e o motivo é da forma dele, não frouxidão.** "Todo pino
diz de que versão é" só pergunta de pinos, e antes da fatia não havia nenhum — 25 tags, e uma tag
já diz a versão. Ele existe para o depois, e por isso a cobertura dele veio de mutação. É a ADR
0038 outra vez: *a cobertura de um portão é a dos ramos que a amostra percorre*.

**As mutações, uma por predicado, todas revertidas em seguida:**

| Mutação | Resultado |
|---|---|
| `deploy-hml.yml:47` volta a `actions/checkout@v4` | reprova, nomeando a linha |
| apaga o ` # v4` daquele mesmo pino | reprova: *"estes pinos de action não dizem de que versão são"* |
| `redis` fica só com a tag | reprova: *"não estão fixadas por digest com a tag ao lado"* |
| SHA do `setup-terraform` encurtado para 39 hex | reprova pelo predicado 1 |
| `WORKFLOW_DIR` aponta para diretório vazio | **os quatro** reprovam, pelo fail-closed |
| allowlist ganha uma referência que já está pinada | reprova: *"já está corretamente pinada"* |
| chave da isenção trocada por um nome inexistente | reprova: *"não aparece em superfície nenhuma"* |
| *contraprova:* imagem despinada **e** na allowlist | **verde** — a isenção legítima passa |
| superfície nova: um `docker-compose.rascunho.yml` com `alpine:3.21` | reprova **sem editar a guarda** |

**E a revisão achou o que o levantamento não tinha achado**, que é a parte desta fatia que quase
não existiu. O `ci.yml` sobe o MinIO do job `backup-restore` com um `docker run` dentro de um
`run:`, porque um `services:` não aceita comando e aquela imagem precisa de `server /data`:

```yaml
docker run -d --name minio -p 9000:9000 \
  … minio/minio:latest server /data
```

É a imagem que o CI **de fato puxa**, no job que existe para provar que o backup funciona, na
mesma tag móvel que a fatia acabara de pinar no compose — e nenhum casador de `image:` a alcança.
Sem fechar isso, o repositório passaria a afirmar "toda imagem pinada" com o CI puxando `latest`,
e com o CI e a máquina de quem desenvolve subindo **versões diferentes** de MinIO. O casador novo
lê o comando através da continuação de linha, pula flag e valor de flag, e **reprova quando não
consegue identificar a imagem** em vez de concluir que não há nenhuma — o `skipped` não é `clean`
do `scanner.py`, aplicado a um parser. A tabela de flags que ele usa é a única lista digitada do
arquivo, e é detalhe de parser e não corpus: ela envelhece com a CLI do Docker, não com o
repositório.

**Inventário final:** 41 referências, 40 pinadas, 1 isenta por escrito.

**E o atualizador foi medido pelo avesso, que é a única prova que interessa nele:** numa cópia da
árvore, despinar uma action (`infra-hml.yml`) e uma imagem (`docker-compose.yml`) e rodar
`--update` devolveu os dois arquivos **byte a byte idênticos** aos originais — ele reconstrói o
pino sem tocar em comentário, indentação ou qualquer outra linha. Rodado sobre a árvore já pinada,
resolve zero e reescreve zero: é idempotente, e anuncia a referência isenta como *"escolha
necessária"* em vez de pinar `latest` por conta própria.

**Portões, todos verdes:** 647 testes de API (**0 pulados**, sem `test_backup_restore.py`, com
Postgres e MinIO de pé), `npm test` 139/139 (inclui o harness novo do `pins.mjs`), `npm run lint`
0 erros (os 4 avisos são de `coverage_html.js`, dentro do `.venv`, e são anteriores a esta fatia),
`npm run audit` limpo, `docker compose config --quiet` no arquivo base e no override de
homologação, `terraform fmt -check -recursive` sem deriva, e `node scripts/pins.mjs` fechando em
41 referências, 40 pinadas, 1 isenta.

**E a pilha foi construída e subida com os pinos**, que é a única prova de que um digest não
quebrou nada: `docker compose build web api` verde a partir dos `FROM` por digest, e os dez
serviços de pé e saudáveis — API (`/health` 200, `/docs` 200), web (`/login` 200), Keycloak
(descoberta OIDC do realm 200), MinIO na versão nova (`/minio/health/live` 200 e console 200),
Mailpit, Redis, Postgres, worker, beat e o drive-stub. Nenhum digest de plataforma escapou: a
máquina que rodou isto é arm64 e o CI é amd64.

## Consequências

- **Digest congela, e isso é o preço, não um efeito colateral.** `python:3.13.15-slim` recebia
  patch de segurança a cada rebuild e não recebe mais. Nenhum dos dois portões vê CVE de imagem
  base — o `dependency-audit` não conhece imagem, e este só pergunta se há pino, nunca se o pino
  é recente. O que torna a troca defensável é o descongelamento ser barato: `npm run pins --
  --update` resolve tudo de uma vez, e `npm run pins` sozinho imprime a lista que o
  `dependency-advisory.md` mandava revisar e que não existia. Não é o robô que a ADR 0062
  desligou — aquele abria vinte PRs por semana e treinava a equipe a fechá-los sem ler; este é um
  comando que uma pessoa roda de propósito.
- **O CI e a máquina de quem desenvolve passaram a subir o mesmo MinIO.** A versão foi escolhida à
  mão (`RELEASE.2025-09-07T16-13-09Z`) porque `latest` não tem versão para pôr ao lado do digest,
  e o console em `:9001` foi conferido em contêiner de verdade — health 200, login 204,
  `/api/v1/buckets` respondendo —, já que as notas de uma versão de 05/2025 anunciam a saída do
  console embutido e o `passeio-local.md` usa aquela porta.
- **O `--update` resolve, mas não escolhe.** Referência sem tag ou em `latest` ele anuncia e deixa
  em paz: pinar `minio/minio:latest@sha256:…` produziria um pino que o portão continua reprovando
  com razão, e escolher versão por conta própria é decisão de produto disfarçada de ferramenta.
- **A isenção não tem prazo, e é a primeira allowlist do repositório que nasce com uma linha.** O
  placeholder do Cloud Run é publicado só em `latest`; o motivo está escrito e é contestável, e
  quem discordar pina a referência — aí a asserção de obsolescência cobra a remoção da linha. Sem
  `review_by`, ao contrário do `advisories.json` (ADR 0023): pino não caduca por calendário.
- **O `dependency-review` continua desligado e isto não o substitui.** Aquele job olha o *diff* de
  dependências de um PR e está desligado por variável desde 17/08 porque o repositório é privado
  sem Advanced Security. São três mecanismos com perguntas distintas, e agora dois de pé.
- **Fica aberto, e nomeado:** nada afirma que um pino é *recente*. Um digest de 2025 e um de
  ontem passam igual, e nenhum portão deste repositório sabe a diferença — a única defesa é
  alguém rodar `npm run pins` ao revisar dependência, que é o que o runbook agora manda fazer com
  um comando em vez de com uma instrução. Uma guarda de idade exigiria consultar o registro no
  CI, isto é, rede num teste que hoje não tem nenhuma, e ficou de fora por isso.
- **E fica aberto o que a tabela de flags não cobre:** um `docker run` com flag de valor separado
  que o casador não conhece toma o valor dela por imagem em vez de reprovar. Foi medido e está no
  comentário do código: o fail-closed cobre o caso de *nenhum* token sobrar, não o de sobrar o
  token errado. Hoje há um `docker run` no repositório inteiro.
