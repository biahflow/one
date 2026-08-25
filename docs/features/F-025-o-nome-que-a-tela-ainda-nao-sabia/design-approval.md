# Design Approval Package — F-025 · Identidade do One e fundação de design

Classification: INTERFACE_CHANGE
Revision: 3
Status: Approved
Date: 2026-08-25
Produced by: Claude Opus 5 (1M context), sob a Engineering OS

> Governado por `workflows/design-approval.md`. Este artefato é evidência para um gate humano.
> Não é implementação e não deve ser copiado para dentro do código da aplicação.

## Approval record

| Field | Value |
| --- | --- |
| What was approved | **visual e cópia** |
| Approved by | Daniel Campos |
| Date | 25/08/2026 |
| Revision approved | **3** |
| Explicitly **not** approved | A direção de marca com selo (considerada e recusada) · o descritor `Portal do Cliente` (retirado na revisão 3) · tema escuro · redesenho de tela existente · o laço de aceite da ADR 0067 · renomear o repositório · qualquer coisa listada em *Open questions* |

### Histórico de revisões

| Rev | O que aconteceu | Artefato |
| --- | --- | --- |
| 1 | Levada ao gate com **duas** direções de marca renderizadas lado a lado, para escolha. | `design/one-dap-r1.html` + `design/captures/` — **preservados** |
| 2 | Direção B (só wordmark), descender em inglês, e o símbolo do `favicon`/`og.png` resolvido como tile com a inicial. | superseded antes de qualquer implementação consumi-la — não preservada |
| 3 | Sai o descritor `Portal do Cliente`: o produto se apresenta pelo nome, sem aposto. Some do `<title>`, do cartão de compartilhamento e do rodapé do painel de autenticação. | `design/one-dap-r3.html` + `design/captures-r3/` — **a revisão que vale** |

**A revisão 1 fica.** É o que a pessoa olhou quando escolheu entre as duas direções de marca, e
apagá-la tornaria aquela decisão não verificável depois. **A revisão 2 não fica**, e a diferença é
que ninguém agiu sobre ela: ela existiu por vinte minutos entre duas emendas do mesmo gate, nenhuma
implementação a consumiu e nenhuma revisão de código dependeu dela. O que ela decidiu está nesta
tabela e no corpo deste registro; guardar cinco megabytes de captura de um estado intermediário
seria confundir histórico com evidência.

### Errata

Uma divergência **interna** ao artefato, achada na implementação e registrada aqui em vez de
resolvida no silêncio:

| Onde | O artefato diz | Vale |
| --- | --- | --- |
| Alvo de toque do botão | a prosa da §03 diz `44` como altura mínima de alvo de toque; o CSS da §05 escreve `min-height: 42px` | **44 px.** A prosa registra a decisão; os 42 px foram descuido de quem escreveu o artefato |

Não houve revisão nova por isto, e a razão é a proporção: dois pixels de altura mínima não mudam o
que a pessoa aprovou ao olhar a captura, e recapturar catorze imagens por eles trocaria evidência
por cerimônia. Uma divergência que **mudasse** o que foi visto seria revisão, não errata.

Cada emenda virou revisão nova em vez de nota de rodapé, e a razão é a mesma nas três vezes:
**aprovação de um pacote que não mostra o que foi decidido não é evidência de nada.** A revisão 1
renderizava `por Biahflow` em seis lugares e não desenhava símbolo algum; a 2 ainda estampava o
descritor em dois. É contra o artefato que a revisão de código compara o que foi construído, então
ele precisa ser o que vale.

A aprovação desta revisão não é aprovação de uma posterior. Um pacote materialmente alterado é
uma revisão nova e precisa do seu próprio registro. **Aprovação de visual não é aprovação de
cópia**, e vice-versa: se só uma das duas for aprovada, diga qual.

## Artifact

| File | What it is |
| --- | --- |
| `design/one-dap-r3.html` | **A revisão aprovada.** Renderização auto-contida: abre com duplo clique — sem build, sem toolchain, sem rede. Um arquivo, CSS embutido e ícones em SVG inline. |
| `design/captures-r3/` | **Captura congelada do que foi aprovado** — é a isto que a aprovação se refere. Catorze imagens: capa, uma por seção, e o pacote inteiro. |
| `design/one-dap-r1.html` + `design/captures/` | Histórico: o que foi levado ao gate, com as duas direções de marca. Não é a revisão aprovada. |

