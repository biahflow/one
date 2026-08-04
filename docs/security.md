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
- **Auditoria.** `chat.pending_created` em `audit_log` com o autor (e sem o texto da pergunta);
  `identity.linked` e `identity.provisioned` em log estruturado, porque no primeiro login ainda
  não há organização.
- **Ainda aberto nesta fase:** rate limit em autenticação (será `bruteForceProtected` no realm),
  sessão no navegador e o fim do fallback demo do BFF.

## Dados e IA

Documentos são conteúdo não confiável. O recuperador trata texto de fonte como dados, nunca como instruções. O modelo recebe apenas chunks permitidos para o projeto corrente e não recebe segredos. Ações futuras via ferramenta exigem allowlist e confirmação humana.

## Incidentes

Siga `docs/runbooks/incident-response.md`. Uma suspeita de vazamento exige revogar sessões/chaves, bloquear conectores afetados, preservar logs e comunicar o responsável pelo tenant.
