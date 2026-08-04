"""Keycloak Admin API — só o que o convite precisa (ADR 0011).

O realm é o registro de identidade; o portal é o registro de acesso. Convidar
alguém é, nesta ordem: garantir que a pessoa existe no realm e pedir ao
**Keycloak** que mande o e-mail de definir senha e verificar endereço. O portal
não escreve template de e-mail para identidade: assunto, idioma e expiração do
link são do Keycloak, e a Fase 2 é que trará um remetente nosso, para
notificação de produto.

**Nenhum realm role é atribuído no convite, de propósito.** A `membership` é a
autoridade e o realm role é só indício, usado quando alguém se autoprovisiona no
primeiro login (ADR 0010) — e o convidado não se autoprovisiona: o portal grava a
linha `user`, com `is_internal` derivado do papel da membership, antes de a
pessoa entrar. Atribuir o role exigiria `view-realm` no service account, que é
permissão a mais para informação que já temos.

Quem fala aqui é um service account próprio (`portal-admin`), separado do client
de login: quem autentica usuário não precisa poder criar usuário.

O endereço é sempre o **interno** — esta é uma conversa servidor-a-servidor, e a
separação público/interno é a mesma de `OIDC_ISSUER`/`OIDC_JWKS_URL` (ADR 0010).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from portal_api.config import Settings

logger = logging.getLogger(__name__)

#: Ações que o convidado precisa completar antes de entrar. `VERIFY_EMAIL` é o
#: que fecha o item de "verificação de e-mail" da Fase 1: sem ele o token sai com
#: `email_verified: false` e `auth.py` recusa (ADR 0010).
INVITATION_ACTIONS = ("UPDATE_PASSWORD", "VERIFY_EMAIL")

#: Margem para não usar um token que vence no meio da requisição.
TOKEN_SKEW_SECONDS = 30


class KeycloakAdminError(RuntimeError):
    """Falha na conversa com o realm.

    O endpoint traduz para um 502 sem corpo do Keycloak: mensagem de servidor de
    identidade não é para o cliente.
    """


@dataclass(frozen=True)
class RealmUser:
    subject: str
    email: str
    email_verified: bool


class KeycloakAdmin:
    """Cliente fino. Um por requisição — o cache de token vive na instância."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=10)
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # -- infraestrutura ----------------------------------------------------

    @property
    def _realm_url(self) -> str:
        base = self._settings.keycloak_internal_url.rstrip("/")
        return f"{base}/realms/{self._settings.keycloak_realm}"

    @property
    def _admin_url(self) -> str:
        base = self._settings.keycloak_internal_url.rstrip("/")
        return f"{base}/admin/realms/{self._settings.keycloak_realm}"

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        response = self._client.post(
            f"{self._realm_url}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._settings.keycloak_admin_client_id,
                "client_secret": self._settings.keycloak_admin_client_secret,
            },
        )
        payload = self._json(response, "token")
        token = payload.get("access_token")
        if not token:
            raise KeycloakAdminError("Keycloak did not return an access token")
        self._token = token
        self._token_expires_at = time.monotonic() + max(
            int(payload.get("expires_in", 60)) - TOKEN_SKEW_SECONDS, 1
        )
        return token

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        return self._client.request(
            method, f"{self._admin_url}{path}", headers=headers, **kwargs
        )

    @staticmethod
    def _json(response: httpx.Response, what: str) -> dict[str, Any]:
        if response.status_code >= 400:
            # O corpo do Keycloak fica no log, nunca na resposta ao chamador.
            logger.warning(
                "keycloak.failed",
                extra={"what": what, "status": response.status_code},
            )
            raise KeycloakAdminError(f"Keycloak {what} failed ({response.status_code})")
        return dict(response.json())

    # -- operações ---------------------------------------------------------

    def find_by_email(self, email: str) -> RealmUser | None:
        response = self._request(
            "GET", "/users", params={"email": email, "exact": "true"}
        )
        if response.status_code >= 400:
            logger.warning("keycloak.failed", extra={"what": "find_by_email"})
            raise KeycloakAdminError("Keycloak user lookup failed")
        found = response.json()
        if not found:
            return None
        user = found[0]
        return RealmUser(
            subject=user["id"],
            email=(user.get("email") or email).lower(),
            email_verified=bool(user.get("emailVerified")),
        )

    def unverified_emails(self) -> set[str]:
        """E-mails do realm que ainda não foram confirmados.

        Uma chamada só, filtrando no próprio Keycloak, em vez de uma por membro:
        é o que permite a tela dizer "convite pendente" sem virar N requisições.
        Falha aqui **não** derruba a listagem — quem chama trata como "não sei",
        porque saber quem já entrou é conveniência, não controle de acesso.
        """
        response = self._request(
            "GET",
            "/users",
            params={"emailVerified": "false", "briefRepresentation": "true", "max": 500},
        )
        if response.status_code >= 400:
            logger.warning("keycloak.failed", extra={"what": "unverified_emails"})
            raise KeycloakAdminError("Keycloak user listing failed")
        return {
            (user.get("email") or "").lower()
            for user in response.json()
            if user.get("email")
        }

    def create_user(self, email: str, full_name: str) -> RealmUser:
        """Cria a conta no realm. O `id` que ela recebe **é** o `sub` do token."""
        first, _, last = full_name.strip().partition(" ")
        response = self._request(
            "POST",
            "/users",
            json={
                "username": email,
                "email": email,
                "firstName": first or email,
                "lastName": last,
                "enabled": True,
                # Falso de propósito: quem verifica é a pessoa, pelo link do
                # convite. Marcar verdadeiro aqui deixaria qualquer e-mail
                # digitado errado virar uma conta que autentica.
                "emailVerified": False,
            },
        )
        if response.status_code >= 400:
            logger.warning(
                "keycloak.failed",
                extra={"what": "create_user", "status": response.status_code},
            )
            raise KeycloakAdminError(f"Keycloak user creation failed ({response.status_code})")

        created = self.find_by_email(email)
        if created is None:
            raise KeycloakAdminError("Keycloak created a user it cannot find")
        return created

    def send_invitation(self, subject: str) -> None:
        """Dispara o e-mail de ações. 204 é a resposta de sucesso do Keycloak."""
        response = self._request(
            "PUT",
            f"/users/{subject}/execute-actions-email",
            params={
                "client_id": self._settings.keycloak_web_client_id,
                "redirect_uri": f"{self._settings.portal_web_url.rstrip('/')}/login",
                "lifespan": self._settings.invitation_lifespan_seconds,
            },
            json=list(INVITATION_ACTIONS),
        )
        if response.status_code >= 400:
            logger.warning(
                "keycloak.failed",
                extra={"what": "send_invitation", "status": response.status_code},
            )
            raise KeycloakAdminError(
                f"Keycloak invitation e-mail failed ({response.status_code})"
            )
