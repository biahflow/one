# Portal Labs

Portal multiempresa para clientes acompanharem projetos, resultados e decisões, com uma IA contextual que responde somente com evidências do projeto.

## Ambiente local

O frontend funciona com `npm run dev`. Para subir toda a plataforma local — API, worker, PostgreSQL, Redis, MinIO, Keycloak e Mailpit — use:

```bash
cp .env.example .env
docker compose up --build
```

| Serviço | Endereço local |
| --- | --- |
| Portal web | http://localhost:3000 |
| API e OpenAPI | http://localhost:8000/docs |
| Keycloak | http://localhost:8080 |
| MinIO Console | http://localhost:9001 |
| Mailpit | http://localhost:8025 |
| Drive stub | http://localhost:19100 |

**Com a pilha no ar, siga [`docs/runbooks/passeio-local.md`](docs/runbooks/passeio-local.md):**
quem é quem no ambiente local (três contas semeadas, senha versionada), e o caminho para ver
cada fatia funcionando — login, busca, notificação com e-mail, citação do assistente, documento
indexado, pasta do Drive, ROI apurado e a negação que é 404 e nunca 403.

## Estrutura

- `app/`: experiência web do cliente.
- `apps/api/`: API FastAPI, domínio e integrações.
- `apps/worker/`: jobs assíncronos.
- `docs/`: PRD, arquitetura, segurança, decisões e design de funcionalidades.
- `infra/`: configuração local de banco e identidade.

## Qualidade

```bash
npm run lint
npm test
docker compose up --build
```

Consulte [AGENTS.md](AGENTS.md) antes de alterar código. As regras de produto, segurança e IA estão em [PRD.md](PRD.md) e `docs/`.
O contexto operacional, fontes de verdade e perfis de validação estão em
[`docs/project-context.md`](docs/project-context.md).
