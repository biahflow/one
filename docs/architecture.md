# Arquitetura

O One é um monorepo com frontend Next.js, API FastAPI e worker Celery. O navegador usa uma sessão OIDC protegida e o frontend atua como BFF; regras de permissão, acesso a dados e chamadas de IA permanecem no servidor.

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

Quatro credenciais de banco, uma por tipo de trabalho (ADR 0010/0011): `portal_app` no caminho de
requisição, **sujeito às policies**; `portal_system` (`BYPASSRLS`) para o webhook e o seed, que
criam o tenant; `portal_migrator`, dono do schema, para as migrações; e `portal_admin`, também
**sujeito às policies**, que é o único que escreve `membership`. A separação não é
organizacional — é o que faz a RLS existir, já que superusuário a ignora incondicionalmente.

*Corrigido em 06/08/2026 (ADR 0035): este parágrafo dizia "Três credenciais" e nomeava três,
enquanto a seção de topologia logo abaixo já dizia "as quatro credenciais de banco". A frase é da
Fase 1, anterior ao `portal_admin` (ADR 0011), e a que a contradiz foi escrita na ADR 0022 sem que
ninguém voltasse aqui — de modo que a lista canônica de credenciais omitia justamente o papel que
escreve na tabela mais sensível do modelo de autorização.*

## Topologia de implantação (ADR 0022, ADR 0044–0053)

O diagrama acima é lógico. Fisicamente há **Local**, **Homologação** e **Nuvem**, e a diferença
entre elas não é de escala, é de fronteira.

**Local** (`docker-compose.yml`): treze serviços, dos quais oito publicam porta no host, com
senhas de exemplo versionadas e três dublês que só existem aqui — `mailpit` (caixa de entrada de
mentira), `drive-stub` (Google Drive de mentira) e `api-seed` (dado de demonstração). É o certo
para uma máquina de desenvolvimento, que precisa subir com um `cp .env.example .env`.

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

O que **não** muda entre os dois composes: as duas imagens, as quatro credenciais de banco, as
migrações e o código. O que muda é um arquivo de override e um `.env` — e a garantia de que o
segundo não é o primeiro está em dois lugares, `${VAR:?}` no compose e `portal_api/preflight.py`
no processo. Subir é `docs/runbooks/deploy.md`.

**Nuvem** (`infra/terraform/`): a terceira fronteira, e a única em que não há compose. Não há
Caddy e não há porta no host — cada serviço é um Cloud Run, e quem termina o TLS e decide quem
passa é a borda, hoje a Cloudflare. E a fronteira do **dado** deixa de coincidir com a da pilha:
Postgres é **Neon** e Redis é **Upstash**, os dois fora do provedor, alcançados por DSN através do
egress da VPC. O `boto3` do `storage.py` fala com o Cloud Storage pelo mesmo protocolo S3 com que
fala com o MinIO. São **dois** states do Terraform, um por dono: `infra/terraform/ambientes/hml/`
é a fundação compartilhada — rede, saída, registro de imagens, cofre, identidades e a borda — e
`infra/terraform/ambientes/hml-biahflow/` são os serviços do portal operacional, que é **outro
produto**. A forma está em `infra/terraform/README.md`; a ordem de subir, em
`docs/runbooks/hml-gcp.md`.

**E este produto não está implantado nesta terceira topologia.** Desde 13/08/2026 (ADR 0053) o
portal do cliente saiu da GCP por decisão de produto; `infra/terraform/ambientes/hml-portal/` foi
apagado com o state e os segredos que eram dele, e o `deploy-hml.yml` perdeu o gatilho de push
sem deixar de ser a receita de como o portal sobe. É por isso que o único ambiente de nuvem
nomeado acima ao lado da fundação é o de outro produto: a topologia existe, é aplicável, e hoje
não hospeda este.

*Corrigido em 20/08/2026 (ADR 0064): esta seção dizia "Fisicamente há **dois ambientes**" e
descrevia só os dois composes — não continha as palavras `Terraform`, `Cloud Run`, `Cloudflare`,
`Neon` nem `Upstash`, dez ADRs depois de a nuvem existir como código neste repositório, e não
sabia que o portal tinha saído do ar. Dizia também "treze serviços, **cada um** publicando porta
no host", quando oito dos treze publicam, e "as **três** imagens", quando há dois contextos de
build. O cardinal "dois ambientes" não foi corrigido para três: foi **apagado**, e as topologias
passaram a ser nomeadas — guarde o número cujo denominador é artefato contável, apague o número
cujo denominador é escolha narrativa. Quem cobra os que ficaram é
`apps/api/tests/test_architecture_doc.py`.*

## Domínios

- Identidade: usuário, convite, papel e associação ao projeto.
- Projeto: status, entregas, marcos, decisões e pendências.
- Conhecimento: documento, reunião, transcrição, chunk, fonte e citação.
- Resultados: investimento, evento de agente, horas poupadas, custo evitado e ROI.
- Conversa: mensagem, recuperação, resposta, fonte e escalonamento.
