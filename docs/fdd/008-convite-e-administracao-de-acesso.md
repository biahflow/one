# FDD 008 — Convite e administração de acesso

Um administrador interno dá e tira acesso a um projeto pela própria interface. A pessoa
convidada recebe um e-mail, define a senha, confirma o endereço e entra vendo **apenas** o
projeto para o qual foi convidada.

## Objetivo e não objetivos

**Objetivo.** Fechar o único caminho que ainda passava por fora do produto: até aqui, dar
acesso a um cliente novo exigia criar o usuário no Keycloak à mão *e* inserir a `membership`
no banco à mão. O portal tinha login, isolamento e dashboard reais — e nenhuma porta de entrada.

**Não objetivos.** Administrar organizações e projetos: eles nascem do snapshot do Biahflow
(ADR 0006/0008) e criá-los aqui dividiria a fonte da verdade. Configuração financeira, que
migrou para a Fase 3, junto do cálculo de ROI que lhe dá sentido. Central de notificações do
produto (Fase 2) — é outro assunto de e-mail: aviso de pendência, não identidade.

## Jornada e interface

`/admin` mostra quem enxerga o projeto: nome, e-mail, papel e se o convite ainda está pendente.
O formulário pede nome, e-mail e papel; ao enviar, a tela confirma e a pessoa aparece na lista
como **convite pendente**. Quando ela define a senha e confirma o e-mail, o rótulo vira o papel.

O link para a tela aparece no menu de perfil apenas para a equipe interna — ergonomia, não
segurança: quem nega é a API, com 404.

Do lado de quem foi convidado: e-mail do Keycloak em português → página de confirmação → definir
senha → volta para `/login` do portal → entra e vê o projeto.

## Dados, API e permissões

| Endpoint | Regra |
|---|---|
| `GET /api/v1/admin/projects/{id}/members` | `internal_admin` no projeto; lista membros diretos e org-wide |
| `POST /api/v1/admin/projects/{id}/members` | idem; cria conta no realm se faltar, grava `user` + `membership` e dispara o e-mail |
| `DELETE /api/v1/admin/projects/{id}/members/{membership_id}` | idem; remove o vínculo, mantém a pessoa |

Ordem que não é acidental, em uma transação sob o papel `portal_admin`:

1. `resolve_user` + `require_project(…, ADMIN_ONLY)` **antes** de `bind_admin_org`. Nessa
   janela a transação enxerga apenas os vínculos do próprio chamador, como qualquer usuário —
   é o que impede a verificação de responder a si mesma com privilégio.
2. `bind_admin_org` abre a organização; `bind_invitee` abre **uma** linha de `user`, a do
   convidado, endereçada pelo `sub` que o realm acabou de confirmar.
3. Keycloak antes do banco (é dele que vem o `sub`), e o e-mail **depois** do banco: a falha
   inversa — convite recebido para um acesso que não existe — é a que confunde de verdade.

Detalhes e o porquê de cada escolha na ADR 0011.

## Estados de erro e segurança

- **404, nunca 403**, em qualquer negação — inclusive para um vínculo que existe em outro
  projeto. A resposta não distingue "não é seu" de "não existe".
- **Resposta uniforme** no convite para e-mail conhecido e desconhecido: a diferença revelaria
  quem já é cliente do portal.
- **Revogar o próprio acesso é 409.** Sem isso um clique deixaria o administrador fora da
  própria tela, sem como desfazer.
- **502 quando o Keycloak não responde**, sem repassar o corpo dele; o motivo vai para
  `keycloak.failed` no log estruturado.
- **Degrada em vez de derrubar:** se a consulta de e-mails não confirmados falhar, a lista de
  acesso continua e o rótulo "convite pendente" some. Saber quem já entrou é conveniência.
- **Usuário órfão no realm é estado seguro:** se a conta for criada e a transação falhar, a
  pessoa autentica e não vê nada — o comportamento correto desde a ADR 0010 — e reconvidar
  reconcilia.
- Auditoria: `membership.invited` e `membership.revoked` em `audit_log`, com o autor e o
  vínculo, **sem o e-mail** (`docs/data-classification.md`).

## Telemetria e critérios de aceite

1. `client_member` recebe 404 em toda rota de administração, e a chamada nem chega ao provedor
   de identidade. ✔
2. `internal_admin` da organização A recebe 404 num projeto da B. ✔
3. Convite cria conta, vínculo e dispara **um** e-mail; reconvidar não duplica nada. ✔
4. `is_internal` vem do papel da membership, não do realm role. ✔
5. Sem a GUC de administração, o papel `portal_admin` enxerga apenas os próprios vínculos. ✔
6. `portal_app` continua sem escrita em `membership` — verificado no catálogo do Postgres. ✔
7. Convite ponta a ponta: e-mail recebido, senha definida, acesso ao projeto e só a ele. ✔
8. Revogar remove o acesso e mantém a conta. ✔

## Testes e avaliações de IA

- `apps/api/tests/test_admin_rls.py` — a barreira abaixo da aplicação, no papel `portal_admin`
  e com `select()` cru: a janela antes da GUC, o alcance de uma organização só, a escrita
  barrada no tenant vizinho, e o invariante de privilégio que justifica a credencial separada.
- `apps/api/tests/test_admin_endpoints.py` — o contrato pelo stack HTTP real, com o Keycloak
  dublado: negativos de permissão, idempotência, auditoria sem e-mail e degradação quando o
  provedor de identidade cai.
- `apps/api/tests/test_seed_matches_realm.py` — o realm tem SMTP e o service account tem
  `manage-users`; sem isso o convite falha só em produção.
- `tests/e2e/invite.spec.ts` — o fluxo inteiro no navegador, lendo a caixa do Mailpit.

Avaliações de IA: **não se aplica — esta feature não altera prompt, recuperador, modelo ou
ferramenta.**
