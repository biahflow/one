# One — sistema de design

Este documento extrai para fora do CSS a linguagem visual que
[`docs/features/F-025-o-nome-que-a-tela-ainda-nao-sabia/design-approval.md`](../features/F-025-o-nome-que-a-tela-ainda-nao-sabia/design-approval.md)
aprovou (revisão 3, 25/08/2026) — a tabela "Provenance of visual values" daquele pacote é a
origem de cada linha abaixo. Antes desta fatia, a linguagem existia só dentro de
`app/globals.css`, sem documento que um pacote seguinte pudesse citar; esta extração é parte do
que foi aprovado, não uma iniciativa paralela.

A fonte executável continua sendo `app/globals.css` — bloco `@theme` e `@layer components`. Se
este documento e o CSS divergirem, **o CSS vence e este documento está desatualizado**.

## Regra de admissão

Um token só entra no `@theme` se algum seletor de `@layer components` (ou um utilitário do
Tailwind) o consumir. A mesma regra que já vale para classes de CSS — "o que ninguém usa não
entra" — vale para token. Não se acrescenta cor, raio ou sombra "para quando alguém precisar".

**A regra tem portão** (F-025 T04, `PLAN_DEVIATION 01`): `tests/rendered-html.test.mjs` deriva
o corpus do próprio bloco `@theme` e exige, de cada token, um consumidor fora dele — `var(--token)`
no CSS ou o utilitário que o Tailwind v4 gera a partir dele (`--color-info-600` →
`text-info-600`, `--radius-card` → `rounded-card`). `@theme` ilegível ou vazio **reprova**, e a
isenção é linha em `TOKEN_WITHOUT_A_CONSUMER` com motivo em prosa e **sem prazo**, no precedente
do `PINNED_BY_EXCEPTION` — quem a vence é a asserção de obsolescência, não o calendário. A frase
acima foi publicada quando sete tokens ainda não tinham consumidor nenhum; regra publicada sem
portão volta a divergir, que é o argumento da ADR 0034.

## Tokens de cor

| Token | Valor | Papel |
| --- | --- | --- |
| `--color-ink` | `#17243a` | texto primário |
| `--color-muted` | `#657389` | texto secundário / rótulo |
| `--color-line` | `#e8edf4` | borda padrão |
| `--color-canvas` | `#f6f8fc` | fundo da página |
| `--color-navy` | `#16233a` | superfícies escuras (topo do painel de autenticação) |
| `--color-brand-50…900` | oito degraus, `#f3f0fd` → `#342478` | a marca do One — o roxo, com procedência declarada (DAP, decisão 3) |
| `--color-success-50` / `--color-success-600` | `#e7f7f0` / `#1a7e5b` | estado de sucesso |
| `--color-warning-50` / `--color-warning-600` | `#fdf3e4` / `#a16118` | estado de atenção |
| `--color-danger-50` / `--color-danger-600` | `#fdecea` / `#c0392b` | estado de falha |
| `--color-info-50` / `--color-info-600` | `#e9f1fd` / `#1d5fb4` | estado informativo — não existia antes desta fatia |
| `--color-accent-green` | `#1c8665` | o verde do gradiente do `body`, que existia como `rgba(33, 161, 121, …)` escrito à mão |
| `--color-focus` | `var(--color-brand-500)` | anel de foco de teclado — existia como literal em `:focus-visible` |
| `--color-surface` | `#ffffff` | superfície de cartão — existia como `bg-white` sem nome |
| `--color-surface-sunken` | `#f8fafc` | superfície rebaixada — existia como `bg-slate-50` sem nome |

`--color-muted`, `--color-success-600` e `--color-warning-600` são os três valores que a medição de
contraste corrigiu nesta fatia (ver abaixo); os demais são retidos do que já existia.

## As medições de contraste

Fórmula de luminância relativa da WCAG 2.1, sobre os hexes exatos, contra o critério **AA para
texto normal (4,5:1)** — não AA-large, porque nada na tela usa texto grande (o corpo secundário é
14 px, a pastilha de estado é 10 px em negrito). Medidas em 25/08/2026, registradas no DAP.