A captura existe porque uma renderização depende de fonte, navegador e plataforma. As capturas
foram feitas com Chromium headless (Playwright 1.62.1), 1280 px de largura, escala 1,5× (o pacote
inteiro em 1×), sobre o mesmo arquivo desta revisão — validação determinística, sem modelo no laço.

**Sobre a fonte:** o artefato pede `Inter` e cai para a pilha de sistema quando ela não está
instalada. A captura foi feita numa máquina com Inter disponível; é o que a aprovação enxerga, e
é a fonte que o produto carrega por `next/font/google`.

## Surfaces and states included

| Surface | State | In package |
| --- | --- | --- |
| Shell do cliente — desktop | sucesso | sim (§06) |
| Shell do cliente — mobile 390×844 | sucesso | sim (§07) |
| Shell do cliente | carregando | sim (§09) |
| Shell do cliente | vazio (sem projeto atribuído) | sim (§09) |
| Shell do cliente | erro (assistente indisponível) | sim (§09) |
| Shell do cliente | não autorizado (404, nunca 403) | sim (§09) |
| Autenticação `/login` | sucesso + erro | sim (§08) |
| Marca | wordmark em três tamanhos, sobre claro e sobre o gradiente escuro | sim (§01) |
| Símbolo | tile com a inicial em 16 / 32 / 64 / 180 px | sim (§01) |
| Cartão de compartilhamento (`og.png`) | 1200 × 630 | sim (§01) |
| Estados semânticos | sucesso, atenção, falha, informativo — e em tons de cinza | sim (§04) |
| Controles | repouso, hover, **foco de teclado**, desabilitado | sim (§05) |
| Revisão/decisão do cliente | `client_review` + os cinco rótulos de aceite | sim (§10) — **reservado** |
| Notificação | lista com não lida + envelope do e-mail | sim (§11) |

Deliberadamente **fora** do pacote, com o motivo:

| Surface | Por que não está aqui |
| --- | --- |
| Chat e citações | Nada muda de forma nem de cópia; a única mudança é a frase de apresentação do assistente, que é texto e não desenho. |
| Telas de `/admin/*` | São superfície interna. Herdam os tokens; nenhuma decisão visual nova. |
| Aba Resultados, Documentos, Cronograma | Mesma linguagem já provada pelo shell e pelos painéis de §06. Desenhá-las de novo seria pedir aprovação de coisa que não muda. |
| Tema escuro | Não existe neste produto e não está sendo proposto. |
| E-mail em HTML completo | Só o envelope entra (§11). O corpo do digest não muda de forma nesta fatia. |

## Provenance of visual values

Design system referenced: **nenhum documentado** — este é o achado. `docs/project-context.md`
não declara onde vive o design system, e a linguagem existe apenas dentro de `app/globals.css`.
Por isso este pacote é o que a Engineering OS descreve: *"um projeto nessa posição deve esperar que
seu primeiro pacote aprovado estabeleça a linguagem que os pacotes seguintes citam — e deve
extrair essa linguagem para um documento em vez de deixá-la no artefato."* A extração é
`docs/design/one-design-system.md`, e ela é parte do que se está aprovando.

Fonte lida em 25/08/2026: `app/globals.css`, bloco `@theme` e `@layer components`.

