# Design Approval Package — F-027 · O aceite que a tela só desenhou

Classification: INTERFACE_CHANGE (superfície de uma `FEATURE_CHANGE`)
Revision: 1
Status: Approved
Date: 2026-08-26
Produced by: Claude Opus 4.8 (1M context), sob a Engineering OS

> Governado por `docs/engineering-os/workflows/design-approval.md`. Evidência para gate humano.
> Não é implementação. Um agente produz e revisa; **não aprova**.

## O que este pacote decide

A F-025 §10 **já desenhou** esta superfície e a aprovou como **reservada** — o card de revisão, os
cinco rótulos de aceite, os controles Aprovar / Pedir ajuste — com a condição escrita de que ela só
seria renderizada "quando existir contrato de projeção com `approvals` chegando de verdade e evento
`client.accepted` de volta". Este pacote **remove a reserva**: a superfície passa a ser renderizada,
os controles passam a agir, e o desenho ganha o que um elemento reservado não tinha — **o histórico
imutável**, a **supersessão explícita**, e os estados de vazio/erro/não autorizado do fluxo real.

O que está em aberto para o gate, portanto, **não** é o visual do card (aprovado na F-025), e sim:
o comportamento do histórico, como uma segunda decisão se mostra sem apagar a primeira, como o
aceite de negócio fica **visivelmente distinto** do merge de engenharia, e a cópia dos controles.

## Approval record

| Campo | Valor |
| --- | --- |
| What was approved | **visual e cópia** (as *Open questions* seguem em aberto — a aprovação não as resolve) |
| Approved by | Daniel Campos |
| Date | 26/08/2026 |
| Revision approved | **1** |
| Explicitly **not** approved | `superseded`/`cancelled` como rótulos visuais (não desenhados aqui — exigem revisão própria) · qualquer superfície de administração do aceite pelo time · assinatura eletrônica · exibição de estado de PR/CI ao cliente · tema escuro |

Aprovação de visual não é de cópia; aprovação desta revisão não é de uma posterior.

## Artifact

| File | O que é |
| --- | --- |
| `design/one-acceptance.html` | Renderização auto-contida da superfície de aceite **viva**: card de revisão, os cinco rótulos, os controles ativos, o histórico imutável com supersessão, e os estados vazio/erro/não autorizado. Abre com duplo clique, sem build/toolchain/rede. |
| `../F-025-.../design/one-dap-r4.html` (§`#review`) | **A origem aprovada** do card e dos rótulos (reservado). Este pacote o torna real; não muda seus valores. |

**Capturas.** Pacote *Awaiting approval*; capturas congeladas são passo determinístico no gate
(Chromium headless, 1280 px desktop e 390×844 mobile), sobre `design/one-acceptance.html`. Incluem
obrigatoriamente: sucesso (aprovar), sucesso (pedir ajuste), **histórico com duas decisões**, vazio
("nada aguardando sua revisão"), erro (serviço indisponível), não autorizado (404).

## Surfaces and states included

| Superfície | Estado | No pacote |
| --- | --- | --- |
| Lista de entregáveis a revisar | sucesso (há itens) | sim |
| Lista de entregáveis a revisar | vazio ("nada aguardando revisão") | sim |
| Card de revisão de um entregável | `ready_for_acceptance` / `client_review` | sim |
| Card de revisão — contexto/evidência | links de documento/citação já autorizados | sim |
| Controles | **Aprovar** (comentário opcional) / **Pedir ajuste** (comentário esperado) | sim — repouso, hover, foco de teclado, desabilitado (enviando) |
| Confirmação pós-decisão | "Enviado ao time da Biahflow" | sim |
| Histórico imutável | uma decisão · duas decisões (supersessão explícita) | sim |
| Escada de aceite | os cinco rótulos, `done` em cinza | sim |
| Distinção merge≠aceite | marcador de "entrega de engenharia" separado do "seu aceite" | sim |
| Superfície | carregando | sim |
| Superfície | erro (serviço indisponível) | sim |
| Superfície | não autorizado (404, nunca 403) | sim |

Deliberadamente **fora**:

| Superfície | Por que |
| --- | --- |
| Administração do aceite pelo time (`/admin`) | O time consome o evento por notificação/Pulse; não há tela de time nesta fatia. |
| Estado bruto de PR/CI/GitHub | ADR 0067 proíbe atravessar a fronteira; o cliente vê "entregue", não o pipeline. |
| `superseded`/`cancelled` como rótulo visual | Não desenhados na §10; entram só com revisão própria. |

## Provenance of visual values

Design system: [`docs/design/one-design-system.md`](../../design/one-design-system.md), lido em
26/08/2026; superfície-origem: F-025 §10 (`../F-025-.../design/one-dap-r4.html`, seção `#review`).
**Se divergir do CSS, o CSS vence.**

Os cinco rótulos e o card são **retidos da F-025** (não novos):