| Par | Antes | Depois |
| --- | --- | --- |
| `muted` sobre branco | 4,36:1 ✗ | 4,81:1 ✓ |
| `muted` sobre `canvas` | 4,10:1 ✗ | 4,52:1 ✓ |
| `.eyebrow` (`slate-400`) sobre branco | 2,56:1 ✗✗ | 4,81:1 ✓ (passa a usar `muted`) |
| `success-600` sobre `success-50` | 3,90:1 ✗ | 4,54:1 ✓ |
| `warning-600` sobre `warning-50` | 3,88:1 ✗ | 4,51:1 ✓ |
| `danger-600` sobre `danger-50` | 4,76:1 ✓ | inalterado |
| `info-600` sobre `info-50` | não existia | 5,51:1 ✓ |
| `brand-700` sobre `brand-50` | 7,52:1 ✓ | inalterado |
| branco sobre `brand-500` | 5,39:1 ✓ | inalterado |
| `brand-200` sobre `brand-900` (ponta escura do gradiente) | 7,71:1 ✓ | inalterado |
| `brand-200` sobre `brand-600` (ponta clara do gradiente) | 4,04:1 — AA-large | inalterado; é onde é usado: rótulo curto de 10,5 px |

O pior caso do produto era o `.eyebrow`: 10 px, caixa alta, `slate-400`, 2,56:1 — reprovava até o
critério de texto grande. É o rótulo acima de todo título de painel, e a correção foi trocar o
literal `text-slate-400` por `text-muted` na regra compartilhada `.eyebrow, .nav-label`.

## Política de raio

Três valores com dono, nunca um quarto informal:

| Token | Valor | Onde se aplica |
| --- | --- | --- |
| `--radius-card` | `1rem` (16px) | cartão — o que hoje é `rounded-2xl` |
| `--radius-control` | `0.75rem` (12px) | controle e botão — o que hoje é `rounded-xl` |
| `--radius-pill` | `9999px` | pastilha — o que hoje é `rounded-full` |

Estes três tokens **não redefinem** `--radius` do Tailwind v4 nem substituem, nesta fatia, as
classes utilitárias já escritas na tela (`rounded-2xl`, `rounded-xl`, `rounded-full`) — eles
existem para fixar a política que essas classes já seguem, e para que uma superfície futura possa
citar `--radius-card`/`--radius-control`/`--radius-pill` em vez de reintroduzir um valor solto.

## Escala de espaçamento

A base de `4px` do `--spacing` do Tailwind v4 é retida, sem redefinição — redefini-la deslocaria
todo utilitário de espaçamento já escrito na tela, que é redesenho disfarçado de token. O que esta
fatia fixa é a lista dos oito degraus efetivamente em uso na linguagem do One:

| Degrau | Valor |
| --- | --- |
| 1 | `4px` |
| 2 | `8px` |
| 3 | `12px` |
| 4 | `16px` |
| 5 | `20px` |
| 6 | `24px` |
| 7 | `36px` |
| 8 | `44px` |

## Sombras

Três sombras em camadas — um contorno de 1px mais uma difusão ampla e suave — já definidas no
`@theme` e retidas sem alteração:

| Token | Papel |
| --- | --- |
| `--shadow-card` | repouso: painel, cartão de estado, cartão de métrica |
| `--shadow-raised` | elevação intermediária |
| `--shadow-pop` | elevação máxima: popover, menu flutuante |

## Nenhum hex de marca escrito à mão

As quatro ocorrências de `rgba(110, 86, 207, …)` (a cor de `brand-500`) e `rgba(33, 161, 121, …)`
(a cor que nomeou `--color-accent-green`) que existiam em `app/globals.css` — os dois gradientes
do `body`, a sombra de `.brand-mark` e a de `.ai-button` — passaram a derivar de token, por
`color-mix(in srgb, var(--color-…) N%, transparent)`. `color-mix` exige o espaço de cor declarado
(`in srgb`); sem ele o navegador ignora a declaração e o efeito some sem erro.

## O que fica de fora, deliberadamente

- Tema escuro — não existe neste produto e não foi proposto no DAP.
- Redefinição da base de `--spacing` — ver acima.
- Qualquer token sem consumidor no CSS atual.
