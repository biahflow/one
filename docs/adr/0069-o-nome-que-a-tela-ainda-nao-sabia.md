# ADR 0069 — O nome que a tela ainda não sabia

**Status:** aceito
**Data:** 25/08/2026
**Fase:** 7 — e a primeira fatia depois de o produto mudar de nome

## Contexto

A ADR 0067 renomeou o produto numa frase — *"O produto passa a ser chamado One"* — e parou aí.
Não decidiu marca, cor, tipografia, token, nem a relação entre **Biahflow** (a empresa) e **One**
(o produto). Um dia depois, toda superfície que o cliente alcança ainda afirmava o nome antigo: a
sidebar escrevia `portal`**`labs`**, o `<title>` dizia `Portal Labs | Portal do Cliente`, o
assistente se apresentava como "o assistente do Portal Labs", o e-mail saía de
`Portal Labs <portal@portallabs.local>`, a tela do Keycloak anunciava `Portal Labs (Local)` e o
`og.png` estampava o monograma da marca antiga.

**E o nome era a metade menor.** Não havia `components/`. O wordmark existia **duas vezes escrito à
mão**, em `DashboardClient.tsx` e em `login/page.tsx`, sem nada que cobrasse que os dois blocos
ficassem idênticos — o defeito que o `textfold.py` existe para impedir do lado da API. O `@theme`
tinha três estados semânticos e a Issue #46 cobrava quatro. E `app/globals.css` escrevia o roxo da
marca **à mão, em quatro lugares**, contra a regra que o próprio `CLAUDE.md` publica.

## Decisão

### (a) O gate de design fica antes do planejamento, e ele mudou o desenho três vezes

A Engineering OS põe o Design Approval **antes do Planner**, não antes do Builder, e a razão é
econômica: um plano que decompõe superfície não aprovada produz tarefas que precisam ser recortadas
de novo quando o desenho muda. Esta fatia é a prova executável disso — a revisão 1 foi ao gate com
**duas** direções de marca desenhadas lado a lado, e voltou com a segunda escolhida, o descender em
inglês e uma pergunta nova. Cada emenda virou revisão, nunca nota de rodapé, pelo mesmo motivo:
**aprovar um pacote que não mostra o que foi decidido não é evidência de nada** — é contra o
artefato que a revisão de código compara o que foi construído.

O que o gate custou: quatro revisões, uma hora. O que ele evitou: descobrir na tela que o selo não
era a direção certa, depois de ele estar em quatro arquivos, dois testes e um `og.png`.

### (b) Biahflow é a empresa; One é o produto — e a regra de uso é escrita

O produto aparece na marca, na aba do navegador e no assunto do e-mail. A empresa aparece onde a
cópia fala do **time**: quem responde uma pendência, quem precisa fazer um vínculo, quem o cliente
procura quando algo falha. Sem essa distinção, `"Pendência criada para Portal Labs"` não tem
substituto óbvio — e o motivo é que ela **nunca foi sobre o produto**, era sobre quem responde.

Daí `PROVIDER_LABEL = "Biahflow"`, `Time Biahflow`, `Administrador Biahflow`, e o `<title>` sendo
`One` — **sem aposto**. `Portal do Cliente` saiu de tudo: um nome que precisa de legenda ao lado é
um nome que ainda não confia em si, e aquele aposto era herança do tempo em que "portal" era o
produto.

### (c) O roxo fica — e três valores dele reprovavam contraste

Retê-lo é decisão declarada, não herança: é o que distingue esta tela da identidade clay do Pulse
sem ler uma palavra. Mas medir a paleta em vez de admirá-la achou o que ninguém tinha olhado, e o
critério é **AA para texto normal (4,5:1)**, não AA-large, porque nada aqui é texto grande — o
corpo secundário é 14 px e a pastilha de estado é 10 px em negrito:

| Par | Antes | Depois |
| --- | --- | --- |
| `.eyebrow` (`slate-400`) sobre branco | **2,56:1** | 4,81:1 |
| `muted` sobre branco | 4,36:1 | 4,81:1 |
| `muted` sobre `canvas` | 4,10:1 | 4,52:1 |
| `success-600` sobre `success-50` | 3,90:1 | 4,54:1 |
| `warning-600` sobre `warning-50` | 3,88:1 | 4,51:1 |

**O pior caso era o rótulo.** O `.eyebrow` fica acima de cada título de painel, em caixa alta e
10 px — a condição mais difícil da tela —, e a 2,56:1 ele reprovava até o critério de texto grande.
A correção é usá-lo em `muted`, que a esta altura passa AA: um rótulo não deve ser *menos* legível
que a frase que ele rotula.

