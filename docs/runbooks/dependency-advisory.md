# Runbook — caiu um aviso de segurança numa dependência

O portão é `scripts/audit.mjs` (ADR 0023), rodando no job `dependency-audit` do CI a cada push
e a cada pull request. Ele audita os **dois** ecossistemas — `npm audit` para o web,
`pip-audit` para a API — e reprova em qualquer aviso, sem limiar de severidade.

Reproduza local com o mesmo comando que o CI usa:

```bash
npm run audit          # node scripts/audit.mjs
```

Precisa do `pip-audit` no `PATH`; ele vem em `apps/api/requirements-dev.txt`.

## Sintoma: o job `dependency-audit` ficou vermelho

A saída nomeia o aviso, o pacote e onde ele fecha:

```
REPROVA [pip] python-multipart: PYSEC-2026-1852 → corrigido em 0.0.22
      Path Traversal com UPLOAD_DIR e UPLOAD_KEEP_FILENAME=True.
      sem entrada em advisories.json
```

Três causas possíveis, e a terceira é a que engana.

### 1. Um aviso novo foi publicado

O caso comum, e a razão de o portão rodar em `push`: um aviso não chega por pull request, chega
porque alguém o publicou. Vá para *Conserto*.

### 2. Uma exceção venceu

```
REPROVA [npm] alguma-lib: GHSA-…
      exceção venceu em 2026-06-30 — reavalie ou conserte
```

A linha em `docs/security/advisories.json` fez o que devia. **Não** empurre a data para frente
por reflexo: reabra a pergunta que a `reason` responde e verifique se ela ainda é verdade. Se
já houver correção disponível, o certo é a correção; a prorrogação é para quando não houver.

### 3. Uma entrada ficou obsoleta

```
REPROVA entrada obsoleta em docs/security/advisories.json: GHSA-… (next)
      nenhum aviso corresponde a ela.
```

Ou o aviso foi corrigido — e a linha deve **sair** —, ou o `id`/`package` foram escritos
errado. O segundo caso é o que engana: a exceção nunca valeu para o aviso que alguém achou
estar aceitando, e o arquivo dizia uma coisa enquanto o portão fazia outra. Um `id` certo com
`package` errado reprova dos dois lados de propósito, para o engano ficar visível.

## Conserto

**Primeiro caminho, sempre: subir a dependência.**

```bash
# web
npm install <pacote>@<versão>          # nunca `npm audit fix --force`
npm run lint && npm test

# API
$EDITOR apps/api/requirements.txt
pip install -r apps/api/requirements-dev.txt
PYTHONPATH=apps/api/src pytest apps/api/tests
```

Duas coisas que a ADR 0023 mediu e que economizam uma tarde:

- **A versão que o aviso nomeia pode não bastar.** O aviso do `next` dizia "corrigido em
  16.2.11", e a linha 16.2.x repinava `postcss` e `sharp` nas versões vulneráveis: só a 16.3.0
  fechava as três. Rode `npm run audit` de novo antes de acreditar que acabou.
- **Aviso em transitiva do FastAPI se conserta subindo o FastAPI.** Ele fixa a faixa do
  `starlette`; tentar subir o `starlette` sozinho por baixo de uma faixa que o proíbe não
  resolve. E cuidado com o inverso: como a faixa nova é `>=` sem teto, um ambiente que já tenha
  a versão vulnerável **continua nela**. Confira o que ficou instalado:

  ```bash
  pip show starlette | head -2
  ```

**Se o bump não existir ou não couber agora**, escreva a exceção — e só então:

```jsonc
// docs/security/advisories.json
{ "accepted": [
  {
    "id": "PYSEC-2026-1852",
    "package": "python-multipart",
    "reason": "Só afeta UPLOAD_DIR + UPLOAD_KEEP_FILENAME=True; o portal usa nenhum dos dois.",
    "review_by": "2026-11-30"
  }
]}
```

A `reason` responde por que o risco é aceitável **neste repositório**, não em geral — "baixa
severidade" não é motivo, "o caminho vulnerável não existe aqui, e é este o caminho" é. A
`review_by` é uma data em que alguém volta, não uma formalidade: passada, o portão reprova.

## Sintoma: o portão saiu com código 2

Código 2 é falha de execução, não aviso encontrado — tipicamente `pip-audit` fora do `PATH` ou
sem rede para consultar a base. É a distinção que o script faz de propósito: as duas
ferramentas saem com 1 *quando encontram vulnerabilidade*, que aqui é o caso normal.

```bash
pip install "$(grep '^pip-audit==' apps/api/requirements-dev.txt)"
```

## O que este portão não cobre

Ele mede o que as duas ferramentas conhecem. Ficam de fora: dependência vulnerável **sem aviso
publicado**, pacote comprometido no registro, e transitiva do lado Python que ninguém fixou —
não há lockfile de transitivas ali, e o pin direto do `starlette` resolve o caso medido, não a
classe (ADR 0023, consequências).

O `dependency-review` do CI é o outro lado, e não substitui este: ele olha o **diff** de um
pull request e pega a biblioteca ruim entrando. O que já está instalado não é diff de ninguém —
foi exatamente assim que nove avisos do `next`, sete do `starlette` e seis do `python-multipart`
conviveram meses com um CI de seis portões.

**Não há robô que abra o PR que conserta.** O conserto é manual: quem lê o vermelho sobe o pin,
roda `npm run audit` de novo e abre o PR à mão. Este job é o único mecanismo automático, e ele
detecta — não corrige.

