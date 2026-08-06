# ADR 0029 — A prioridade sem produtor, e a guarda de que o contrato é consumido

**Status:** aceita — 06/08/2026
**Contexto:** Fase 2, fechando dois itens abertos. A prioridade das pendências passa a existir de
verdade, as abas longas ganham filtro, e um campo que a API entrega não pode mais sumir no BFF.

## Contexto

`ROADMAP.md` diz que *"Prioridade, comentários e vínculo a conversas seguem pendentes"*. A
prioridade não estava pendente — estava **quatro vezes presente e nenhuma vez viva**:

| Camada | Estado antes desta fatia |
|---|---|
| `models/project.py:173` | coluna `priority`, enum `PendingPriority` (`low`/`medium`/`high`) |
| `schemas.py` | `PendingOut.priority`, no OpenAPI publicado |
| `integrations/biahflow.py` | projetada no payload do dashboard |
| `app/page.tsx:78` | **declarada** no tipo `ApiPending` |
| `app/page.tsx` (mapeamento) | **omitida** |
| `app/DashboardClient.tsx` | a palavra não aparecia |

Na única aba onde se espera que o cliente **aja**, toda pendência aparecia igual.

### E a causa era mais funda do que o descarte

Ao escrever o e2e, o banco mostrou as oito pendências semeadas todas em `medium`. O motivo:
**`sync_snapshot` nunca lia `priority`.** O `PendingItem(...)` construía título, responsável,
estado, origem, `external_ref` e datas — e não a prioridade. O snapshot do Biahflow sequer
carregava o campo, e nenhum documento o mencionava.

Então havia coluna, enum, campo de contrato e chave de payload, **e nenhum produtor**. Uma
coluna com contrato e sem produtor é uma constante disfarçada de dado — e renderizar o selo sem
consertar isso teria entregue código que mostra sempre a mesma coisa, que é a definição de casca
de demonstração com backend.

### Por que nada disso ficou vermelho

`tests/api-contract.test.mjs` confere que a **fixture** casa com o contrato. Nenhuma asserção
olhava o outro lado: se a API entrega um campo e o mapeamento do BFF não o lê, o dado atravessa
a rede, é tipado, e é jogado fora com a rota respondendo 200.

É exatamente o defeito que a ADR 0020 recusou acrescentar do lado Python ao escolher
`extra="forbid"` — *"um dado sumindo da tela com a rota respondendo 200"* —, um passo adiante no
caminho e sem guarda nenhuma.

## Decisão

### 1. O snapshot passa a carregar a prioridade, e ela é opcional

`pendencia.priority` (`low`/`medium`/`high`) entra no contrato do snapshot, com
`PENDING_PRIORITY_MAP` ao lado do `PENDING_STATE_MAP` que já existia. **Opcional, com default
`medium`**: o portal não pode exigir que a outra ponta já envie um campo novo, e a ausência tem
de continuar significando o padrão em vez de quebrar o sync.

Quem origina é o Biahflow e quem espelha é o portal — a ADR 0006 aplicada como sempre. Um
`PATCH` de prioridade no portal seria originar status.

O seed ganhou uma mistura (uma alta, uma baixa, o resto no default) em **duas linhas** do
snapshot versionado. Sem ela, o selo, a ordenação e o filtro seriam invisíveis no
`passeio-local.md` e no e2e — e uma funcionalidade que só se prova em teste unitário é meia
funcionalidade.

### 2. A prioridade aparece e ordena, e só alta e baixa têm selo

`medium` é o default da coluna: marcar toda linha é não marcar nenhuma.

**Abertas ordenam por prioridade.** A comparação só olha a prioridade, e é de propósito: o
`sort` é estável e a API já devolve por `created_at desc`, então dentro de cada faixa a mais
recente continua em cima sem que o cliente repita o critério do servidor.

Isso muda o corte de quatro itens da Visão geral, que mostrava as quatro **mais recentes**. Um
resumo que corta por data é as primeiras linhas de um `ORDER BY created_at` com nome de resumo —
foi o que escondeu a pendência semeada quando o e2e rodou num banco usado.

### 3. Filtros client-side, e a razão de não serem do servidor

Um componente (`FilterChips`) para as quatro abas longas. O dashboard já trouxe a lista inteira:
perguntar ao servidor exigiria parâmetro, `response_model` novo, esquema regenerado e caso
negativo de permissão (regra 6 do `AGENTS.md`) para responder o que o navegador tem em mãos. No
dia em que a lista não couber numa resposta, a decisão muda — e aí é paginação, não filtro.