| Value | Source | New? |
| --- | --- | --- |
| `--color-ink: #17243a` | `app/globals.css` | não — retido, explicitamente |
| `--color-line: #e8edf4` | `app/globals.css` | não — retido |
| `--color-canvas: #f6f8fc` | `app/globals.css` | não — retido |
| `--color-navy: #16233a` | `app/globals.css` | não — retido |
| `--color-brand-50…900` (oito degraus) | `app/globals.css` | não — retido, e é a decisão de marca do One |
| `--color-danger-50/600` | `app/globals.css` | não — retido |
| Três sombras em camadas | `app/globals.css` | não — retido |
| Inter, por `next/font/google` | `app/layout.tsx` | não — retido |
| Três pontos de quebra (761 / 980 / 760 px) | `app/globals.css` | não — retido |
| `--color-muted: #6b7a91` → **`#657389`** | medição de contraste | **sim — corrigido aqui** |
| `--color-success-600: #1c8a63` → **`#1a7e5b`** | medição de contraste | **sim — corrigido aqui** |
| `--color-warning-600: #b06a1a` → **`#a16118`** | medição de contraste | **sim — corrigido aqui** |
| `--color-info-50: #e9f1fd` / `--color-info-600: #1d5fb4` | — | **sim — novo, não existia estado informativo** |
| `--color-accent-green: #1c8665` | era `rgba(33,161,121,.05)` à mão | **sim — novo, o valor existia sem nome** |
| `--color-focus` | era o literal de `:focus-visible` | **sim — novo, o valor existia sem nome** |
| `--color-surface: #ffffff` / `--color-surface-sunken: #f8fafc` | eram `bg-white` / `bg-slate-50` | **sim — novo, nomeia a hierarquia de superfície** |
| `--radius-card: 16px` / `--radius-control: 12px` / `--radius-pill: full` | eram `rounded-2xl` / `xl` / `full` | **sim — novo, vira política citável** |
| Escala de espaço: 4 · 8 · 12 · 16 · 20 · 24 · 36 · 44 | base de 4 px do Tailwind v4 | não — a base é retida; **novo** é fixar os oito degraus |
| Wordmark `One.` com o ponto em `brand-500` | gesto do wordmark antigo, cujo sufixo ia em roxo | **sim — decidido aqui** |
| Descender `by Biahflow` | — | **sim — decidido aqui** |
| O ponto vira `brand-200` sobre o gradiente | medição: `brand-500` sobre `brand-600` dá 1,06:1 | **sim — decidido aqui** |
| Tile com a inicial `O`, em `brand-500` | é o wordmark comprimido; o raio é o de controle | **sim — decidido aqui**, e só onde não cabe texto |
| `favicon.svg` = o tile | hoje é azul `#68C4FF`, fora da paleta | **sim — decidido aqui** |
| `og.png` = tile + wordmark + a frase do produto | hoje estampa `portal labs` e o monograma "P" | **sim — decidido aqui** |
| O produto se apresenta **sem aposto** — sai `Portal do Cliente` | — | **sim — decidido na revisão 3** |
| Ícone junto do texto em toda pastilha de estado | hoje é cor + texto | **sim — sendo decidido aqui** |

Se este pacote e `app/globals.css` divergirem, **a fonte vence e o pacote está velho**.

### As medições de contraste

Feitas com a fórmula de luminância relativa da WCAG 2.1, sobre os hexes exatos. O critério é
**AA para texto normal (4,5:1)**, e não AA-large, porque nada aqui é texto grande: o corpo
secundário é 14 px e a pastilha de estado é 10 px em negrito.

| Par | Antes | Depois |
| --- | --- | --- |
| `muted` sobre branco | 4,36:1 ✗ | 4,81:1 ✓ |
| `muted` sobre `canvas` | 4,10:1 ✗ | 4,52:1 ✓ |
| `.eyebrow` (`slate-400`) sobre branco | **2,56:1 ✗✗** | 4,81:1 ✓ (passa a usar `muted`) |
| `success-600` sobre `success-50` | 3,90:1 ✗ | 4,54:1 ✓ |
| `warning-600` sobre `warning-50` | 3,88:1 ✗ | 4,51:1 ✓ |
| `danger-600` sobre `danger-50` | 4,76:1 ✓ | inalterado |
| `info-600` sobre `info-50` | não existia | 5,51:1 ✓ |
| `brand-700` sobre `brand-50` | 7,52:1 ✓ | inalterado |
| branco sobre `brand-500` | 5,39:1 ✓ | inalterado |
| `brand-200` sobre `brand-900` (ponta escura do gradiente) | 7,71:1 ✓ | inalterado |
| `brand-200` sobre `brand-600` (ponta clara do gradiente) | 4,04:1 — AA-large | inalterado, e é onde ele é usado: rótulo curto de 10,5 px |

O pior caso do produto era o `.eyebrow`: 10 px, caixa alta, `slate-400`, **2,56:1**. Ele reprova
até o critério de texto grande, e é o rótulo que fica acima de cada título de painel.

## Delivered vs reserved