Ganharam nome os valores que existiam sem um: o estado **informativo**, que não existia e que a
Issue cobrava; o **anel de foco**, que era o literal de `brand-500` dentro do `:focus-visible`; a
**superfície** do cartão, que era `bg-white`; e o verde do gradiente do `body`, que era
`rgba(33, 161, 121, …)` escrito à mão — não dava para verificá-lo porque ele não era um valor do
sistema. As quatro ocorrências de hex de marca escritas à mão viraram `color-mix` derivado de token.

### (d) A primitiva, e o wordmark num lugar só

`components/` nasce com três primitivas, e a regra de admissão é a das classes: **o que ninguém usa
não entra.** `Brand` porque o wordmark existia duplicado; `StatePill` porque o estado precisa de
**ícone e texto e cor**, e sem o ícone ele some em tons de cinza; `Button` porque as quatro
variantes estavam espalhadas em `.ai-button`, `.auth-sso`, `.admin-submit` e `.text-button`.

O `Button` tem um detalhe que só existe por causa de uma guarda: `onClick` é escrito **por extenso
na tag**, nunca por espalhamento de props, porque `inertButtons()` lê o texto-fonte e um `{...rest}`
faria a primitiva nascer inerte aos olhos dela **mesmo funcionando em runtime**.

### (e) Token sem consumidor não fica — e a regra ganhou portão

O commit que publicou `docs/design/one-design-system.md` acrescentou ao `@theme` **sete tokens sem
consumidor**, enquanto o próprio documento afirmava, em seção dedicada, que "um token só entra no
`@theme` se algum seletor o consumir". É a ADR 0033 acontecendo dentro da fatia que a cita:
documento publicado sobre o que não existe.

A guarda que fecha isso está em `tests/rendered-html.test.mjs`, ao lado do `inertButtons`, e tem as
três propriedades que este repositório aprendeu a exigir. **O corpus é derivado**: sai do próprio
bloco `@theme`, hoje 32 tokens, nenhum digitado — um `for` sobre nomes escritos à mão é o defeito da
ADR 0033. **É fail-closed em três pontos**: `@theme` ilegível, `@theme` do qual não se extraiu
token, e corpus vazio; verde por não ter conseguido olhar é a forma do `dependency-review` da
ADR 0023. **E o elo é medido**: um token é consumido por `var(--token)` no CSS ou pelo utilitário
que o Tailwind gera dele, com o casador fechado nas duas pontas por asserção de largura zero — sem
isso `--color-brand-5` passaria verde por causa de `bg-brand-500`, que é o `.priority` da ADR 0033 e
o `date` da ADR 0038, os dois casos em que um nome casou por substring e a guarda deu por consumido
o que ninguém consumia.

O bloco `@theme` **sai do corpus** antes da busca, e a razão está escrita no código:
`--color-focus: var(--color-brand-500)` faria um token provar a si mesmo.

### O que fica de fora, declarado em vez de fingido

Tema escuro — não existe neste produto e não foi proposto. Redesenho de tela existente: as telas
mudam de nome, não de forma, e renomear classe de CSS quebraria os seletores dos specs de e2e sem
entregar nada ao cliente. O laço de aceite da ADR 0067: a superfície de revisão do cliente é
**desenhada e declarada reservada** no pacote, com hachura e selo, e no produto ela simplesmente não
é renderizada — controle inerte é defeito, não *placeholder*. Renomear o repositório, que a Issue
exclui. E trocar `.state--0..3` pelas variantes novas no produto inteiro, que é churn.

## Medição

**O baseline estava vermelho, e não por causa desta fatia.** As ADRs 0067 e 0068 entraram em `main`
declarando `**Status:** Accepted` — o vocabulário da guarda de índice é `{aceito, aceita}` — e sem
linha no `ROADMAP.md`. `test_roadmap_index.py` reprovava por dois lados a cada push desde 24/08. É o
defeito que a ADR 0054 existe para pegar, contra as duas primeiras ADRs escritas depois que a guarda
existe. Consertado em commit próprio, antes de qualquer trabalho de interface.

**A guarda de token foi medida por mutação, duas vezes e por duas pessoas diferentes.** Token de
mentira acrescentado ao `@theme`: vermelho, nomeando o token. Retirado: verde. `@theme` renomeado:
vermelho pelo fail-closed. `@theme` esvaziado: vermelho. Isenção desnecessária: vermelho pela
asserção de obsolescência.

