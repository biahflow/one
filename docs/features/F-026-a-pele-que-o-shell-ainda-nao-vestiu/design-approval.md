# Design Approval Package — F-026 · A pele que o shell ainda não vestiu

Classification: INTERFACE_CHANGE
Revision: 1
Status: Approved
Date: 2026-08-26
Produced by: Claude Opus 4.8 (1M context), sob a Engineering OS

> Governado por `docs/engineering-os/workflows/design-approval.md`. Este artefato é evidência para
> um gate humano. Não é implementação e não deve ser copiado para dentro do código da aplicação.
> Um agente **produz e revisa** o pacote; **não aprova**.

## O que este pacote decide, e o que ele não decide

**Não decide aparência nova.** A aparência-alvo desta fatia é a que a F-025 **já aprovou** (DAP
revisão 4, 25/08/2026, capturas em `../F-025-o-nome-que-a-tela-ainda-nao-sabia/design/captures-r4/`).
Nenhuma cor, raio, sombra, fonte ou espaçamento é introduzido aqui.

**Decide o mapeamento.** O que está em aberto é: **qual utilitário cru do shell vira qual token
semântico**, e **onde as primitivas `StatePill`/`Button` substituem desenho à mão**. Essa é a
substância do gate — sem ela o aprovador julgaria gosto, e não há gosto novo a julgar; há uma
tabela de tradução a conferir. Duas linhas dessa tabela **não são isovalentes** e é nelas que o
contraste melhora — elas são o motivo de o gate existir.

## Approval record

| Campo | Valor |
| --- | --- |
| What was approved | **visual e cópia** |
| Approved by | Daniel Campos |
| Date | 26/08/2026 |
| Revision approved | **1** |
| Explicitly **not** approved | Tema escuro · troca das classes utilitárias de raio (`rounded-2xl/xl/full`) pelos tokens de raio · qualquer valor visual novo · superfícies `/admin/*` · o laço de aceite (F-027) e a projeção de jornada (F-028). *As duas Open questions do pacote foram **resolvidas** no gate — `.nav-item` ativo = `brand-50`, abas longas = nesta fatia; ver §Open questions.* |

Aprovação desta revisão não é aprovação de uma posterior. Aprovação de **visual** não é aprovação
de **cópia** (a única mudança de cópia é "Notificações no portal" → "Notificações no One") — se só
uma for aprovada, diga qual.

## Artifact

| File | O que é |
| --- | --- |
| `design/one-shell-tokens.html` | Renderização auto-contida do **mapeamento**: abre com duplo clique, sem build/toolchain/rede. Mostra cada componente do shell nas duas versões — utilitário cru (antes) e token semântico (depois) — lado a lado, com o hex efetivo de cada um. |
| `../F-025-.../design/captures-r4/` | **A aparência aprovada.** É a isto que "depois" se refere; esta fatia não a altera. |

**Sobre capturas próprias.** Este pacote está *Awaiting approval*; a captura congelada da revisão
aprovada é passo determinístico no momento do gate, como foi na F-025 (cujas capturas foram feitas
com Chromium headless, Playwright 1.62.1, sobre o arquivo da revisão). Comando de captura no
momento da aprovação: renderizar `design/one-shell-tokens.html` a 1280 px, 1,5×, e as superfícies do
shell tokenizado a 1280 px (desktop) e 390×844 (mobile). Como esta fatia **não muda a aparência**
aprovada da F-025, a evidência de igualdade é a comparação com `captures-r4/`, não uma captura nova
de tela nova.

## Surfaces and states included

Toda superfície tocada e cada estado — o que entra e o que fica de fora com o motivo.

| Superfície | Estado | No pacote |
| --- | --- | --- |
| Sidebar (desktop) — `.brand-row`, `.project-switcher`, `.nav-item`, `.profile-card` | repouso, item ativo, hover | sim (mapa §1) |
| Sidebar (mobile, `.sidebar--open`) | aberta sobre backdrop | sim (mapa §1) |
| Topbar — breadcrumb, busca, sino, avatar | repouso | sim (mapa §1) |
| Status-card | sucesso | sim (mapa §2) |
| Grade de métricas (ROI, próxima entrega) | sucesso | sim (mapa §2) |
| Painel de jornada `.journey-*` | fase ativa / bloqueada / concluída | sim (mapa §2) |
| Entrada e fio de pendências `.pending-*` | lista, prioridade | sim (mapa §2) |
| Pastilhas de estado `.state--0..3`, `.health-pill`, `.priority-pill` | as quatro variantes + cinza | sim (mapa §3 — via `StatePill`) |
| Botões `.ai-button`, `.text-button` | repouso, hover, **foco de teclado**, desabilitado | sim (mapa §3 — via `Button`) |
| Vazio / carregando / erro / 404 do shell | todos | sim — **já tokenizados na F-025**, conferidos, não reescritos (`.state-shell`/`.state-card`/`.empty-state`) |

