# ADR 0023 — As dependências vulneráveis, e o portão que as mede

Data: 2026-08-05 · Fase 5 · FDD 017

## Contexto

O último item aberto do roadmap, e o único entre a Fase 5 e o lançamento externo:
*"Revisar dependências vulneráveis apontadas pelo `npm audit` antes de produção"*. O
`docs/security.md` repetia o mesmo em prosa, e a ADR 0018 já citava aquele aviso como "em
aberto" — ele atravessou pelo menos duas fatias sem ninguém mexer, o que por si já era o
sintoma.

Pela **sétima vez na Fase 5**, o que faltava não era uma promessa adiada e sim uma que os
documentos davam como cumprida. Desta vez foram cinco achados, e os três últimos só
apareceram porque alguém finalmente executou a ferramenta.

### 1. O alvo que os documentos nomeavam não fechava o `npm audit`

O `security.md` dizia "corrigido em 16.2.11". Medido, pin a pin:

| pin | postcss | sharp | `npm audit` |
|---|---|---|---|
| `next@16.2.6` (o do repositório) | 8.4.31 | ^0.34.5 | 3 pacotes, 14 avisos |
| `next@16.2.12` (a linha de patch) | **8.4.31** | **^0.34.5** | **inalterado** |
| `next@16.3.0` | 8.5.23 | ^0.35.3 | limpo |

Os nove avisos do `next` de fato fecham em 16.2.11. Mas `postcss` (três avisos, um deles
path traversal lendo `.map` arbitrário) e `sharp` (CVEs de libvips) chegam **por baixo do
`next`**, e a linha 16.2.x repina os dois nas versões vulneráveis. Seguir a instrução escrita
teria fechado o item do roadmap deixando três pacotes de severidade alta em pé — e, pior, com
um `[x]` afirmando o contrário.

### 2. A frase que tranquilizava estava invertida

O `security.md` dizia que "as pré-condições do aviso (Turbopack e locale único) não se aplicam
aqui". Turbopack **é** o bundler deste repositório: é o padrão do Next 16 e nenhum script
passa `--webpack`. O próprio build imprime `▲ Next.js 16.3.0 (Turbopack)`. A pré-condição que
não se aplica é a outra — não existe `config.i18n` nem segmento `[locale]` em lugar nenhum.

A conclusão estava certa e o motivo estava errado, que é a pior combinação: uma frase assim
sobrevive à revisão seguinte justamente por soar resolvida, e sobreviveu a duas.

### 3. O `dependency-review` parecia varredura de dependências e não era

O CI rodava `actions/dependency-review-action@v4` sem configuração e só em `pull_request`. Ele
olha o **diff** de dependências: pega a biblioteca ruim *entrando*. O que já estava no
`package-lock.json` não é diff de ninguém, e passava verde a cada push. Somado ao `codeql`
desligado por variável, o resultado é que `npm audit` **não rodava em lugar nenhum** — nem no
CI, nem em `package.json`, nem em `scripts/`. E o `ROADMAP.md` marcava `[x]` em "dependency
review e CodeQL" na lista da pirâmide inicial.

### 4. O lado Python era o ponto cego maior, e nenhum documento o mencionava

Nem `pip-audit`, nem `safety`, nem SBOM, nem uma linha no `threat-model.md`. Executado pela
primeira vez, o `pip-audit` devolveu **16 avisos em 3 pacotes**:

- **`python-multipart 0.0.20`** — seis avisos, o primeiro deles path traversal na gravação do
  arquivo. É a biblioteca que sustenta a única rota multipart do produto, o upload de
  documentos da ADR 0014.
- **`starlette 0.46.2`** — sete avisos, inclusive o CVE-2026-48710 da auditoria X41. É a
  camada HTTP da API inteira.
- **`pytest 8.3.5`** — um, só de desenvolvimento.

O roadmap dizia "falta só o `npm audit`". O lado que ninguém tinha olhado era o maior dos
dois.

### 5. Subir o FastAPI não conserta o Starlette — depende de onde

Medido por acidente e depois de propósito. O `fastapi==0.115.12` exigia `starlette<0.47.0`, e
os sete avisos só fecham em 1.3.1: nenhum `pip install -U starlette` resolveria, porque quem
segurava era a faixa do FastAPI. Até aí, esperado. O que não era: o `fastapi==0.141.1` pede
`starlette>=0.46.0` **sem teto**, então um ambiente que já tivesse o 0.46.2 instalado
**continua nele** e passa a satisfazer o FastAPI novo, enquanto uma instalação limpa resolve
para o 1.4.1. Sem lockfile de transitiva, o mesmo commit produz a versão corrigida na imagem
Docker e a vulnerável na máquina de quem já tinha — dois ambientes que se dizem iguais.

