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

E há duas coisas que ele **não** detecta, agora sem nada por trás: as actions do `ci.yml` e as
duas imagens base do compose. `npm audit` e `pip-audit` não as conhecem, e as imagens estão
fixadas em versão exata (ADR 0022) — congelam na CVE do dia em que foram escolhidas até alguém
subir o pin. Quem revisa dependência revisa essas duas listas junto, porque nada mais o fará.

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

## Se o aviso for grave e estiver em produção

Siga o `incident-response.md`. As duas perguntas de ordem, nesta ordem: o caminho vulnerável é
alcançável por quem não está autenticado, e ele passa pelo `proxy.ts` ou pela RLS? Um aviso no
portão de sessão ou na camada HTTP é diferente de um aviso numa biblioteca de build — o `next` e
o `starlette` são os dois casos em que a resposta é "sim" por definição.
