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
  após tentativas seguidas (`failureFactor: 30`), sem código nosso. O que está **desligado** é
  só a heurística de *quick login* (`quickLoginCheckMilliSeconds: 0`): por padrão ela trava a
  conta por 60s quando dois logins do mesmo usuário chegam a menos de um segundo um do outro,
  ainda que nenhum tenha falhado. Isso não é defesa contra adivinhação de senha — o contador de
  falhas é — e derruba o e2e, que autentica o mesmo administrador em specs seguidos.
- **Rate limit na API de eventos (ADR 0013):** janela deslizante por chave, contada na própria
  linha da chave no Postgres. Estourar responde **429 com `Retry-After`**, e não 401, porque o
  produtor precisa distinguir ritmo de credencial — senão retenta para sempre.
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

## Credencial de terceiro em repouso (ADR 0016)

O refresh token do Google Drive é o único segredo do portal que precisa **voltar em claro** — ele é reapresentado ao provedor a cada sincronização, e por isso o HMAC sob pepper da ADR 0013 não serve aqui. Ele é selado com AES-256-GCM sob `DRIVE_TOKEN_ENCRYPTION_KEY`, que vive só no ambiente e nunca no banco que protege; o dado associado carrega organização e projeto, de modo que um ciphertext copiado para outra linha falha a decifra em vez de sincronizar a pasta errada. Sem a chave configurada, nenhuma conexão do Drive funciona — falha fechada.

O escopo é `drive.readonly` e só ele: se o Google conceder um conjunto diferente, a conexão é recusada sem nada ser gravado. O token não aparece em nenhuma resposta da API nem no `audit_log`. Girar a chave exige passar a anterior em `DRIVE_TOKEN_ENCRYPTION_KEY_PREVIOUS` — sem essa janela, todo projeto precisa refazer o consentimento.

## Dados e IA

Documentos são conteúdo não confiável. O recuperador trata texto de fonte como dados, nunca como instruções. O modelo recebe apenas chunks permitidos para o projeto corrente e não recebe segredos. Ações futuras via ferramenta exigem allowlist e confirmação humana.

## Incidentes

Siga `docs/runbooks/incident-response.md`. Uma suspeita de vazamento exige revogar sessões/chaves, bloquear conectores afetados, preservar logs e comunicar o responsável pelo tenant.