Cada chip mostra **a contagem**, que é o que separa um filtro útil de um enfeite: sem o número,
escolher é adivinhar. "Todas" é sempre a primeira opção, porque um filtro sem caminho de volta
esconde dado e parece lista vazia.

### 4. A guarda: o contrato tem de ser consumido, não só casado

Para cada esquema de item do dashboard, **toda propriedade declarada tem de ser desreferenciada
no mapeamento do BFF**. Oito esquemas entraram; na primeira execução a guarda acusou **um campo
só**, `PendingOut.priority`, e ele virou mapeamento em vez de exceção.

A asserção é sobre `.<chave>` e não sobre a chave solta, e essa distinção é o teste inteiro:
`priority` **já aparecia** em `page.tsx`, na declaração de tipo. Uma guarda sobre o nome nasceria
verde em cima do defeito que ela existe para pegar.

A allowlist existe e está **vazia**. Um campo que a tela legitimamente não usa é uma pergunta
para o contrato, não para o BFF.

### 5. `PendingOut.priority` deixa de ser `str`

É o único campo enumerado da resposta, e a exceção foi medida: a fixture do teste de SSR dizia
`"normal"` — valor que `PendingPriority` não tem — e passava, porque `str` aceita qualquer coisa.
Declarar os três valores não muda um byte (eles já saem de `.value`) e põe o contrato a serviço
de quem o consome. Regenerado o esquema, a fixture foi recusada na hora.

## Consequências

- **A aba onde o cliente decide o que fazer primeiro passa a dizer o que é primeiro.**
- **A guarda nasceu vermelha** apontando `.priority`, e a asserção de ordenação também: com o
  comparador neutralizado, o teste de SSR reprova. É o argumento da ADR 0020 contra guarda que
  nasce verde, aplicado às duas.
- **Armadilha medida, e ela vale para qualquer asserção de ordem futura:** o Next serializa as
  props do componente cliente em `<script>self.__next_f.push(...)` no mesmo documento, então
  **toda string da lista aparece duas vezes** — e a cópia do payload está na ordem em que a API
  entregou, não na que a tela desenhou. Um `html.indexOf(...)` cai na cópia errada e passa a
  medir o `ORDER BY` do Postgres achando que mede a tela. Daí `renderedMarkup()`, que remove os
  `<script>` antes de comparar posições. Asserções de *presença* seguem usando o HTML inteiro.
- **Sem migração e sem rota nova.** O esquema publicado mudou em cinco linhas, só para ganhar o
  `enum`.
- **Os filtros são cobertos de graça pela ADR 0026:** são `<button>` com `onClick`, e a guarda de
  affordance já os policia.
- **O que continua aberto, e agora a linha do roadmap diz só isso:** comentários em pendência
  (dado originado no portal, contra a ADR 0006/0008) e vínculo a conversas (`pending_item` não
  tem coluna de conversa; pediria migração).
- **O Biahflow ainda não envia o campo.** Enquanto não enviar, tudo o que vem de lá é `medium` e
  nada quebra — mas a demonstração local mostra a mistura porque o seed a traz. Isso está
  declarado aqui para não ser lido como "já funciona em produção".

## Alternativas recusadas

**Tirar `priority` do contrato até haver produtor.** Coerente com a mensagem da própria guarda, e
foi considerado a sério. Custaria desfazer trabalho no dia em que o Biahflow enviar, e trocaria
um campo inerte por uma lacuna — sendo que o campo já tinha coluna, enum e migração aplicada.

**Deixar o cliente definir a prioridade no portal.** Originar status, contra a ADR 0006/0008, e
pela mesma razão que o CRUD interno saiu do roadmap na Fase 2.

**Filtro no servidor.** Ver decisão 3.

**Selo em toda linha, inclusive `medium`.** Três cores em oito linhas é ruído com aparência de
informação; o olho procura a exceção, e "médio" é a regra.

**Ordenar também por idade explicitamente no cliente.** O `sort` estável já entrega isso a partir
da ordem da API. Repetir o critério aqui criaria um segundo lugar para ele divergir — e o dia em
que o servidor mudar o `ORDER BY`, a tela discordaria dele em silêncio.
