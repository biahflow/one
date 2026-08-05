# Arquitetura

O Portal Labs é um monorepo com frontend Next.js, API FastAPI e worker Celery. O navegador usa uma sessão OIDC protegida e o frontend atua como BFF; regras de permissão, acesso a dados e chamadas de IA permanecem no servidor.

```text
              ┌──────────────┐
              │   Keycloak   │  OIDC: o BFF faz o code exchange (PKCE),
              └──────┬───────┘  a API só verifica o token contra o JWKS
                     │
Browser → Next.js BFF → FastAPI → PostgreSQL + pgvector
                         ├→ Redis/Celery → Drive, e-mail, indexação
                         └→ MinIO/S3 → documentos e transcrições
```

PostgreSQL é a fonte de verdade. O banco aplica RLS por organização e projeto; a API também executa autorização explícita. O worker recebe somente jobs com escopo de projeto e propaga o contexto de tenant.

Três credenciais de banco, uma por tipo de trabalho (ADR 0010): `portal_app` no caminho de
requisição, **sujeito às policies**; `portal_system` (`BYPASSRLS`) para o webhook e o seed, que
criam o tenant; `portal_migrator`, dono do schema, para as migrações. A separação não é
organizacional — é o que faz a RLS existir, já que superusuário a ignora incondicionalmente.

## Topologia de implantação (ADR 0022)

O diagrama acima é lógico. Fisicamente há **dois ambientes**, e a diferença entre eles não é de
escala, é de fronteira.

**Local** (`docker-compose.yml`): treze serviços, cada um publicando porta no host, com senhas de
exemplo versionadas e três dublês que só existem aqui — `mailpit` (caixa de entrada de mentira),
`drive-stub` (Google Drive de mentira) e `api-seed` (dado de demonstração). É o certo para uma
máquina de desenvolvimento, que precisa subir com um `cp .env.example .env`.

**Homologação** (`+ docker-compose.homolog.yml`): os três dublês saem, o Keycloak deixa o modo de
desenvolvimento, e **um único serviço publica porta** — o Caddy, que termina o TLS e roteia dois
nomes:

```text
                    Internet
                       │  443
                 ┌─────┴─────┐
                 │   Caddy   │  TLS automático (ACME)
                 └──┬─────┬──┘
   portal.<domínio> │     │ auth.<domínio>
                    ▼     ▼
                  web   keycloak
                    │       ▲
                    │       │ backchannel
                    ▼       │
                   api ─────┘        ← nunca publicada: quem fala com ela é o BFF
                    ├→ postgres, redis, minio, clamav
                    └→ worker, beat
```

A API não aparecer na fronteira é o desenho da ADR 0010, não uma economia: o navegador nunca a
alcança, porque o access token vive no cookie cifrado do BFF e a autorização é decidida no
servidor. Publicá-la daria à internet um caminho que o portal não usa.

O que **não** muda entre os dois: as três imagens, as quatro credenciais de banco, as migrações e
o código. O que muda é um arquivo de override e um `.env` — e a garantia de que o segundo não é o
primeiro está em dois lugares, `${VAR:?}` no compose e `portal_api/preflight.py` no processo.
Subir é `docs/runbooks/deploy.md`.

## Domínios

- Identidade: usuário, convite, papel e associação ao projeto.
- Projeto: status, entregas, marcos, decisões e pendências.
- Conhecimento: documento, reunião, transcrição, chunk, fonte e citação.
- Resultados: investimento, evento de agente, horas poupadas, custo evitado e ROI.
- Conversa: mensagem, recuperação, resposta, fonte e escalonamento.