## Decisão

### 1. `next@16.3.0`, não a linha de patch

É o único alvo que zera o `npm audit`. Minor dentro do major 16, sem breaking change; traz de
quebra o próprio *"Fix Turbopack middleware matcher with i18n single locale"*. O
`eslint-config-next` sobe junto, obrigatoriamente: o `eslint.config.mjs` importa os subpaths
dele.

### 2. `starlette` declarado direto, com o precedente do `cryptography`

O `requirements.txt` já tinha o argumento escrito, para outra biblioteca: *"depender de
trânsito de outra biblioteca para um módulo de cifra é dívida"*. Vale igual para a camada HTTP,
e agora com uma razão medida em cima (achado 5). Um pin direto tira a resolução do acaso.

Fica a regra: **um aviso numa transitiva do FastAPI se conserta subindo o FastAPI**, nunca
fixando a transitiva por baixo de uma faixa que a proíbe.

### 3. O portão é `scripts/audit.mjs`, e ele reprova

Mora em `scripts/` pela razão do `backup.sh` e do `loadtest.py`: é operação. Uma porta só para
os dois ecossistemas, na forma do `queue_document_scan` — duas listas de exceção em dois
formatos seriam duas coisas para envelhecer em paralelo, e a metade Python é justamente a que
não existia.

Núcleo puro (`evaluate(findings, registry, today)`), bordas impuras. O dia entra por parâmetro
como em `results.py`, que é o que torna o portão testável.

**Sem limiar de severidade.** Um `--audit-level=high` seria um segundo mecanismo de exceção, e
silencioso: tudo abaixo do corte passaria sem ninguém escrever nada. É a mesma regra de o
`skipped` não ser `clean` no `scanner.py` — ausência de verificação não vira afirmação de
segurança. (O `pip-audit` sequer publica severidade, então um limiar não teria como valer para
os dois lados sem inventar um deles.)

### 4. Aceitar um risco é escrever uma linha com prazo

`docs/security/advisories.json` é a única forma de um aviso não reprovar. Cada entrada leva
`id`, `package`, `reason` — por que é aceitável **aqui**, não em geral — e `review_by`.

Duas propriedades carregam o resto, e as duas reprovam:

- **exceção vencida reprova.** Risco aceito é decisão com prazo, não permissão permanente;
- **entrada órfã reprova.** Se não casa com aviso nenhum, ou o aviso foi corrigido (e a linha
  deve sair) ou o `id`/`package` foram escritos errado — caso em que a exceção nunca valeu
  para o aviso que alguém achou estar aceitando, e o arquivo dizia uma coisa enquanto o portão
  fazia outra.

É o quarto gate de deriva do repositório, ao lado do `alembic check`, do `openapi.json` e do
`prompt-registry.json`. E **ao contrário do `prompt-registry.json`, este arquivo não é
append-only**, pela razão inversa: lá a história é o portão, e reescrever o passado é o que se
quer impedir; aqui a linha precisa poder sumir no dia em que o aviso é corrigido, senão o
arquivo vira uma lista de coisas que já não são verdade.

O registro nasce **vazio**, e isso é a afirmação: esta fatia consertou em vez de aceitar.

### 5. Job próprio no CI, em `push` e em `pull_request`

`dependency-audit`, pelo argumento do `backup-restore`: precisa dos dois toolchains, e uma
dependência vulnerável merece o próprio vermelho em vez de se confundir com um lint quebrado.

O `dependency-review` **fica**. Os dois não se sobrepõem — ele pega a biblioteca ruim
entrando, este pergunta o que já está instalado —, e a divisão fica escrita no YAML porque foi
confundi-los que produziu o achado 3.

Em `push` também, ao contrário dele: um aviso novo não chega por pull request, chega porque
alguém o publicou. Restringir a PR deixaria `main` descoberta exatamente entre as entregas.

### 6. Dependabot é o mecanismo secundário, e a ordem é deliberada

Quem reprova é o CI; o Dependabot só abre o PR que conserta. O inverso seria confiar num
controle que este repositório não pode ligar: *version updates* funcionam em repositório
privado, mas os **alertas de segurança** dependem da mesma configuração que o `codeql` não
tem. Foi assim que o aviso do `next` atravessou duas fatias.

Semanal, com teto baixo e agrupado por pares que andam juntos (`next`/`eslint-config-next`,
`fastapi`/`starlette`/`python-multipart`). Um robô que abre vinte PRs por semana treina a
equipe a fechá-los sem ler, que é este mecanismo virando o oposto de si.