E há duas coisas que ele **não** detecta, e que desde a ADR 0063 têm portão próprio: as actions
dos workflows e as imagens base. `npm audit` e `pip-audit` continuam sem conhecê-las — nenhuma
das duas é pacote de ecossistema —, e quem responde por elas é
`apps/api/tests/test_supply_chain_pins.py`, que reprova toda referência sem pino, mais
`npm run pins`, que **é** a lista que este parágrafo mandava revisar e que não existia.

> *Corrigido em 20/08/2026 (ADR 0062). Este parágrafo dizia que "o Dependabot
> (`.github/dependabot.yml`) abre o PR que conserta, semanalmente", e que ele era o mecanismo
> **secundário** por escolha — porque os alertas de segurança nativos do GitHub dependem da mesma
> configuração de repositório que o `codeql` não tem (`ci.yml`). O robô foi **desligado** e o
> arquivo apagado: três dos quatro tetos de `open-pull-requests-limit` estavam saturados — npm
> 5/5, `github-actions` 3/3, pip 6/5, e só docker em 2/3 —, e com o teto cheio ele não abre PR
> novo naquele ecossistema, inclusive o que consertaria um aviso futuro.
> Dezesseis PRs abertos, os mais antigos de 05/08, e nenhum mergeado. O comentário do próprio
> arquivo previa a forma da falha ("um robô que abre vinte PRs por semana treina a equipe a
> fechá-los sem ler, que é a forma de este mecanismo virar o oposto do que é"); o que ele não
> previu é que o teto transformaria isso em bloqueio.*

> *Corrigido em 20/08/2026 (ADR 0063). Este parágrafo dizia que "as imagens estão fixadas em
> versão exata (ADR 0022)" e que "quem revisa dependência revisa essas duas listas junto, porque
> nada mais o fará" — e as três afirmações estavam erradas ao mesmo tempo. **Não existia lista:**
> eram 25 linhas `uses:` espalhadas por três workflows e 16 referências de imagem espalhadas por
> cinco lugares, e quem fosse revisá-las não tinha o que abrir. **Nada verificava a instrução:**
> ela era prosa, e prosa não reprova. E **"versão exata" era falso** — `docker-compose.yml:78`
> era `minio/minio:latest`, e o job `backup-restore` puxava a mesma tag móvel num `docker run`
> que nenhum casador de `image:` alcançava.*

## Sintoma: `test_supply_chain_pins.py` ficou vermelho

O outro portão da mesma fronteira (ADR 0063), e ele não roda no `dependency-audit`: é um teste do
`pytest`, no job `api-quality`, sem rede e sem banco. Ele varre quatro superfícies por glob —
workflows, Dockerfiles, `docker-compose*.yml` e as variáveis de imagem do Terraform — e reprova
por um de quatro motivos:

1. **Uma action está em tag ou branch.** `actions/checkout@v4` é um ponteiro que o dono daquele
   repositório reescreve, e os workflows deste repositório rodam com credencial de nuvem
   (`deploy-hml.yml`) e de registro (`infra-hml.yml`).
2. **Um pino de action não diz de que versão é.** O SHA sozinho é ruído hexadecimal; a lista
   existe para ser lida por uma pessoa.
3. **Uma imagem não tem digest**, tem digest sem tag, ou está em `latest` — que reprova mesmo
   acompanhada de digest, pelo mesmo motivo do item 2.
4. **Uma linha de `PINNED_BY_EXCEPTION` deixou de ser necessária**, porque a referência sumiu do
   repositório ou passou a estar corretamente pinada. Isenção de pino não tem prazo de propósito
   — pino não caduca por calendário —, e essa asserção é o único vencimento que ela tem.

Há um quinto vermelho, e ele não é sobre pino: **a superfície ficou sem arquivo nenhum**. O glob
não achou nada, e a guarda reprova em vez de passar. Verde por não ter olhado é o defeito que a
ADR 0033 achou no `dependency-review`.

### Conserto

```bash
npm run pins             # a lista: onde está cada referência e se tem pino
npm run pins -- --update # resolve SHA pela API do GitHub e digest pelo registro, e reescreve
```

O `--update` **resolve, não escolhe**: referência sem tag ou em `latest` ele anuncia e deixa em
paz, porque pinar `minio/minio:latest@sha256:…` produziria um pino que o portão continua
reprovando com razão. Nesse caso escolha a versão à mão, ponha a tag e rode de novo.

Precisa de `gh` autenticado e do `docker buildx` — este último fala com o registro e **não**
precisa do daemon de pé. Sem um dos dois, o script sai com código 2: falha de execução, não
referência despinada, na mesma distinção que o `audit.mjs` faz.

### O preço, que está declarado

Pino por digest **congela**: `python:3.13.15-slim` não recebe mais patch de segurança ao
rebuildar, e nenhum dos dois portões vê CVE de imagem base — o `npm audit`/`pip-audit` não
conhece imagem, e este aqui só pergunta se há pino, nunca se o pino é recente. Quem revisa
dependência roda `npm run pins` junto, e agora tem o que abrir.

## Se o aviso for grave e estiver em produção

Siga o `incident-response.md`. As duas perguntas de ordem, nesta ordem: o caminho vulnerável é
alcançável por quem não está autenticado, e ele passa pelo `proxy.ts` ou pela RLS? Um aviso no
portão de sessão ou na camada HTTP é diferente de um aviso numa biblioteca de build — o `next` e
o `starlette` são os dois casos em que a resposta é "sim" por definição.
