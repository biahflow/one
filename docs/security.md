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

## Dados e IA

Documentos são conteúdo não confiável. O recuperador trata texto de fonte como dados, nunca como instruções. O modelo recebe apenas chunks permitidos para o projeto corrente e não recebe segredos. Ações futuras via ferramenta exigem allowlist e confirmação humana.

## Incidentes

Siga `docs/runbooks/incident-response.md`. Uma suspeita de vazamento exige revogar sessões/chaves, bloquear conectores afetados, preservar logs e comunicar o responsável pelo tenant.
