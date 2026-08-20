# Guia para agentes e contribuidores

## Princípios inegociáveis

1. Todo dado pertence a uma organização e a um projeto; nunca use um identificador fornecido pelo cliente sem validar o vínculo no servidor.
2. Não envie segredos, tokens, instruções de sistema ou contexto de outro projeto ao modelo de IA.
3. Respostas de IA devem citar fontes. Sem evidência, devem declarar a lacuna e criar uma pendência, nunca inventar uma resposta.
4. Migrações são aditivas e revisadas; alterações de tenant, autenticação, RAG ou retenção exigem ADR/RFC.
5. Não inclua segredos em commits, fixtures, logs ou documentação.
6. Todo endpoint ou busca nova tem caso negativo de permissão, e ele afirma 404 — nunca 403.

*A regra 6 foi escrita como princípio na ADR 0035. Ela já era citada "regra 6 do
`AGENTS.md`" por duas ADRs, uma FDD e três arquivos de teste, e o número não
existia: o texto vivia como item da lista de pull request abaixo, e a numeração
que circulava vinha da cópia do `CLAUDE.md` — que tinha seis itens, promovera uma
convenção a princípio e **descartara** a regra 5. Uma guarda afirma que as duas
listas são a mesma e que toda citação por número resolve.*

## Convenções

- Código, nomes de API e banco em inglês; experiência e documentação de produto em PT-BR.
- API REST sob `/api/v1`; payloads Pydantic e erros padronizados.
- Frontend não decide autorização. O backend valida identidade, organização, projeto e papel.
- Toda FDD inclui critérios de aceite, telemetria, testes e casos de avaliação de IA.

## Engineering OS e ciclo de trabalho

- O contexto operacional do projeto está em [`docs/project-context.md`](docs/project-context.md).
  Ele aponta para as fontes canônicas; não duplique seus comandos ou decisões aqui.
- [`ROADMAP.md`](ROADMAP.md) é o índice canônico de trabalho. Para uma funcionalidade com FDD,
  a FDD é o contrato detalhado e dona do estado do ciclo; ADRs registram decisões e RFCs preservam
  contexto, não status de implementação.
- Adoção é prospectiva: FDDs históricas permanecem no lugar. Novas FDDs usam o template com
  identificador `F-<número>` e estados da Engineering OS. Planos, contratos de tarefa e evidências
  vivem conforme [`docs/features/README.md`](docs/features/README.md).
- Nenhum agente escolhe prioridade, inicia implementação ou marca uma funcionalidade como `DONE`
  sem a seleção e o gate humano aplicáveis.

## Antes de abrir pull request

- Atualize FDD, ADR ou RFC que fundamenta a mudança.
- Atualize o [`ROADMAP.md`](ROADMAP.md) no mesmo commit quando a fatia mudar o estado publicado —
  entrega nova, item que deixa de estar aberto, ou produto que sai do ar. Ele é o índice canônico
  de descoberta: uma ADR aceita que ele não conhece é estado sem dono, e foi assim que dez delas
  ficaram de fora entre 07 e 19/08/2026.
- Rode lint, tipos, testes unitários e integração aplicáveis.
- Adicione caso negativo de permissão para qualquer endpoint ou busca nova.
- Adicione avaliações de IA para mudança de prompt, recuperador, modelo ou ferramenta.
- Rode `npm run audit` ao mexer em dependência — dos dois lados, e o CI reprova
  igual (ADR 0023). Aviso que não dá para consertar agora vira linha **com motivo
  e prazo** em `docs/security/advisories.json`; ela vence, e é a única forma de
  não reprovar. Ver `docs/runbooks/dependency-advisory.md`.
- Mexeu em workflow ou em imagem de contêiner? **O pino vem junto** (ADR 0063): action por
  SHA de commit com a versão ao lado (`# v4`), imagem por digest com a tag ao lado.
  `npm run pins` lista as referências e `npm run pins -- --update` as resolve;
  `test_supply_chain_pins.py` reprova quem despinar. Isenção é linha em `PINNED_BY_EXCEPTION`
  com motivo e **sem prazo** — pino não caduca por calendário, e quem a vence é a asserção de
  obsolescência.
- Escreveu migração? **Ela é aditiva, e cita a decisão** (ADR 0066). `test_migration_rules.py`
  lê o AST do `upgrade()` — e só dele, porque `downgrade()` é destrutivo por definição — e
  reprova o que apaga dado (`drop_table`, `drop_column`, `DROP TABLE/COLUMN`, `TRUNCATE`);
  `DROP INDEX`, `DROP TYPE`, `DROP POLICY` e `DROP DEFAULT` passam, porque mudam regime e não
  linhas. Migração que toca policy, RLS ou privilégio cita ADR ou RFC **que existe e não foi
  recusada**, que é a regra 4 na parte em que o gatilho é estrutural. Isenção é linha em
  `ADDITIVE_BY_EXCEPTION` com motivo e sem prazo. O `alembic check` **não** cobre isto: ele
  existe contra deriva, não contra perda.
- Apagou um diretório, criou um ambiente ou mudou o que a pilha tem? **O documento de
  arquitetura vem junto** (ADR 0064): `test_architecture_doc.py` cobra que todo ambiente
  declarado (`docker-compose*.yml`, `infra/terraform/ambientes/*/` com `backend.tf`) seja nomeado
  na topologia de `docs/architecture.md`, que todo caminho desenhado num bloco de estrutura
  exista, que todo serviço nomeado na tabela de HML seja chave de algum `servicos.tf`, e que
  número escrito case com o contado. **Guarde o número cujo denominador é artefato contável;
  apague o número cujo denominador é escolha narrativa.**

## Comandos locais

```bash
npm run lint
npm test
docker compose up --build
```