**E a mutação achou um defeito na primeira versão da guarda**, que é a razão de ela existir: ao
renomear o bloco para testar o fail-closed, o casador solto `/@theme\b/` encontrou a menção a
`@theme` **dentro de um comentário** do bloco novo de `@layer components`, balanceou as chaves do
bloco errado e reprovou dizendo *"o `@theme` existe e está vazio"* sobre um arquivo onde ele não
existia mais. Guarda certa pela razão errada é exatamente o que a mutação pega. A âncora virou
`^@theme` em início de linha.

**O pacote de design mentia sobre a própria letra.** Ele afirmava, em parágrafo próprio, que "a
captura foi feita numa máquina com Inter disponível". Medido com `canvas.measureText`: `Inter`
resolvia nesta máquina **exatamente como uma fonte inexistente**, e a pilha caía em `system-ui` —
enquanto o produto renderiza Inter, auto-hospedada pelo `next/font`. As capturas das revisões 1 a 3
mostravam, portanto, a letra do sistema. É o defeito que a regra da captura congelada existe para
evitar — *"uma renderização depende de fonte, navegador e plataforma"* —, porque **aprovar uma marca
é aprovar uma letra, e a letra aprovada não era a letra entregue**. A revisão 4 embute a Inter no
arquivo como data URI, o que também fecha uma violação latente da exigência de o artefato abrir
"sem build, sem toolchain e sem rede": ele dependia do que estivesse instalado na máquina de quem o
abrisse. Corrigir só a frase teria deixado o pacote honesto e continuado errado.

**De quebra, um falso verde que quase passou.** Depois que a pilha local subiu, `pytest` passou a
reportar **240 passados e 419 pulados**, com a mensagem "PostgreSQL is not reachable" — enquanto o
Postgres estava de pé e respondia. A causa é o `.env` que o `docker compose` pede: ele aponta o
banco para o hostname **do contêiner**, e o `pydantic-settings` o lê quando o `pytest` roda do mesmo
diretório. Sem `.env`, os mesmos testes voltam a rodar: **659 passados, zero pulados**. É o que o
`CLAUDE.md` diz sobre skip — ele não diz "não dá para provar aqui", diz que o ambiente não é o que
alguém supôs, em verde. No CI não acontece: o job `api-quality` não cria `.env`, e lá um skip
reprova.

**Os ativos.** O `og.png` foi de **1,1 MB para 180 KB**, e ganhou gerador versionado ao lado — o
anterior era um binário **sem fonte**, e foi assim que o nome antigo sobreviveu sete fases dentro de
um arquivo: ninguém conserta o que não pode reabrir. O `favicon.svg` desenha a inicial como
**path, e não `<text>`**, porque um favicon é renderizado fora do produto, onde a fonte do produto
não está carregada.

**Os portões, na revisão final:** 659 testes de API com zero pulados, 142 de web, 38 de e2e contra a
pilha inteira, `lint` limpo, `npm run audit` sem aviso, `alembic check` sem deriva.

## Consequências

O One passa a ter contrato de token e de primitiva que a próxima tela cita em vez de reinventar, e o
`docs/project-context.md` finalmente declara onde o sistema de design mora — antes desta fatia ele
não declarava, porque o sistema não existia como documento e a linguagem vivia dentro do CSS.

Três cores mudam de valor em telas existentes. É correção de contraste medida, não gosto, e o maior
deslocamento é de 0,02 em luminância relativa.

A guarda nova reprova o oitavo token órfão. A isenção dela **nasce vazia**, e o que a mantém assim é
a asserção de obsolescência — no precedente do `PINNED_BY_EXCEPTION`, sem prazo, porque token não
caduca por calendário.

Fica aberto, medido e registrado: o `docker-compose.yml` passa `NOTIFICATIONS_FROM_NAME` só ao
serviço `api`, e **quem envia o e-mail é o worker** — hoje inofensivo porque o default do
`config.py` é o mesmo, e uma armadilha para quem sobrescrever a variável. Não existe
`apple-touch-icon`, embora o pacote nomeie três lugares para o tile. E o anel de foco herda
`transition-colors` de `.nav-item` e irmãos, que no Tailwind v4 inclui `outline-color`: nos ~150 ms
seguintes ao `Tab` ele exibe a cor de origem antes de virar a da marca. Os três são pré-existentes,
e nenhum foi consertado de carona.

## O que esta fatia não é

Não é o laço de aceite do cliente: a superfície de revisão foi desenhada para provar a linguagem
visual e está declarada **reservada**, sem rota, sem evento e sem escrita. Não é implantação — o
portal segue fora do ar desde 13/08/2026 (ADR 0053), e a validação de navegador rodou na pilha
local, que é runtime real. Não é renomear o repositório. E não é redesenho: a tela do cliente tem
hoje a mesma forma de ontem, com outro nome e três cores que agora passam AA.
