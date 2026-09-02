# Kit de marca do One

Os arquivos que uma peça montada **fora** deste repositório precisa: slide de kickoff, cabeçalho
de relatório, assinatura de e-mail, peça institucional da casa que cite o produto. A página
navegável do kit é o artifact **Kit de Marca One** (v1, 29/08/2026), derivado do mesmo material.

**A fonte executável continua sendo `app/globals.css`** — bloco `@theme` e `@layer components`.
Se um arquivo daqui divergir do CSS, **o CSS vence e o arquivo daqui está desatualizado**. A
norma em prosa é [`../one-design-system.md`](../one-design-system.md); este diretório não a
reformula, só empacota o que sai dela.

| Arquivo | O que é | Onde usar |
| --- | --- | --- |
| `one-mark.svg` | Tile roxo, geometria idêntica à de `public/favicon.svg` | Fundo claro, onde texto não cabe |
| `one-mark-inverse.svg` | Tile branco com a inicial em `brand-500` | Navy e `brand-900` — o tile roxo some ali (1,4:1) |
| `one-wordmark.svg` | `One.` + `by Biahflow`, nas medidas do `Brand.tsx` | Fundo claro |
| `one-wordmark-inverse.svg` | O mesmo, para superfície escura | Gradiente da autenticação, peça preta da casa |
| `one-tokens.css` | Cópia legível do `@theme` | Peça em HTML fora do produto |
| `one-tokens.json` | Os mesmos valores como dado, com os contrastes medidos | Ferramenta, script, deck gerado |

## Duas coisas que este diretório declara em vez de esconder

**O wordmark não está vetorizado.** Os dois `one-wordmark*.svg` usam `<text>` com Inter. Quem
exportar para impressão precisa da fonte instalada, ou converte em curva na hora. Vetorizar aqui
criaria uma segunda fonte de verdade para o nome — exatamente o que a F-025 T02 fechou ao deixar
o wordmark vivendo em `components/one/Brand.tsx` e em nenhum outro lugar.

**Não existe lockup.** Tile e wordmark nunca aparecem juntos: dentro do produto vai só o
wordmark; onde texto não cabe (aba, atalho de tela, avatar, cartão de compartilhamento) vai só o
tile. Isso é decisão do DAP r3, §01, item 2 — não é lacuna do kit.

## Fronteira com a marca da casa

O roxo é do One, o clay é do Pulse, o âmbar e o turquesa são da Biahflow. Nenhum atravessa: em
peça institucional e em rede social quem assina é a casa, e o One entra como produto citado. A
norma da casa está em `biahflow-os/00-company/brand.md`.
