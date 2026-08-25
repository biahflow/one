# FDD 025 — O nome que a tela ainda não sabia

**Feature ID:** `F-025`

**Classificação de design:** `INTERFACE_CHANGE` — cria e altera superfície perceptível por
humano, inclusive marca, `<title>`, e-mail e os estados de erro, vazio e não autorizado.

**Classe de validação:** `BROWSER_REQUIRED`.

**Origem:** [Issue #46](https://github.com/biahflow/portal-cliente/issues/46), sob a
Engineering OS (`workflows/design-approval.md`, `workflows/browser-runtime-validation.md`).

## Status

`SPEC_IN_PROGRESS` → `READY_FOR_PLANNING` **somente depois** de o humano aprovar a revisão exata
do Design Approval Package — hoje a **revisão 1**, em
[`design-approval.md`](../features/F-025-o-nome-que-a-tela-ainda-nao-sabia/design-approval.md),
estado `Awaiting approval`. O gate fica **antes do planejamento**, não antes da construção: um
plano que decompõe superfície não aprovada produz tarefas que precisam ser recortadas de novo
quando o desenho muda.

## Prioridade

Selecionada por humano em 25/08/2026, pela Issue #46.

## Objetivo e não objetivos

### Problema

A ADR 0067 renomeou o produto para **One** com uma frase — *"O produto passa a ser chamado
One"* — e nada mais. Nenhuma decisão sobre marca, cor, tipografia, token, ou sobre a relação
entre **Biahflow** (empresa) e **One** (produto). Um dia depois, o repositório inteiro ainda
afirma o nome antigo em toda superfície que o cliente alcança: a sidebar escreve
`portal`**`labs`**, o `<title>` diz `Portal Labs | Portal do Cliente`, o assistente se apresenta
como "o assistente do Portal Labs", o e-mail de notificação sai de
`Portal Labs <portal@portallabs.local>`, a tela de login do Keycloak anuncia `Portal Labs (Local)`
e o `og.png` estampa o monograma da marca antiga.

E o problema não é só o nome. **Não existe fundação para o One consumir.** Não há diretório
`components/`; o wordmark está escrito à mão em dois lugares que precisam ser idênticos, sem
nada que fique vermelho quando divergirem — o defeito que `textfold.py` existe para impedir do
lado da API. Não há token de espaçamento, de raio, de foco nem de estado **informativo**: o
`@theme` tem `success`, `warning` e `danger`, e o quarto estado que a Issue cobra simplesmente
não existe. E `app/globals.css` escreve o roxo da marca **à mão, em quatro lugares**, contra a
regra que o próprio repositório publica ("nunca escreva hex num componente").

Enquanto isso, ADR 0067 e o `docs/contracts/client-projection-contract.md` já fixaram o
vocabulário que a próxima superfície do One vai desenhar — `ready_for_acceptance`,
`client_review`, `accepted`, `changes_requested` — e não há primitiva que saiba mostrá-lo.

### Resultado desejado

1. Existe um **Design Approval Package** revisionado, auto-contido e com captura congelada, e um
   humano aprovou a revisão exata antes de qualquer implementação.
2. A relação **Biahflow ⟂ One** está escrita e aplicada: o produto aparece na marca e no título;
   a empresa aparece onde a cópia fala do *time*.
3. Toda superfície que o cliente alcança diz **One**, e nenhuma diz Portal Labs.
4. Existe contrato estável de token e de primitiva para o trabalho futuro do One, com a
   linguagem **extraída para documento**, não deixada dentro do artefato de aprovação.
5. Existe superfície viva que prova o sistema num navegador de verdade, com evidência
   congelada presa à revisão exata.

### Escopo

- Design Approval Package (revisão 1) com rendering auto-contido e capturas.
- Terminologia **One** no shell do cliente e nas superfícies representativas.
- Identidade de produto no backend que o cliente lê: título da API publicada, nome do remetente
  de e-mail, como o assistente se apresenta, rótulo do dono de marco e pendência, realm local.
- Tokens semânticos novos: estado informativo, foco, hierarquia de superfície, política de raio
  e escala de espaçamento — e a correção dos quatro hex escritos à mão.
- Três primitivas em `components/one/`, todas com consumidor real: marca, pastilha de estado
  (**ícone + texto + cor**) e botão.
- Vitrine interna que renderiza o sistema para validação de navegador.
- `docs/design/one-design-system.md`, declarado como fonte no `docs/project-context.md` — que
  hoje **não** declara onde vive o design system, embora o gate de design exija isso do projeto.

### Fora de escopo

- **Renomear o repositório** `portal-cliente` → `one`. A Issue #46 exclui explicitamente.
- **Religar infraestrutura.** O portal está fora do ar desde 13/08/2026 (ADR 0053). A validação
  de navegador roda na pilha **local**, que é runtime real e production-like o bastante para o
  que esta fatia muda; nada aqui reativa GCP, Terraform ou `deploy-hml.yml`.
- **Tema escuro.** Não há `dark:` neste produto, e a Issue o exclui salvo proposta aprovada em
  separado. A revisão 1 do DAP não o propõe.
- **Redesenhar as telas existentes.** Elas mudam de nome, não de forma. Renomear classe de CSS
  quebraria os seletores dos specs de e2e sem entregar nada ao cliente.
- **Mudar fluxo de dado, isolamento de tenant, autenticação, autorização ou RAG.** Nenhuma
  policy, nenhum GRANT, nenhuma migração, nenhum prompt novo — só a frase de apresentação do
  assistente, que obriga bump de versão e é a única mudança de IA aqui.
- **Implementar o laço de aceitação da ADR 0067.** O DAP *desenha* o estado de revisão e decisão
  do cliente para provar a linguagem visual; o fluxo continua não existindo, e o desenho declara
  isso como **reservado**, não como entregue.
- **Mudar o Pulse**, ou reusar a identidade clay dele.
- **Trocar a marca de cor.** Decidido por humano em 25/08/2026: o roxo fica, e o que muda é que
  ele passa a ser decisão declarada em vez de herança.

## Jornada e interface

O cliente abre o link do convite. A tela de login diz **One**, e o painel de marca é o mesmo
gradiente roxo de sempre — o que mudou é que agora ele tem procedência escrita. Entra, e a
sidebar traz o wordmark `One` com o descender `por Biahflow`: o produto que ele usa, e a empresa
com quem ele fala. A aba do navegador diz `One | Portal do Cliente`. Quando o assistente não
acha evidência e abre pendência, o chip diz "Pendência criada para o time Biahflow" — o time tem
nome de empresa, porque é com a empresa que ele fala; o produto é a tela.

Nada mais muda de lugar. Os marcos, a jornada, o chat, as citações, as pendências e a busca
continuam exatamente onde estavam, com as mesmas classes e o mesmo comportamento.

Do lado interno, `/admin/design` passa a existir: a vitrine do sistema. É onde um humano vê, num
navegador, o que os tokens e as primitivas produzem — e é o que torna `BROWSER_REQUIRED`
verificável sem depender de encenar um estado raro em dado de produção.

## Dados, API e permissões

**Nenhuma mudança.** Sem migração, sem policy, sem GRANT, sem rota nova de API, sem esquema novo
no contrato publicado. A regra 6 do `AGENTS.md` — caso negativo de permissão que afirma 404 — não
é acionada porque nenhum endpoint nasce aqui.

A única mudança no artefato de contrato é o `info.title` do `docs/api/openapi.json`, que
acompanha o `FastAPI(title=...)` e é regenerado no mesmo commit, como o gate de deriva exige.

A vitrine `/admin/design` é rota do BFF, fechada pelo `proxy.ts` como todo o resto, e espelha o
`notFound()` de `app/admin/page.tsx` para quem não é interno — ergonomia, não segurança: a
autoridade continua sendo a API, que responde 404.

## Estados de erro e segurança

Os estados de erro **não mudam de comportamento**, e mudam de nome: a tela de erro e a de
projeto não atribuído deixam de citar Portal Labs. O DAP inclui os cinco estados que o gate
cobra — sucesso, vazio, erro, não autorizado e carregando — mais foco de teclado, porque
`:focus-visible` é decisão visual e é a que mais some quando ninguém a desenha.

Segurança: nada nesta fatia toca sessão, token, RLS ou tenant. A troca do domínio dos e-mails
semeados (`@portallabs.com.br` → `@biahflow.ai`) mexe em **dado de desenvolvimento local**, e
tem de sair no mesmo commit dos dois lados — `seed.py` e o realm — porque
`test_seed_matches_realm.py` compara `sub`, e-mail, nome e papel um a um. Um UUID editado de um
lado só produz alguém que autentica e não casa com linha nenhuma, o que aparece muito depois como
"todo mundo vê 404". A conta da cliente (`marina.farias@acme.com.br`) **não** muda: ela é cliente,
não é do time.

## Restrições e dependências

- **O gate de design bloqueia o planejamento**, e um agente não aprova design — nem o que ele
  mesmo produziu (`workflows/design-approval.md`, seção *Agent authority*).
- **`components/` entra no corpus de `tests/rendered-html.test.mjs`.** Todo `<button>` novo
  precisa de `onClick` ou `type="submit"`; nenhum arquivo novo pode declarar dado fixo de aba.
- **`components/` não entra no corpus de `tests/api-contract.test.mjs`**, que só varre `app/`.
  Mover mapeamento de JSON da API para lá derrubaria a guarda de consumo. Primitiva é
  apresentação; o mapeamento fica onde está.
- **Mexer no `SYSTEM_PROMPT` obriga `PROMPT_VERSION` nova** e registro append-only; regravar
  versão já gravada é recusado por construção.
- **`docs/api/openapi.json` casa byte a byte** com o que o código gera.
- **Bloco cercado com três ou mais linhas em forma de caminho** é lido como árvore de diretórios
  por `test_architecture_doc.py`, e todo caminho precisa existir. Documento novo desta fatia usa
  tabela, não árvore.
- Depende da ADR 0067 (o nome) e do `docs/contracts/client-projection-contract.md` (o
  vocabulário de homologação que o DAP desenha).

## Lacunas e riscos

- **O monograma "P" morre com o nome antigo, e não existe substituto pronto.** Ele só existe
  embutido no `og.png`; a aplicação nunca o usou — o `.brand-mark` é um ícone genérico. A revisão
  1 do DAP propõe direção de marca; se o humano recusar, é o gate funcionando, e é barato.
- **O `og.png` é imagem, não código.** Regenerá-lo a partir de HTML capturado é determinístico,
  mas o resultado é decisão visual e entra no DAP como tal.
- **Renomear é varredura**, e varredura erra por omissão. O critério de aceite é um `grep` que
  precisa voltar só com prosa histórica — verificável, não argumentado.
- **ADR aceita não é reescrita.** As ADRs 0008, 0009 e 0021 continuam dizendo Portal Labs, e o
  histórico do roadmap também. A ADR desta fatia registra a retificação em vez de apagar o
  registro.
- **Colisão de numeração registrada, não resolvida:** a branch `a-flag-que-o-casador-nao-conhecia`
  numera sua ADR como 0067, número que `main` já usou. A desta fatia é **0069**; quem mergear por
  último renumera.

## Gates humanos

1. **Aprovação do Design Approval Package**, revisão exata, antes de qualquer implementação.
   Um agente pode produzir e revisar o pacote e transcrever a decisão; aprovar, não.
2. **Merge do pull request.** O harness comita, empurra, abre PR e observa CI; não mergeia e não
   liga auto-merge.
3. **`DONE`** só depois de evidência, revisão aplicável e decisão humana. Merge de PR é evidência
   de integração de engenharia, não aceitação de cliente.

## Telemetria e critérios de aceite

**Telemetria: nenhuma nova.** A vitrine não emite evento — evento novo obriga linha em
`docs/runbooks/alerts.md` no mesmo commit, e um gasto de alerta que ninguém vai vigiar é ruído.
A guarda bidirecional de `test_telemetry.py` continua verde por não ter o que cobrar.

### Gate de design

- [ ] Existe DAP auto-contido, revisionado, que abre sem build, sem toolchain e sem rede.
- [ ] O pacote traz **captura congelada**, não só prosa.
- [ ] A relação Biahflow ⟂ One está explícita.
- [ ] Todo valor visual está declarado como **retido** ou **novo**, com procedência.
- [ ] Um humano aprovou a revisão exata antes de o Builder começar.

### Fundação do One

- [ ] Nenhuma superfície client-facing diz "Portal Labs"; o `grep` de aceite volta só com prosa
      histórica.
- [ ] Nenhum token do Pulse é reusado como pele do One.
- [ ] Cor, tipografia, espaçamento, raio, elevação e os **quatro** estados semânticos estão
      definidos — inclusive o informativo, que não existia.
- [ ] `docs/design/one-design-system.md` existe e está declarado no `docs/project-context.md`.
- [ ] As três primitivas têm consumidor real; o wordmark deixa de existir duas vezes escrito à
      mão.
- [ ] `app/globals.css` não escreve mais hex de marca à mão.
- [ ] Autenticação, permissão e fronteira de tenant seguem sem mudança de comportamento.

### Validação

- [ ] `npm run lint`, `npm test`, `pytest apps/api/tests` (sem o de backup) e `npm run audit`
      verdes; `alembic check` sem deriva.
- [ ] `npm run test:e2e` verde com a pilha de pé.
- [ ] Evidência de navegador na revisão exata: shell desktop, shell mobile, foco de teclado,
      dashboard/projeto, os quatro estados semânticos com **ícone + texto + cor**, e o estado de
      revisão/decisão do cliente.
- [ ] Expectativa de contraste documentada e verificada onde se aplica.
- [ ] `REVIEW_PASS`, com o laço automático Builder ↔ Reviewer quando necessário
      (`max_review_feedback_iterations = 3`).
- [ ] Política de CI respeitada: `codeql` e `dependency-review` continuam desligados por
      variável, e isso fica **registrado como exceção** em vez de tratado como `CI_GREEN`.

### Git e gate humano

- [ ] Classificação de paralelismo registrada antes da execução gravável.
- [ ] Implementação em branch e worktree dedicados, com um Builder ativo.
- [ ] PR é o caminho canônico de integração e carrega o DAP aprovado, a evidência local, a de
      navegador e o resultado da revisão.
- [ ] O harness não mergeia. O humano decide.
- [ ] Depois do merge, limpeza segura de worktree, branch local e branch remota.

## Referências

| Fonte | O que ela decide |
| --- | --- |
| `docs/adr/0067-one-como-projecao-client-facing.md` | O nome, e que o estado de Delivery é projeção |
| `docs/contracts/client-projection-contract.md` | O vocabulário de homologação que o DAP desenha |
| `docs/adr/0026-*.md` | Controle inerte é defeito, não placeholder |
| `docs/adr/0021-*.md` | Tela não fabrica dado; e o registro append-only de prompt |
| `docs/adr/0054-*.md` | ADR aceita sem linha no roadmap é estado sem dono |
| `docs/project-context.md` | Perfis de validação e fontes de verdade |
| `workflows/design-approval.md` (Engineering OS) | O gate, e o que o pacote precisa conter |
| `workflows/browser-runtime-validation.md` (Engineering OS) | O que `BROWSER_REQUIRED` exige |
| `docs/features/F-025-o-nome-que-a-tela-ainda-nao-sabia/design-approval.md` | **O Design Approval Package**, revisão 1 — registro, procedência e questões em aberto |
| `docs/features/F-025-o-nome-que-a-tela-ainda-nao-sabia/design/one-dap-r1.html` | O artefato auto-contido que o gate aprova |

## Testes e avaliações de IA

**Avaliação de IA: obrigatória e mínima.** A frase de apresentação do `SYSTEM_PROMPT` muda, o que
obriga `PROMPT_VERSION` nova e registro. O conjunto adversarial de `docs/ai/eval-dataset.md` roda
inteiro contra o respondedor real com o cliente injetado pela costura — sem chave e sem custo de
token —, porque mudança de prompt pede eval, mesmo quando a mudança é de nome. O que a eval tem
de continuar provando é o que já provava: sem evidência, declarar a lacuna e abrir pendência;
nunca inventar citação; nunca obedecer a instrução embutida no documento.

**Testes que mudam de expectativa, e não de propriedade:** as asserções de `<title>` e de cópia
em `tests/rendered-html.test.mjs`, o `info.title` em `test_openapi_contract.py`, o rótulo de dono
em `test_biahflow_integration.py` e as fixtures de e-mail. Nenhuma guarda é afrouxada: elas
passam a afirmar o nome novo com a mesma força com que afirmavam o antigo.

**Teste novo:** a marca deixa de existir duas vezes. A primitiva é o mecanismo; a asserção é que
o wordmark literal não volta a aparecer escrito à mão nos arquivos de tela.