Deliberadamente **fora**, com o motivo:

| Superfície | Por que não está aqui |
| --- | --- |
| Chat e citações | Já consomem os tokens; nada muda de forma nem de cor. |
| `/admin/*` (inclusive `/admin/design`) | Superfície interna; herda tokens; nenhuma decisão nova. |
| Aba Resultados/Documentos/Cronograma/Reuniões/Decisões | Mesma linguagem já provada pelo shell; a mudança de token nelas é o mesmo mapa §1–§3 aplicado, sem decisão visual nova. Se o gate quiser, entram na mesma fatia por herança do mapa. |
| Tema escuro | Não existe e não é proposto. |

## Provenance of visual values

Design system referenciado: [`docs/design/one-design-system.md`](../../design/one-design-system.md),
lido em 26/08/2026; fonte executável `app/globals.css` (`@theme` 5–45). **Se este pacote e o CSS
divergirem, o CSS vence e o pacote está velho.**

**Nenhum valor novo.** Toda linha abaixo cita o token existente. As colunas "antes"/"depois" são o
mapeamento que se está aprovando.

### §1 — Sidebar e topbar

| Onde (seletor / `app/globals.css`) | Antes (cru) | Depois (token) | Isovalente? |
| --- | --- | --- | --- |
| `.sidebar` fundo (`:158`) | `bg-white` | `bg-surface` (`#ffffff`) | sim |
| `.topbar` fundo (`:218`) | `bg-white/85` | `bg-surface/85` | sim |
| `.sidebar-toggle` hover (`:177`) | `hover:bg-slate-100` | `hover:bg-surface-sunken` (`#f8fafc`) | ~ (slate-100 `#f1f5f9` → sunken `#f8fafc`) |
| `.nav-item` texto/hover (`:202`) | `text-slate-500 hover:bg-slate-100` | `text-muted hover:bg-surface-sunken` | **não** — `slate-500`→`muted` é a correção de contraste |
| `.nav-item` ativo (`:206`) | `bg-slate-100` | `bg-brand-50` (item ativo passa a citar a marca) | **não — decisão** |
| `.breadcrumb b` (`:231`) | `text-slate-300` | `text-line`/`text-muted` (separador) | ~ |

### §2 — Status-card, métricas, jornada, pendências

| Onde | Antes | Depois | Isovalente? |
| --- | --- | --- | --- |
| `.status-card` fundo (`:257`) | `bg-white` | `bg-surface` | sim |
| `.progress` trilho (`:267`) | `bg-slate-200/70` | `bg-line` | ~ |
| `.status-meta small` (`:273`) | `text-slate-400` | `text-muted` | **não** — correção de contraste (o pior caso da F-025) |
| `.timeline-dot span` (`:306`) | `bg-white` | `bg-surface` | sim |
| `.timeline-dot--2` (`:312`) | `border-slate-300` | `border-line` | ~ |
| `.pending-avatar` (`:149`) | `bg-amber-100 text-amber-800` | `bg-warning-50 text-warning-600` | **não** — estado semântico |
| `.priority-pill--low` (`:356`) | `bg-slate-100` | `bg-surface-sunken text-muted` | ~ |
| `.file-icon` (`:378`) | `text-slate-400` | `text-muted` | **não** — contraste |
| `.comment-input`/`.filter-chip` fundo (`:343`,`:362`) | `bg-white` | `bg-surface` | sim |

### §3 — Primitivas

| Onde | Antes | Depois | Novo? |
| --- | --- | --- | --- |
| Estado (`.state--0..3`, `.health-pill`, `.priority-pill`) | desenho à mão em `globals.css`, com `.state--2` em `bg-slate-100 text-slate-500` | `<StatePill variant=…>` (`components/one/StatePill.tsx`), ícone **junto** do texto | não — a primitiva existe (F-025 §04); o shell passa a usá-la |
| Notification badge (`:240`) | `bg-rose-500` | `bg-danger-600` | **não** — `rose-500 #f43f5e` → `danger-600 #c0392b` |
| Botões (`.ai-button`, `.text-button`) | `<button className="…">` cru | `<Button variant=…>` (`components/one/Button.tsx`) | não — a primitiva existe (F-025 §05); satisfaz `inertButtons()` por construção |

### As não-isovalências, medidas

As linhas marcadas "**não**" são a razão do gate. São todas **correção de contraste** já medida na
F-025 (WCAG 2.1, AA texto normal 4,5:1) — o shell simplesmente ainda não as recebeu:

