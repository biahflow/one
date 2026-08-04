# ADR 0011 — Administração de acesso: quem pode escrever `membership`

**Status:** Aceito — 04/08/2026

## Contexto

A ADR 0010 fechou a identidade e o isolamento, e fechou bem demais para o que vem agora: não
há como **conceder** acesso.

- `membership_self_read` é `USING (user_id = portal.current_user_id())`. Um `internal_admin`
  não enxerga o vínculo de mais ninguém — nem para listar.
- O papel `portal_app` tem apenas `SELECT` em `membership`. Escrita ali não existe para o
  caminho de requisição.

Isso não foi acidente: a `membership` é a tabela que decide todo o resto, e o padrão certo para
ela é ninguém escrever. Só que o resultado prático é que dar acesso a um cliente novo exige
criar o usuário no Keycloak à mão e inserir a linha no banco à mão — o portal não consegue
receber ninguém. O PRD já previa o papel ("Administrador interno: administra organizações,
acessos, integrações e auditoria") e o `ROADMAP.md` tinha os dois itens abertos da Fase 1.

Duas restrições vindas de decisões anteriores moldam a solução:

1. **O catálogo não é nosso.** Organização e projeto nascem do snapshot do Biahflow
   (ADR 0006/0008). Administrar projetos no portal dividiria a fonte da verdade, exatamente o
   que a ADR 0008 recusou para status. O portal administra **acesso**, não catálogo.
2. **Privilégio mora na credencial.** A ADR 0010 preferiu `BYPASSRLS` no papel a uma GUC de
   escape justamente porque credencial é auditável por `SELECT rolname FROM pg_roles`, e
   código não é.

## Decisão

### 1. Um quarto papel, `portal_admin`, e não mais grants no `portal_app`

A alternativa óbvia — dar `INSERT/UPDATE/DELETE` em `membership` ao `portal_app` e proteger com
uma GUC — falha no ponto que importa: qualquer bug em qualquer endpoint passaria a poder
escrever controle de acesso, com só uma verificação de aplicação no caminho. Com a credencial
separada, o caminho de requisição **não tem o grant**, e a barreira deixa de depender de
disciplina de código.

`portal_admin` é `NOBYPASSRLS`. Ele não escapa da RLS — recebe policies próprias.

| Papel | Para quê | `membership` |
|---|---|---|
| `portal_app` | caminho de requisição | `SELECT` do próprio vínculo |
| `portal_system` | webhook, sync, seed (`BYPASSRLS`) | CRUD, por criar o tenant |
| `portal_migrator` | dono do schema | DDL |
| **`portal_admin`** | `/api/v1/admin/*` | **CRUD dentro da organização administrada** |

### 2. Terceiro estágio de GUC, publicado *depois* da verificação

`portal.admin_organization_id`, emitida por `bind_admin_org` **somente após** `require_project(…,
ADMIN_ONLY)` confirmar que o chamador tem `internal_admin` ali. Antes disso a GUC é NULL, os
predicados de admin são NULL, e a transação enxerga o que qualquer outro chamador enxergaria:
os próprios vínculos, por `membership_self_read`. É isso que torna a verificação confiável em
vez de circular — ela roda com o alcance de um usuário comum.

Uma quarta GUC, `portal.invitee_subject`, abre exatamente **uma** linha de `user`: a da pessoa
sendo convidada, endereçada pelo `sub` que o realm acabou de confirmar. Sem ela, um convite a
quem já tem conta por outra organização colidiria no e-mail único e seria impossível de
resolver; com um predicado por e-mail livre, o endpoint viraria um diretório de todos os
usuários do portal.

### 3. As policies existem apenas para o papel de administração

Toda policy da migração `0008` é `TO portal_admin`. Não é só que o `portal_app` não tem o
grant — a policy **não se aplica a ele**, então um `set_config` perdido no caminho de
requisição não alcança nada. O bloco inteiro é condicional à existência do papel, como os
grants da `0007`: um banco que nunca rodou `roles.sql` simplesmente não tem caminho de
administração.

Os predicados de `membership` continuam comparações puras de GUC, sem subquery — `project` e
`organization` fazem subquery em `membership`, e uma policy de `membership` que consultasse de
volta recursaria.

### 4. O Keycloak manda o e-mail; o portal não escreve template de identidade

O convite usa `execute-actions-email` com `UPDATE_PASSWORD` e `VERIFY_EMAIL`: resolve convite e
verificação de uma vez, com template e expiração do próprio Keycloak. Um client de service
account separado (`portal-admin`, com `manage-users`) faz isso — **não** o `portal-web`: quem
autentica usuário não precisa poder criar usuário.

O Admin API devolve o id do usuário criado, que *é* o `sub`. A linha `user` já nasce com
`external_subject`, como no seed; o vínculo por e-mail de `identity._claim_seeded_row` continua
existindo como rede de segurança, não como caminho principal.

## Consequências

- **O portal administra acesso, nunca o catálogo.** Não há (e não deve haver) tela para criar
  organização ou projeto: isso é Biahflow. O item de "configuração financeira" do ROADMAP muda
  de fase — investimento e valor-hora pertencem à Fase 3.
- **Uma credencial a mais para operar:** `DATABASE_ADMIN_URL` no compose, no CI e no
  `.env.example`, e a senha correspondente no `roles.sql`. Papéis são objetos de cluster e não
  entram no `pg_dump` — o `docs/runbooks/backup-restore.md` já cobra rodar o `roles.sql` antes
  de restaurar, e agora são quatro papéis.
- **Um teste passa a guardar o invariante:** `portal_app` não pode ganhar escrita em
  `membership`. Se ganhar, o quarto papel virou decoração, e a suíte falha.
- **Convite é idempotente e de resposta uniforme.** Repetir o convite não duplica vínculo, e a
  resposta não distingue e-mail conhecido de desconhecido — a diferença revelaria quem já é
  cliente.
- **Um usuário órfão no realm é estado seguro.** Se o convite criar a conta no Keycloak e a
  transação do banco falhar, a pessoa autentica e não vê nada — que é o comportamento correto
  desde a ADR 0010 — e o convite repetido reconcilia.
- **Não substitui a ADR 0010**, complementa: os dois primeiros estágios de GUC, os 404 em vez
  de 403 e a `membership` como autoridade seguem valendo palavra por palavra.
