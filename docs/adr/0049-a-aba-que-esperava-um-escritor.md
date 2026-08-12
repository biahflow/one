# ADR 0049 — A aba que esperava um escritor

**Status:** aceito
**Data:** 12/08/2026
**Fecha:** a exceção que a ADR 0024 deixou escrita na regra 1 da busca
**Relacionadas:** ADR 0006/0008 (o portal não origina status), ADR 0024 (busca), ADR 0033 (painel
sobre campo sem escritor), FDD 032 e ADR 0027 do `biahflow-portal`

## Contexto

`Decision` tem modelo desde a Fase 1, com RLS e `GRANT SELECT` desde a migração `0007`. Nunca teve
uma linha. `DecisionRepository` tem corpo vazio e nenhum chamador, `build_dashboard` não a projeta,
e a busca a mantinha de fora com a razão escrita na regra 1 do módulo:

> *"`Decision` tem modelo desde a Fase 1 e não é projetada em `build_dashboard`: um hit dela levaria
> a lugar nenhum. **Quando existir aba de decisões, entra aqui junto.**"*

Era a única exceção escrita àquela regra, e ela sobreviveu a três fases.

**Construir só a aba entregaria uma tela que nunca sai de "Nenhuma decisão registrada ainda".** Este
repositório catalogou esse defeito três vezes — a ADR 0033 achou um painel "O que os clientes
disseram" sobre um campo sem escritor — e escreveu a regra no `ROADMAP.md`: **"painel só nasce
depois do escritor"**.

E o escritor não podia nascer aqui: o portal não origina status (ADR 0006/0008), e o `roadmap.md`
do Biahflow tem o CRUD interno de decisões **riscado**, com essa razão. Havia ainda uma terceira
origem possível, e ela está morta deste lado: o `ROADMAP.md:110` diz que "as decisões extraídas
dependem da ingestão de texto da Fase 4", e o docstring de `Meeting` diz que "decisões extraídas
penduram nela" — mas o mesmo arquivo declara que **o texto da transcrição não atravessa o
snapshot**, e medido: `transcript_text` não tem escritor nenhum, aparece só no modelo e na migração
`0002`. O portal nunca teve o texto.

Por isso esta fatia é a **segunda** de duas. O escritor saiu antes, no `biahflow-portal` (FDD 032),
onde a transcrição existe.

## Decisão

**A aba viaja dentro do dashboard, e não numa rota nova.** É o molde de Reuniões, Documentos,
Cronograma e Resultados — read-only, espelhado do snapshot, sem escrita do cliente. Pendências
carrega quatro camadas a mais (origem, comentários, link para o turno e escrita por `POST`) e seria
o molde errado. Sem rota nova, não há caso de 404 novo a provar.

**`rationale` é o campo que justifica a aba existir.** Sem o porquê, uma decisão é um título — e o
porquê é justamente o que o cliente não consegue reconstituir sozinho meses depois. Do outro lado
isso exigiu emenda na ADR 0003 de lá, porque o snapshot **corta** o `description` da pendência de
propósito: levar texto ao cliente é decisão, não detalhe.

**A proveniência chega como pk e é projetada como rótulo.** O snapshot manda `meeting_id` (a pk do
Biahflow); o dashboard devolve `meeting_title`. O uuid da reunião no portal **muda a cada sync** —
`Meeting` não guarda id externo e é recriada por inteiro —, então ele não serviria nem de link nem
de chave estável para a tela.

**E é isso que impõe a substituição integral das decisões, com uma ordem que é dependência.** O
`delete(Decision)` vai **antes** do `delete(Meeting)`, e o mapa `{id do Biahflow: uuid}` é montado
com um `flush()` depois do laço de reuniões — o mesmo movimento que o laço de fases já fazia
("precisamos do `phase.id` para os entregáveis"). Filtrar aquele `DELETE` por origem, como
`PendingItem` e `Document` são filtrados, quebraria a proveniência de todas as decisões antigas na
passagem seguinte: o FK é `ON DELETE SET NULL`, então o sintoma seria `meeting_id` virando nulo
**sem erro, sem log e sem exceção**. O comentário está lá para a próxima pessoa que copiar o padrão
da pendência, e o teste afirma sobre a proveniência **depois de dois syncs** — depois de um, o
desenho errado passa.

## Consequências

- **A regra 1 da busca deixou de ter exceção.** Decisão entra como sexta fonte, casando `title`
  **e** `rationale` — quem procura uma decisão raramente lembra o título dela; lembra do assunto que
  a motivou. O teste que afirmava a ausência (`test_a_decision_is_not_reachable_because_no_tab_shows_one`)
  foi reescrito, como a ADR 0024 previa.
- **Seis documentos carregavam a promessa e foram retificados**, não apagados: `search.py`, a ADR
  0024, as FDD 018 e 003, o `CLAUDE.md` e o `ROADMAP.md`.
- **`build_dashboard` faz `outerjoin` e não carga preguiçosa.** Um relationship com `lazy` daria
  N+1 num laço que já é do dashboard.
- **O seed ganhou duas decisões**, e uma delas **sem reunião** de propósito: é o caso real de uma
  reunião arquivada do outro lado, e é o que faz o `meeting_title` nulo ser exercitado pelo e2e em
  vez de ser um ramo que ninguém percorre.
- **Fica aberto: `Meeting` continua sem id externo.** Dar-lhe `external_ref` e trocar *replace* por
  *upsert* — o padrão que `PendingItem` já tem — estabilizaria o uuid entre syncs e tornaria o mapa
  desnecessário. Nada mais aponta para `Meeting` hoje, então o custo não se paga nesta fatia; no dia
  em que algo apontar, é isto que tem de acontecer antes.
- **Fica aberto: a decisão não é citável pelo assistente.** `ai/retrieval.py` não a lê, e o chat
  continua respondendo por documento, pendência e read model. Uma decisão publicada é evidência tão
  boa quanto uma pendência resolvida — e provavelmente melhor —, mas isso muda o recuperador, o que
  a ADR 0021 obriga a fazer com eval e bump de versão de prompt. Não é desta fatia.