| Element | This feature | Reserved for | Becomes real when |
| --- | --- | --- | --- |
| Tokens (cor, raio, superfície, foco) | entrega | — | — |
| Marca — wordmark `One.` e descender `by Biahflow` | entrega | — | — |
| Tile com a inicial — **só** em `favicon`, atalho de tela e `og.png` | entrega | — | — |
| Selo (anel com ponto), da Direção A | **não entrega** | — | recusado no gate; não volta sem revisão nova |
| `favicon.svg` e `og.png` | entrega | — | — |
| Primitivas: marca, pastilha de estado, botão | entrega | — | — |
| Vitrine interna `/admin/design` | entrega | — | — |
| `docs/design/one-design-system.md` | entrega | — | — |
| Terminologia One em toda superfície do cliente | entrega | — | — |
| **Superfície de revisão/aceite do cliente (§10)** | **desenha, não entrega** | o laço de aceite da ADR 0067 | quando existir contrato de projeção com `approvals` chegando de verdade e evento `client.accepted` de volta |
| Tema escuro | não desenha | — | pacote e aprovação próprios |
| Estados de aceite no shell (aba, contador, aviso) | não desenha | mesma fatia futura | idem |

**Como o elemento reservado se comporta antes de ser real: ele não é renderizado.** Não entra na
tela do cliente desabilitado, nem "só para mostrar". Um controle inerte é defeito, não
*placeholder* — e há guarda no repositório que reprova `<button>` sem `onClick` justamente porque
onze deles sobreviveram assim. No artefato ele está visualmente marcado com hachura e selo
`reservado`, para que ninguém confunda desenho com entrega.

## Decisions this package carries

1. **Biahflow é a empresa; One é o produto — e a regra de uso é explícita.** O produto aparece na
   marca, na aba e no assunto do e-mail; a empresa aparece onde a cópia fala do *time*. Sem essa
   distinção, "Pendência criada para Portal Labs" não tem substituto óbvio, porque nunca foi sobre
   o produto: era sobre quem responde.

2. **A marca do One é o wordmark, e só ele na tela.** `One.` com o ponto final em `brand-500`,
   herdando o gesto do wordmark antigo, cujo sufixo *labs* ia em roxo; descender `by Biahflow`. A
   direção com selo foi levada ao gate e **recusada**. O monograma "P" antigo não entra na conta:
   não é portável — existe embutido no `og.png` e em nenhum outro lugar, e a aplicação nunca o usou.
   Onde texto não cabe — aba do navegador, atalho de tela, cartão de compartilhamento — entra um
   tile com a inicial, que **não é uma segunda marca**: é o wordmark comprimido até caber em 16 px.
   E o ponto troca de valor sobre o gradiente escuro, porque `brand-500` sobre `brand-600` dá
   1,06:1 — ele passa a `brand-200`.

3. **O roxo fica, e passa a ter procedência.** Não por inércia: é o que distingue esta tela da
   identidade clay do Pulse sem ler uma palavra, e seus pares de contraste já estavam pagos.
   Retê-lo é decisão declarada, não herança.

4. **Três cores mudam porque foram medidas e reprovaram** — `muted`, `success-600`, `warning-600` —
   e o `.eyebrow` troca `slate-400` por `muted`. É a única mudança visual que atinge tela existente,
   e ela é de contraste, não de gosto: o maior deslocamento é de 0,02 em luminância relativa.

5. **O estado informativo passa a existir.** Eram três; a Issue cobra quatro. Sem ele, contexto
   vira cinza neutro e se perde entre o que está pendente.

6. **Toda pastilha de estado carrega ícone junto do texto.** É o que faz o estado sobreviver a
   daltonismo, a captura em tons de cinza e a impressão — e a §04 mostra as quatro em cinza para
   provar que a afirmação é verificável, não retórica.

7. **Raio vira política de três valores com dono**, e a escala de espaçamento é **fixada sem ser
   redefinida**: redefinir a base de 4 px do Tailwind deslocaria todo utilitário já escrito na
   tela, que é redesenho disfarçado de token.

8. **O foco é desenhado.** Anel de 2 px na cor da marca com 2 px de afastamento; no campo, borda
   `brand-500` mais halo `brand-100`. E nunca `outline: none` cru — no Tailwind v4 ele grava
   `--tw-outline-style: none` no elemento e faz toda regra de foco escrita depois resolver para
   nada, em silêncio.

