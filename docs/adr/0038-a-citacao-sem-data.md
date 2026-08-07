# ADR 0038 — A citação sem data

**Status:** aceito
**Data:** 07/08/2026
**Fase:** 6

## Contexto

`docs/ai/context-contract.md` tinha **três linhas**, nunca havia sido alvo de fatia nenhuma, e
prometia na segunda frase: *"Toda citação aponta para fonte, localização e **data**."*

A data nunca existiu. `Evidence.citation` era `f"{source} — {location}"` e `CitationOut` tinha
`label` e `document_id`. Valia para as quatro espécies de evidência. Nona repetição do padrão das
ADRs 0024/0026/0027/0033/0034/0035/0036/0037.

**A evidência já estava no banco, sem consumidor para isto**: `Document.source_updated_at` (o
`modifiedTime` do Drive), `Document.indexed_at`, e o `PendingItem.created_at` que o `sync_snapshot`
carimba com o `opened_at` do Biahflow em vez de deixar com a hora da cópia.

**A ponta afiada é o turno guardado.** O `drive_sync` reindexa a **mesma linha** quando o
`modifiedTime` ou a SHA mudam, enquanto `conversation_message.citations` congela o rótulo como foi
exibido. A citação clicável que a ADR 0017 criou *justamente para o cliente conferir a fonte* abre,
meses depois, uma versão diferente daquela em que a resposta se apoiou — mesmo rótulo, nada
dizendo que mudou.

## Decisão

### Data por evidência só quando a fonte data o fato

`Evidence.dated_at` é preenchido pelo documento e pela pendência. Marco e status ficam `None`, e a
medição é o motivo: **a linha do marco é apagada e recriada a cada sincronização**, então o
`created_at` dela diz quando o portal copiou e não quando o fato aconteceu. Carimbar isso como data
da evidência faria o cliente ler a data da cópia como data do marco — falsa precisão, que é o que
`results.py` recusa quando falta premissa. Quem não tem data não ganha nenhuma, e o rótulo sai byte
a byte como saía antes.

O status declara a sincronização **no texto da própria evidência** ("Estado sincronizado em
DD/MM"), e não no `dated_at`. Assim o parêntese do rótulo continua significando uma coisa só, e o
`Responder` não precisa de parâmetro novo: o "estado em" pertence à evidência que já é a frase que
o portal escreve sobre o projeto inteiro.

### A data entra no prompt

Junto do `id`, na linha da evidência, com uma regra nova no `SYSTEM_PROMPT`: use a data para
preferir a evidência mais recente e para situar o fato, nunca afirme data que não esteja listada, e
ausência de data não é "sem data". O modelo continua **não** vendo `source` nem `location` — o
rótulo é montado pelo portal a partir dos ids.

### Um rótulo, uma implementação

`main._citation_label` passou a **delegar** para `Evidence.citation` em vez de repetir a expressão.
Enquanto o rótulo era `fonte — local`, as duas cópias concordavam por sorte; com a data entrando na
composição elas divergiriam sem nada ficar vermelho — o histórico mostrando um rótulo e o chat
outro para a mesma citação. É o argumento do `textfold.py`, na letra.

## Dois portões que esta fatia mediu, e nos quais nasceu verde

**O digest da moldura não via o ramo novo.** Acrescentada a data à linha da evidência, o
`template_sha256` do `prompt-registry.json` **não mudou**: `_TEMPLATE_SAMPLE` não tinha `dated_at`,
então `_line` produzia exatamente o formato antigo e o portão declarava "nada mudou" sobre uma
moldura que mudara. A cobertura de um portão é a dos ramos que a amostra percorre, e a amostra é
parte do portão. Agora são duas sentinelas, uma datada e uma não.

**O campo chamado `date` era invisível para a guarda de consumo.** A guarda da ADR 0033 casa nome
de campo por substring, e `date` aparece em `new Date`, `dateStyle` e `due_date`: medido, o
`CitationOut` passava verde com o consumidor removido. Renomeado para `dated_at` — o nome que o
campo já tinha por dentro —, a guarda reprova sem consumidor e passa com ele. É o `.priority` da
ADR 0033 outra vez, e a lição é que **nome genérico de campo enfraquece a guarda**.

## Consequências

- `PROMPT_VERSION` foi para `chat-2026-08-07`, com entrada nova no registro append-only. Mudança de
  prompt é mudança de comportamento, e a versão é o que a torna auditável.
- A data viaja **também** dentro de `label`, e é deliberado: o rótulo é o que foi exibido, e
  `sources` (a projeção só-texto) precisa ser completa sozinha. O campo estruturado existe para a
  tela tratá-la como data — é dele que sai o "Versão da fonte em 12 de março de 2026" do tooltip.
- O turno guardado passa a gravar `dated_at`. Turnos antigos não têm o campo, e continuam
  remontando o rótulo sem data — que é exatamente o que eles mostraram.

## O que fica em aberto

**A data torna o descompasso perceptível, não o resolve.** Um turno guardado continua apontando
para o documento de hoje. Dizer "este documento mudou desde aquela resposta" exige comparar o
`content_hash` gravado no turno com o atual, e é fatia própria — inclusive porque exige decidir o
que a tela faz com a divergência.

**Marco continua sem data**, e é a citação mais comum. A saída seria o Biahflow mandar o
`completed_at` do marco no snapshot: mudança do outro lado, fatia própria.
