# Artefatos de execução de features

## Convenção prospectiva

FDDs existentes em [`docs/fdd/`](../fdd/) são os Feature Contracts do projeto e permanecem no
local histórico. Para uma feature nova ou retomada, use o ID estável `F-<número da FDD>` e crie
artefatos de execução sem mover a FDD:

```text
docs/
├── fdd/
│   └── 025-exemplo.md
└── features/
    └── F-025-exemplo/
        ├── plan.md
        ├── tasks/
        │   └── T01.md
        └── evidence.md
```

`plan.md` segue o contrato do Planner da Engineering OS e representa um DAG válido. Cada contrato
em `tasks/` declara Feature ID, Task ID, escopo, fora de escopo, critérios de aceite,
dependências, validação e capacidades. `evidence.md` referencia baseline, relatórios completos de
Builder, validações, desvios de plano, revisão e decisões humanas.

## Autoridade e gates

- A FDD declara **o que** a feature entrega e seu estado de ciclo.
- O plano declara **como** a execução é decomposta; não altera requisitos.
- Contratos de tarefa autorizam um Builder apenas no escopo explicitamente aceito.
- Evidência é o handoff para revisão; não substitui os relatórios de Builder.
- Nenhum artefato permite escolher prioridade, aprovar trabalho, marcar `DONE` ou executar
  produção sem a autoridade humana aplicável.

FDDs concluídas ou parcialmente implementadas antes desta convenção não exigem migração
retroativa. Para `F-020` e `F-022`, crie um plano somente depois de seleção humana e de seus
respectivos bloqueios serem resolvidos.
