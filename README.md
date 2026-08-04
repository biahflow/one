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