### 7. O 422 para de devolver o corpo da requisição

Achado ao subir o FastAPI, e o defeito que a fatia teria **introduzido** se ninguém olhasse: a
partir do `0.141` cada item de `detail` inclui `ctx` e `input`, e `input` é o corpo inteiro de
quem chamou.

Numa API cujos corpos fossem todos inócuos isso seria verborragia. Aqui não são: `DriveCallbackIn`
carrega `code` e `state`, e o `code` é o authorization code do Google — trocável pelo refresh
token que a ADR 0016 sela com AES-256-GCM por ser o único segredo reversível do portal. Bastava
o `state` estourar o tamanho para o 422 devolver o `code` em claro, num corpo de erro que cai
no log de quem chamou e no access log de todo proxy no meio.

O handler é do `app` inteiro e deixa passar `type`, `loc` e `msg`. Deliberadamente **não** é
redação por nome de campo como a de `telemetry.py`: ali procura-se o campo suspeito entre
muitos inócuos, aqui *todo* `input` é o corpo alheio — e uma allowlist nem pegaria estes dois,
já que `code` e `state` não casam com nenhuma dica de `_SECRET_HINTS`.

E o esquema publicado poda os mesmos campos, a partir da **mesma constante**
(`VALIDATION_DETAIL_FIELDS`). Um contrato anunciando campo que a resposta não traz é a classe
de defeito que a ADR 0020 recusou acrescentar ao tipar as respostas, só que na direção oposta —
e a única das duas em que quem fica errado é a ferramenta de quem consome.

## Consequências

- `npm audit` e `pip-audit` limpos, e agora **verificado a cada push** em vez de quando alguém
  lembra.
- O `docs/api/openapi.json` mudou **uma linha**: `format: binary` virou
  `contentMediaType: application/octet-stream` no campo de upload, que é a grafia correta em
  OpenAPI 3.1. O gate da ADR 0020 pegou a mudança, como devia; o `ctx`/`input` não aparece
  porque a decisão 7 o removeu dos dois lados.
- Sete constantes de status depreciadas pelo Starlette novo (`HTTP_422_UNPROCESSABLE_ENTITY`,
  `HTTP_413_REQUEST_ENTITY_TOO_LARGE`) renomeadas. Ainda funcionavam; o motivo de mexer é o da
  ADR 0018 — log poluído por aviso que ninguém vai ler treina a não ler o log.
- `apps/api/requirements-dev.txt` deixou de duplicar `httpx==0.28.1`, que já vinha do
  `requirements.txt`. Inofensivo enquanto os pins coincidiam, e uma divergência silenciosa no
  primeiro bump de um arquivo só.
- **O que continua faltando, declarado:** não há lockfile de transitivas do lado Python. O pin
  direto do `starlette` resolve o caso medido, não a classe — a próxima transitiva a ganhar
  aviso vai depender de alguém notar. Um `pip-compile`/`uv.lock` é a resposta certa e é fatia
  própria: trocar o mecanismo de resolução junto com uma remediação torna impossível saber qual
  dos dois quebrou, que é o mesmo argumento com que a ADR 0020 adiou os produtores tipados.
- **E o que o portão não faz:** ele mede o que as duas ferramentas conhecem. Uma dependência
  sem aviso publicado, um pacote comprometido no registro, ou uma action do GitHub com tag
  móvel continuam fora do alcance dele. O Dependabot de `github-actions` e `docker` cobre parte
  disso por atualização, nenhum dos dois por detecção.

## Alternativas recusadas

**Parar em `next@16.2.12`.** Fecharia o item literal do roadmap e deixaria três pacotes de
severidade alta em pé, com um `[x]` afirmando o contrário. Foi a alternativa que a instrução
escrita mandava seguir, e a medição é o que a derrubou.

**`npm audit fix --force`.** Resolve por escalada de major sem ninguém ler o que mudou — num
repositório onde o `proxy.ts` é o portão de sessão, é a ferramenta errada para o alvo mais
central.

**Job agendado e não-bloqueante.** É o "vermelho permanente" contra o qual o próprio `ci.yml`
já argumentou ao explicar por que o `codeql` fica *pulado* e não vermelho: um job cronicamente
vermelho treina quem lê o CI a ignorar vermelho. Um portão que reprova com exceções datadas
mantém o vermelho significando alguma coisa.

**Limiar de severidade em vez de registro.** Ver decisão 3: seria um segundo mecanismo de
exceção, silencioso e sem prazo.

**Filtrar `input` por nome de campo, como o `telemetry.py`.** Ver decisão 7: adiaria o dia em
que um corpo novo passa a carregar segredo, e nem pegaria os dois que existem hoje.
