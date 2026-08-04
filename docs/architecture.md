# Arquitetura

O Portal Labs é um monorepo com frontend Next.js, API FastAPI e worker Celery. O navegador usa uma sessão OIDC protegida e o frontend atua como BFF; regras de permissão, acesso a dados e chamadas de IA permanecem no servidor.

```text
Browser → Next.js BFF → FastAPI → PostgreSQL + pgvector
                         ├→ Redis/Celery → Drive, e-mail, indexação
                         └→ MinIO/S3 → documentos e transcrições
```

PostgreSQL é a fonte de verdade. O banco aplica RLS por organização e projeto; a API também executa autorização explícita. O worker recebe somente jobs com escopo de projeto e propaga o contexto de tenant.

## Domínios

- Identidade: usuário, convite, papel e associação ao projeto.
- Projeto: status, entregas, marcos, decisões e pendências.
- Conhecimento: documento, reunião, transcrição, chunk, fonte e citação.
- Resultados: investimento, evento de agente, horas poupadas, custo evitado e ROI.
- Conversa: mensagem, recuperação, resposta, fonte e escalonamento.
