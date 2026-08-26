# ADR 0074 — Camada global vendorizada e pinada por tag

**Status:** aceito
**Data:** 26/08/2026
**Fase:** 5

## Contexto

`docs/project-context.md` abria declarando a ordem de regras — *Engineering OS global →
`AGENTS.md` → contrato da tarefa* — e, na linha seguinte, dizia onde a camada global estava:
`/Users/danielcampos/workspace/engineeringOS/`. Um caminho absoluto da máquina de uma pessoa,
num arquivo versionado de um repositório que tem remote.

Essa referência nunca resolveu para o CI, para um colaborador novo ou para um agente em nuvem.
Resolvia para exatamente um executor, e por isso a falha ficou invisível: em 25/08/2026 o
checkout mudou para `~/workspace/daniel/engineeringOS` e o caminho morreu **para todos**, sem
erro. Os bootstraps renderizados nas ferramentas apontavam para o mesmo lugar e passaram a
importar treze arquivos inexistentes; um import que não resolve não é um erro, é uma ausência.
Durante esse período nenhuma sessão carregou os guardrails globais, e nada avisou.

O repositório se declarava `ENGINEERING_OS_COMPLIANT` desde 17/08/2026 o tempo inteiro. A
declaração era anterior à exigência de alcançabilidade que a camada global passou a fazer
(`workflows/project-adoption.md`, "Distribution and pinning"), e contra o padrão vigente ela
não se sustentava: *"a textual mention of a global document that no link can reach is dead
text, not a reference"*.

Era o mesmo defeito da regra 6 (ADR 0035) e do `.priority` (ADR 0033) noutra superfície — a
citação que nenhum portão conferia, porque não apontava para lugar nenhum. As referências à
camada global eram as únicas do repositório fora do alcance de qualquer guarda, e havia
**dez** delas em texto corrido: "o Definition of Done global", "o contrato do Planner", "os
estados da Engineering OS".

A alternativa boa passou a existir no caminho: a Engineering OS é publicada em
`github.com/biahflow/engineeringOS`, com CI própria e releases SemVer.

## Decisão

**D1. Um espelho completo da camada global vive em `docs/engineering-os/`.** Cópia fiel, em
inglês, sem tradução e sem edição manual — 91 arquivos, 760 KB. Espelho completo e não recorte:
copiar só os trechos citados quebraria os links internos entre os documentos globais e criaria
uma terceira versão parcial da camada, pior de manter que o todo.

**D2. O pino é uma tag SemVer, e o que não é tag é recusado.** `PINNED_TAG` em
`scripts/sync-engineering-os.mjs` é constante versionada: avançar o pino é um diff de uma linha,
revisado como qualquer outra mudança. Uma branch se move, e um pino que se move não é pino —
`--tag main` falha com essa frase. O `PROVENANCE.md` registra a tag **e** o commit que ela
resolve, para que o pino continue conferível se alguém repontar a tag.

**D3. As referências passam a apontar, e `tests/docs-links.test.mjs` as confere.** É o que
transforma citação em referência: sem portão, o link só adia o problema que o texto corrido já
tinha. O corpus sai de `git ls-files`, nunca digitado (ADR 0033), e é fail-closed — glob que
devolve quase nada reprova. O espelho entra no corpus de propósito: um espelho incompleto
quebra os links internos dos documentos globais, que é exatamente o sinal desejado.

**D4. O núcleo do sync é puro, e o harness o exercita.** `plan()` e `stable()` não têm
processo, rede nem relógio, na forma do `evaluate()` do `audit.mjs` e do `references()` do
`pins.mjs`. O que os testes defendem é a **poda que apaga demais**: `plan().remove` vira
`unlinkSync` dentro de um diretório versionado, e um `remove` que incluísse o `PROVENANCE.md`
apagaria justamente o registro do pino.

**D5. O espelho sai do corpus das guardas estruturais deste repositório.**
`engineering-os` entra no `_NOT_OURS` de `test_architecture_doc.py`,
`test_supply_chain_pins.py` e `test_roadmap_index.py`, onde já moram `node_modules` e `.venv`
pela mesma razão: não é deste repositório. A guarda nasceu vermelha com
`TESTING-COMPLETE.md` desenhando `./bin/biah` — um artefato de build que a origem passou a
ignorar, e cuja ausência é correta lá. Cobrar do espelho as regras estruturais daqui só produz
falha que a D1 proíbe consertar, e produziria de novo a cada release da origem. É o precedente
da ADR 0034 do croquito, que tirou o espelho do `ruff format` pelo mesmo motivo: fidelidade à
origem vence estilo local.

**D6. Ressincronizar exige rede; usar o espelho, não.** Depois da sincronização, CI,
colaborador novo e agente em nuvem leem as regras do próprio checkout, sem rede e sem
credencial. Um submodule apontando para a tag resolveria a alcançabilidade e destruiria essa
propriedade.

## Consequências

Positivas: a camada global passa a existir fora da máquina do operador; a defasagem vira fato
datado e legível — `v0.1.0` diz mais que um SHA, e o `VERSIONING.md` da origem define quando
uma mudança pode tornar um projeto conforme em não conforme; as dez citações em texto corrido
viram links que o `npm test` reprova quando quebram; mover o diretório do checkout deixa de
quebrar qualquer coisa aqui.

Negativas: 760 KB de documentação em inglês entram no repositório e aparecem nas buscas — o
espelho não é fonte de decisão do produto e não deve ser editado aqui; a origem precisa manter
disciplina de release, porque sem tag nova não há como avançar o pino.

E o espelho envelhece silenciosamente entre sincronizações: quem mudar a camada global precisa
lembrar de trazê-la, e o repositório não avisa sozinho. **Fica aberto:** uma guarda que compare
o pino com a última tag publicada seria a outra metade, na divisão do `audit.mjs` — o portão
detecta, o conserto é de uma pessoa —, mas ela precisa de rede no CI e o custo dessa
dependência ainda não foi medido.

`AGENTS.md` passa a declarar a precedência em vez de reformulá-la: onde os dois falarem do
mesmo assunto, o global manda e o local só aperta.
