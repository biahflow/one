# FDD — A citação com data

Fase 6, ADR 0038.

## Objetivo e não objetivos

**Objetivo.** Que a citação diga **de quando** é a fonte que a sustenta, para o cliente poder
situar a resposta no tempo e perceber quando o documento por trás de uma resposta antiga já não é
o mesmo. Cumpre a promessa que o `context-contract.md` fazia desde a Fase 3 e nunca teve código.

**Não objetivos.** **Inventar data para quem não tem**: marco e status não ganham data, e o
documento explica por quê. **Detectar que o documento mudou desde a resposta**: exige comparar
`content_hash`, é outra fatia e outra decisão de tela. **Mudar o que a IA responde**: a data entra
no prompt como insumo de desempate e situação temporal, não como instrução nova de comportamento.
**Versionar documento**: o portal continua com uma linha por documento, reindexada no lugar.

## Jornada e interface

O cliente pergunta algo que cai num documento. A resposta cita
**"Documento: Contrato de suporte — página 3 (12/03/2026)"**, e passar o mouse sobre a citação
mostra *"Versão da fonte em 12 de março de 2026"* — porque o parêntese sozinho é ambíguo.

Se a citação vier de um marco ou do status, ela sai como sempre saiu, sem parêntese de data.

Reabrindo um turno antigo pela aba de pendências, a data que aparece é a **que foi exibida na
época**, gravada no turno — não a do documento de hoje.

## Critérios de aceite

| # | Critério |
|---|---|
| 1 | A citação de um trecho de documento traz `(DD/MM/AAAA)` da `source_updated_at` |
| 2 | Sem `source_updated_at`, cai para `indexed_at`; sem os dois, sai sem data |
| 3 | A citação de pendência traz a data de abertura, vinda do `opened_at` do Biahflow |
| 4 | A citação de **marco** não traz data nenhuma |
| 5 | A evidência de status declara "Estado sincronizado em DD/MM" no texto |
| 6 | `CitationOut.dated_at` vem em ISO, e `None` quando não há data |
| 7 | O turno guardado grava `dated_at` e o histórico remonta o rótulo com ela |
| 8 | Turno antigo, sem o campo, remonta o rótulo sem data — o que ele mostrou |
| 9 | A data entra na linha da evidência enviada ao modelo |
| 10 | `PROMPT_VERSION` mudou e está gravada no registro |
| 11 | O digest da moldura cobre a linha **com** e **sem** data |
| 12 | A tela consome `dated_at` como data, e não por cirurgia de string no rótulo |

## Telemetria

Nenhum evento novo. A data é um campo de resposta, não um acontecimento: um evento por citação
datada seria uma linha de log por resposta, e o `alerts.md` não teria o que prometer sobre ela.

## Testes

| Teste | O que prova |
|---|---|
| `test_eval_a_document_citation_names_the_date_of_the_source` | Critérios 1 e 6 |
| `test_eval_a_milestone_citation_invents_no_date` | Critério 4 — o limite que a medição impôs |
| `test_eval_a_document_excerpt_is_cited_with_the_page_it_came_from` | Que o rótulo sem data não mudou |
| `test_prompt_version.py` | Critérios 10 e 11 |
| `test_openapi_contract.py` | Critério 6, e o contrato regerado |
| `npm run test:contract` | Critério 12 — reprova sem consumidor, medido |
| `rendered-html.test.mjs` | Critério 12, na forma do controle |

## Casos de eval de IA

Dois casos novos em `docs/ai/eval-dataset.md`, na tabela da Fase 4. Rodam contra o respondedor
offline como os demais; os adversariais que exercitam o `AnthropicResponder` real (com o cliente
injetado, sem chave e sem custo) continuam cobrindo as invariantes de citação e injeção — e o
prompt novo passa por eles sem alteração.

## Riscos

**Mudança de prompt é mudança de comportamento.** A versão nova torna isso auditável, mas nenhuma
eval do conjunto mede *qualidade* de resposta — só invariantes. É o limite conhecido.

**A data aparece duas vezes na resposta** (dentro de `label` e em `dated_at`). Aceito: o rótulo é o
registro do que foi exibido e precisa bastar sozinho; o campo é para a tela poder formatá-la.

**O parêntese pode ser lido como "data do documento" e não "da versão".** O tooltip é o que
desambigua, e ele depende de mouse — em toque não aparece. Se virar dúvida real, o passo é escrever
por extenso no rótulo.