| Valor | Origem | Novo? |
| --- | --- | --- |
| `ready_for_acceptance` → "Pronto para revisão", tom `brand` | F-025 §10 | não |
| `client_review` → "Em revisão", tom `info` | F-025 §10 | não |
| `accepted` → "Aprovado", tom `success` | F-025 §10 | não |
| `changes_requested` → "Ajuste pedido", tom `warning` | F-025 §10 | não |
| `done` → "Concluído pela operação", **cinza** | F-025 §10, decisão 9 | não |
| `StatePill`, `Button`, `.panel`, tokens de cor/raio/foco | F-025 / `one-design-system.md` | não |
| **Layout do histórico imutável** (linha por decisão, ator+data, supersessão riscada) | — | **sim — decidido aqui** |
| **Marcador merge≠aceite** ("entrega de engenharia concluída" ≠ "seu aceite pendente") | — | **sim — decidido aqui** |
| **Cópia dos controles** ("Aprovar entrega" / "Pedir ajuste" / "Enviado ao time da Biahflow") | — | **sim — decidido aqui** |

Nenhum token de cor novo. O único gesto de cor é usar `info` para `client_review` e `success` para
`accepted`, que já são tokens.

## Delivered vs reserved

| Elemento | Esta fatia | Reservado para | Vira real quando |
| --- | --- | --- | --- |
| Card de revisão + cinco rótulos (agora vivos) | entrega | — | — |
| Controles Aprovar / Pedir ajuste (ativos) | entrega | — | — |
| Histórico imutável + supersessão | entrega | — | — |
| Confirmação "Enviado ao time" | entrega | — | — |
| Retorno `client.accepted` ao Pulse | **sem superfície** — é backend | contrato de retorno (ADR da F-027) | quando o emissor outbound existir |
| `superseded`/`cancelled` como rótulo | não desenha | revisão própria | decisão de design nova |

O elemento reservado da F-025 (esta superfície) **deixa de ser reservado**. Não sobra affordance
inerte: todo controle desta fatia age (satisfaz `inertButtons()`).

## Decisions this package carries

1. **A superfície reservada vira real** — a condição escrita na F-025 §10 é satisfeita por esta
   feature, e o desenho passa a ser renderizado com controles que agem.
2. **O histórico é imutável e visível** — cada decisão é uma linha nova; uma segunda decisão
   **acrescenta** e a anterior aparece **superada** (riscada, com rótulo), nunca apagada. É o reflexo
   na tela do `GRANT` só de `INSERT` no banco: "quem escreve não reescreve".
3. **Merge de engenharia e aceite do cliente são visivelmente distintos** — o card separa "entrega de
   engenharia concluída" (fato da operação) do "seu aceite" (decisão do cliente, pendente). Sem essa
   separação a tela sugeriria que uma coisa é a outra, que é o invariante que a fatia inteira nega.
4. **`done` continua cinza** — quem o declara é a operação; o aceite do cliente permite `accepted`,
   não `done` (ADR 0067).
5. **A confirmação diz para onde foi** — "Enviado ao time da Biahflow": a empresa é quem responde,
   não o produto (F-025 decisão 1).

## Open questions

- **Onde a superfície vive:** aba própria "Revisão" no nav, ou dentro do card do entregável na
  jornada? Proponho aba própria (contador de "aguardando você") + atalho a partir do entregável.
  Decisão do gate.
- **Comentário em Aprovar:** opcional (proposto) ou dispensado? Em Pedir ajuste é esperado.
- **Elegibilidade:** o que traz um entregável para `ready_for_acceptance` vem do contrato de projeção
  (F-028 / Biahflow); se F-028 não estiver pronta, usar o estado que o snapshot já traz.
- **`superseded`/`cancelled`** como rótulo visual — fora desta revisão.

## Notes for the implementer

**Intencional e precisa sobreviver.** A imutabilidade visível (nada de editar decisão in-place); a
separação merge≠aceite; `done` cinza; os cinco rótulos exatos e seus tons; o anel de foco da F-025
nos controles; a confirmação nomeando o time.

**Ilustrativo, não especificação.** Nomes, datas, títulos de entregável, comentários de exemplo. A
tela só desenha o que a API entregou — não há caminho que fabrique decisão, data ou citação.

**O que o artefato não mostra e a implementação garante.** Que a segunda decisão **acrescenta** no
banco (`GRANT` só de `INSERT`); 404-nunca-403 no acesso cruzado; a notificação interna **não** chega
ao cliente (guarda de `AUDIENCE`); ordem de foco e teclado; `role="status"` na confirmação; nada
anima e `prefers-reduced-motion` respeitado.

**Armadilha do repositório.** O evento é imutável — não há tela de "editar aceite", e não deveria
haver, porque o `GRANT` recusaria. Um controle de editar seria feature errada, não faltando.