| Par | Antes | Depois |
| --- | --- | --- |
| `.status-meta small` / `.file-icon` (`slate-400`) sobre branco | 2,56:1 ✗✗ | `muted` 4,81:1 ✓ |
| `.nav-item` (`slate-500`) sobre branco | 4,60:1 (limítrofe) | `muted` 4,81:1 ✓ |
| `.pending-avatar` (`amber-800` sobre `amber-100`) | não medido no par do token | `warning-600` sobre `warning-50` 4,51:1 ✓ |

`bg-brand-50` no `.nav-item` ativo é a única decisão de **cor** (não só de contraste): o item ativo
passa a citar a marca em vez de um cinza neutro, alinhando o nav ao gesto que o resto do shell já
usa (o roxo é o que distingue esta tela da identidade clay do Pulse). É reversível para
`bg-surface-sunken` se o gate preferir manter neutro — é a pergunta explícita das *Open questions*.

## Delivered vs reserved

| Elemento | Esta fatia | Reservado para | Vira real quando |
| --- | --- | --- | --- |
| Mapeamento utilitário→token no shell | entrega | — | — |
| Adoção de `StatePill`/`Button` no shell | entrega | — | — |
| Cópia "Notificações no One" | entrega | — | — |
| Tokens de raio nas classes utilitárias | **não entrega** | fatia futura | decisão nova de política |
| Superfícies de aceite / projeção | não desenha | F-027 / F-028 | pacotes próprios |

Nada é desenhado como "reservado" no produto: esta fatia não introduz controle novo, só reveste os
existentes. Não há affordance inerte a marcar.

## Decisions this package carries

1. **A pele do shell passa a vir do token, não do utilitário cru** — mesmo pixel onde isovalente,
   pixel com mais contraste onde a F-025 já tinha corrigido e o shell não recebera. É a única forma
   de a correção de contraste da F-025 valer para a tela inteira.
2. **O shell adota as primitivas em vez de redesenhar estado e botão** — `StatePill` e `Button`
   existem em `components/one/` e o shell as ignorava; usá-las é o que impede a linguagem de
   divergir sem nada ficar vermelho, e satisfaz `inertButtons()` por construção.
3. **O item de nav ativo cita a marca (`brand-50`)** — proposta desta fatia, reversível no gate.
4. **Nenhuma classe utilitária de raio muda** — trocar `rounded-2xl` pelos tokens de raio deslocaria
   toda superfície de uma vez e é redesenho disfarçado; a F-025 fixou os tokens como política sem
   substituir as classes, e esta fatia respeita isso.

## Open questions — **resolvidas no gate (26/08/2026, Daniel Campos)**

As três foram decididas no momento da aprovação; ficam registradas para não serem reabertas por
leitura.

- **`.nav-item` ativo: `brand-50` (marca) ou `surface-sunken` (neutro)?** → **`brand-50`**. O item
  ativo cita o roxo da marca (decisão 3, confirmada). É a única cor nova de fato (não de contraste)
  da fatia.
- **As abas longas (Resultados/Documentos/Cronograma/Reuniões/Decisões) entram nesta fatia ou na
  seguinte?** → **nesta fatia**. Herdam o mesmo mapa §1–§3, sem decisão visual nova; estende o
  escopo de aplicação do mapa (T03 do plano), não o conjunto de decisões.
- **A cópia** "Notificações no portal" → "Notificações no One": **aprovada como cópia**.

## Notes for the implementer

**O que é intencional e precisa sobreviver.** O mapa §1–§3 exato. As três não-isovalências são
correção de contraste, não gosto — não "arredonde de volta" para o slate. As primitivas
`StatePill`/`Button` são a fonte; não recrie estado/botão à mão ao lado delas. O anel de foco da
F-025 (2 px na cor da marca, 2 px de afastamento; no campo, borda `brand-500` + halo `brand-100`)
tem de continuar valendo — e **nunca** `outline: none` cru, que no Tailwind v4 grava
`--tw-outline-style: none` e mata toda regra de foco escrita depois, em silêncio.

**O que é ilustrativo e não é especificação.** Todo dado de exemplo na renderização (nomes,
percentuais, datas). A tela real só desenha o que a API entregou.

**O que o artefato não mostra e a implementação garante.** Que nenhum campo consumido mudou
(`tests/api-contract.test.mjs` verde, sem mudança de fixture); ordem de foco e navegação por
teclado; `aria-current="page"` no nav ativo; comportamento de leitor de tela do sino. Movimento:
nada nesta fatia anima, e `prefers-reduced-motion` continua respeitado.

**Uma armadilha do repositório.** `components/` entra no corpus de `tests/rendered-html.test.mjs`
(guarda `inertButtons`), então a primitiva `Button` precisa de `onClick`/`type="submit"` — ela já
tem. E `components/` **não** entra no corpus de `tests/api-contract.test.mjs` (só `app/`): nenhum
mapeamento de JSON de API pode migrar para `components/`, ou a guarda de consumo cai. Primitiva é
apresentação; o mapeamento fica onde está.
