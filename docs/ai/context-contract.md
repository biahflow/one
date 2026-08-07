# Contrato de contexto

O recuperador recebe `organization_id`, `project_id`, identidade e pergunta. Só retorna chunks cujo
tenant e projeto sejam compatíveis. Falha de recuperação não permite resposta factual sem fonte.

## O que uma citação carrega

**Fonte e localização, sempre. Data, quando a fonte data o fato** (ADR 0038).

| Evidência | Data | De onde |
|---|---|---|
| Trecho de documento | sim | `source_updated_at` — o `modifiedTime` do Drive ou a data do envio; na falta dele, `indexed_at` |
| Pendência | sim | `created_at`, que o `sync_snapshot` carimba com o `opened_at` do Biahflow |
| Marco | **não** | — |
| Status do projeto | **não** por citação; a frase da evidência declara "estado sincronizado em DD/MM" | `project.updated_at` |

> *Corrigido em 07/08/2026 (ADR 0038). Este documento dizia "toda citação aponta para fonte,
> localização e **data**" desde a Fase 3, e nenhuma citação tinha data. A tabela acima é a fatia que
> cumpriu a promessa **e** o limite que a medição impôs a ela: o marco não pode declarar data
> honestamente porque a linha dele é apagada e recriada a cada sincronização, de modo que o
> `created_at` diz quando o portal copiou e não quando o fato aconteceu. Carimbá-lo assim faria o
> cliente ler a data da cópia como data do marco — falsa precisão, que é o que `results.py` recusa
> quando falta premissa. Quem não tem data não ganha nenhuma.*

## Por que a data importa

O ponteiro da citação (ADR 0017) abre o documento **de hoje**, e o sync do Drive reindexa a mesma
linha quando o arquivo muda (`modifiedTime`, depois a SHA-256). O turno guardado congela o rótulo
como foi exibido, mas não o conteúdo por trás dele: sem a data, uma resposta de março e o arquivo
de agosto usam rótulo idêntico, e quem clicasse para conferir veria outra coisa sem saber.

A data não resolve o descompasso — ela o torna **perceptível**, que é o que permite alguém
perguntar. Comparar o `content_hash` gravado no turno com o atual para dizer "este documento mudou
desde aquela resposta" é o passo seguinte, e ainda não existe.

## Onde a data aparece

- No **rótulo**: `Documento: Contrato — página 3 (12/03/2026)`. É a citação como o cliente a vê, e
  é o que o histórico remonta das partes gravadas.
- No **campo `dated_at`** de `CitationOut` (ISO), para a tela poder tratá-la como data — é dele que
  sai o "Versão da fonte em 12 de março de 2026" que explica o parêntese.
- No **prompt**, junto do `id` da evidência, para o modelo poder preferir a versão recente quando
  duas se contradisserem. O modelo continua sem ver `source` e `location`: o rótulo é montado pelo
  portal a partir dos ids.
