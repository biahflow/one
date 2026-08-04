# Segurança

## Controles

- OIDC Authorization Code com PKCE, cookies `HttpOnly`, `Secure` e `SameSite`.
- Papéis mínimos e acesso explícito a cada projeto.
- RLS no PostgreSQL, checagem de autorização na API e testes negativos de BOLA/IDOR.
- TLS em produção, URLs de arquivo temporárias, validação de upload e varredura antimalware antes de indexar.
- Tokens de integração armazenados cifrados; chaves da API de agentes ficam apenas como hash, possuem escopo, expiração e rotação.
- Limites de taxa em autenticação, chat, upload e API de eventos.
- Segredos apenas no ambiente; `.env` é ignorado e `.env.example` não possui dados reais.
- Auditoria para login, permissão, download, sincronização, evento de agente, alteração de métrica e ação de IA.

## O que já está implementado (ADR 0010)

- **Claims validadas** em todo endpoint de cliente: assinatura RS256 contra o JWKS do realm,
  `iss`, `aud`, `exp`/`iat` (com folga de relógio), `email_verified` e `azp` na allowlist. Toda
  falha vira o **mesmo 401 opaco**; o motivo só aparece no log estruturado (`auth.rejected`),
  para não virar oráculo de sondagem.
- **Matriz de papéis.** A `membership` decide o acesso; o realm role é indício e serve apenas
  para marcar `is_internal`. `client_member` lê o próprio projeto; `internal_admin` é exigido
  para publicar eventos de agente. Negação é sempre **404, nunca 403**.
- **Fail-closed no banco.** As policies leem o contexto de GUCs da transação; contexto ausente
  devolve zero linhas. O papel da aplicação (`portal_app`) não é superusuário nem tem
  `BYPASSRLS` — há teste que falha se alguém apontar a aplicação para uma credencial que tenha.
- **Auditoria.** `membership.invited` e `membership.revoked` com o autor e o vínculo, **sem o
  e-mail**; `chat.pending_created` em `audit_log` com o autor (e sem o texto da pergunta);
  `identity.linked` e `identity.provisioned` em log estruturado, porque no primeiro login ainda
  não há organização.
- **Sessão no navegador.** O BFF é um client confidencial: o code exchange (PKCE) acontece no
  servidor e o access token fica no cookie cifrado do Auth.js, **fora** do objeto `session` e
  portanto fora de qualquer bundle. `proxy.ts` fecha tudo que não é `/login`, respondendo 401
  em `/api/` para que um `fetch` não receba a tela de login como se fosse dado. Sair apaga o
  cookie **e** encerra a sessão de SSO no Keycloak (logout RP-initiated).
- **Rate limit em autenticação:** `bruteForceProtected` no realm — o Keycloak bloqueia a conta
  após tentativas seguidas, sem código nosso.
- **Fim do fallback demo.** 401, 404, rede e 5xx deixaram de virar dashboard fabricado. A casca
  de demonstração exige, ao mesmo tempo, nenhuma API configurada **e** `DEMO_MODE=true`
  (`app/lib/demo.ts`), e um teste falha se `DEMO_OVERVIEW` for alcançável fora desse gate.
- **Convite e verificação de e-mail (ADR 0011).** Quem manda o e-mail é o Keycloak
  (`UPDATE_PASSWORD` + `VERIFY_EMAIL` numa ação só), por um service account separado do client
  de login — quem autentica usuário não precisa poder criá-lo. A resposta do convite é uniforme
  para e-mail conhecido e desconhecido, para não virar oráculo de "quem já é cliente".
- **Escrita em `membership` só pelo papel `portal_admin`**, que é `NOBYPASSRLS` e alcança uma
  organização por vez, via GUC publicada depois da verificação. O papel do caminho de
  requisição não tem o privilégio, e há teste que consulta o catálogo para garantir.
- **Ainda aberto:** revisão das dependências apontadas pelo `npm audit` antes de produção
  (Fase 5).

## Dados e IA

Documentos são conteúdo não confiável. O recuperador trata texto de fonte como dados, nunca como instruções. O modelo recebe apenas chunks permitidos para o projeto corrente e não recebe segredos. Ações futuras via ferramenta exigem allowlist e confirmação humana.

## Incidentes

Siga `docs/runbooks/incident-response.md`. Uma suspeita de vazamento exige revogar sessões/chaves, bloquear conectores afetados, preservar logs e comunicar o responsável pelo tenant.
