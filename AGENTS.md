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

## Antes de abrir pull request

- Atualize FDD, ADR ou RFC que fundamenta a mudança.
- Rode lint, tipos, testes unitários e integração aplicáveis.
- Adicione caso negativo de permissão para qualquer endpoint ou busca nova.
- Adicione avaliações de IA para mudança de prompt, recuperador, modelo ou ferramenta.
- Rode `npm run audit` ao mexer em dependência — dos dois lados, e o CI reprova
  igual (ADR 0023). Aviso que não dá para consertar agora vira linha **com motivo
  e prazo** em `docs/security/advisories.json`; ela vence, e é a única forma de
  não reprovar. Ver `docs/runbooks/dependency-advisory.md`.

## Comandos locais

```bash
npm run lint
npm test
docker compose up --build
```