9. **`done` é cinza na escada de aceite.** Quem o declara é o lifecycle de Delivery, não o cliente.
   Dar a ele a cor de "concluído" faria a tela sugerir que o aceite do cliente encerra a entrega, e
   a ADR 0067 diz exatamente o contrário.

10. **A cópia de erro passa a mandar falar com o *time da Biahflow***, e a de 404 continua sem
    distinguir "não existe" de "existe e não é seu" — essa indistinção é o produto da regra, não
    um descuido de texto.

11. **O produto se apresenta pelo nome, sem aposto.** `Portal do Cliente` sai do `<title>`, do
    cartão de compartilhamento e do rodapé do painel de autenticação. Um nome que precisa de
    legenda ao lado é um nome que ainda não está confiando em si — e o aposto era herança do
    tempo em que "portal" era o produto. O `<title>` passa a ser `One`.

## Open questions

Tudo abaixo **continua sendo decisão em aberto depois desta aprovação**, e não pode ser resolvido
por um agente durante a implementação.

*Fechadas no gate, e registradas para não serem reabertas por leitura:* a direção de marca
(wordmark, sem selo); o descender em inglês; o símbolo do `favicon`; o remetente
`Biahflow <one@biahflow.ai>` com os e-mails semeados locais em `@biahflow.ai`; e o descritor, que
**sai** — o produto se apresenta como `One`, sem aposto.

- **O descender em inglês dentro de um produto em PT-BR.** `by Biahflow` é decisão tomada, não
  descuido: ele pertence à marca, e marca não se traduz. A cópia do produto continua toda em
  PT-BR. Se um dia incomodar, é revisão nova — a implementação não a resolve por conta própria.
- **O domínio real de envio em produção.** `one@biahflow.ai` está aprovado como o valor do
  repositório; publicar dele é decisão de operação (SPF, DKIM), não de design.
- **Tipografia de marca.** O wordmark usa Inter, a fonte do produto. Uma fonte de display própria
  seria decisão nova e não está proposta.
- **Tema escuro.** Não proposto.
- **Qualquer estado de aceite fora da superfície reservada da §10** — aba, contador no nav, aviso
  no sino. Não desenhados.

## Notes for the implementer

**O que é intencional e precisa sobreviver.** Os valores exatos de token da tabela de procedência.
A política de raio. O ícone **junto** do texto em toda pastilha de estado. O anel de foco em ambos
os formatos (botão e campo). O descender `by Biahflow` andando com o wordmark, inclusive nas
reduções. O ponto do wordmark em `brand-500` no claro e `brand-200` no escuro. E o tile **só** nos
três lugares nomeados — se ele aparecer na sidebar, a implementação divergiu do que foi aprovado. E a hachura do reservado existindo **só** no artefato: no produto, o que é reservado
simplesmente não é renderizado.

**O que é ilustrativo e não é especificação.** Todo dado de exemplo: "Marina Farias", "Acme
Brasil", "Automação Financeira", `+142%`, `328h`, `68%`, "18 set", "Plano de implantação v3.pdf",
os avatares e as contagens. A tela real só desenha o que a API entregou — não há caminho na tela
que fabrique resposta, data ou citação, e há guarda que reprova a volta disso.

**O que o artefato não consegue mostrar e a implementação deve garantir.** Ordem de foco e
navegação por teclado. Comportamento de leitor de tela — `aria-current="page"` no item ativo do
nav, `role="alert"` no erro, `aria-label` no sino com a contagem de não lidas. Movimento: nada
nesta fatia anima, e `prefers-reduced-motion` continua respeitado. Internacionalização: a cópia é
PT-BR e não há segunda língua.

**Duas armadilhas do repositório que o desenho encosta.**
`components/` entra no corpus varrido por `tests/rendered-html.test.mjs`, então todo `<button>` de
primitiva precisa de `onClick` ou `type="submit"` — a vitrine demonstra estado mexendo em estado,
não desenhando botão morto. E `components/` **não** entra no corpus de `tests/api-contract.test.mjs`,
que só varre `app/`: mapeamento de JSON da API não pode migrar para lá, ou a guarda de consumo cai.
Primitiva é apresentação; o mapeamento fica onde está.
