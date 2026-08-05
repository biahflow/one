"""Bearer token validation — the API as an OIDC resource server (ADR 0010).

The BFF does the Authorization Code + PKCE dance and forwards the access token
server-to-server; here we only *verify* it. Nothing in this module talks to
Keycloak except the JWKS endpoint, and ``PyJWKClient`` already caches those keys
and refetches when an unknown ``kid`` shows up.

Every rejection is the same opaque 401: the reason goes to the log, never to the
response body, so a caller cannot use the error to probe which claim failed.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer

from portal_api.config import Settings, get_settings
from portal_api.principal import Principal

logger = logging.getLogger(__name__)

#: Existe **só para o esquema** (ADR 0020): é o que faz o OpenAPI publicar um
#: ``securityScheme`` e o `/docs` mostrar o cadeado em toda rota que depende de
#: ``CurrentPrincipal`` — as treze de `main.py` e as vinte e três de `admin.py`,
#: sem tocar em nenhuma delas.
#:
#: ``auto_error=False`` é o que o mantém decorativo: ele nunca levanta, nunca
#: decide nada e nunca vê o token. Quem recusa continua sendo ``_bearer_token``
#: logo abaixo, com o 401 opaco de sempre. Trocar a validação por esta classe
#: mudaria a resposta — o ``HTTPBearer`` de erro automático responde 403 num
#: header ausente, e neste projeto 403 não existe.
_bearer_scheme = HTTPBearer(
    scheme_name="OIDCBearer",
    auto_error=False,
    description="Access token do OIDC, encaminhado pelo BFF (ADR 0010).",
)

# Claims without which the token is not evaluable at all. `aud` and `iss` are
# also checked by value below; requiring them here means a token that simply
# omits them is rejected instead of silently skipping the comparison.
REQUIRED_CLAIMS = ["exp", "iat", "sub", "aud", "iss"]


def _unauthorized(reason: str, **context: Any) -> HTTPException:
    logger.warning("auth.rejected", extra={"reason": reason, **context})
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache
def _jwks_client(jwks_url: str, cache_seconds: int) -> jwt.PyJWKClient:
    """One client per JWKS URL, so the key cache survives across requests."""
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=cache_seconds)


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("missing_bearer_token")
    return token.strip()


def _claims(token: str, settings: Settings) -> dict[str, Any]:
    try:
        signing_key = _jwks_client(
            settings.oidc_jwks_url, settings.oidc_jwks_cache_seconds
        ).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            # The allowlist is what defeats algorithm confusion: a token signed
            # HS256 with the public key as the secret never reaches verification.
            algorithms=list(settings.oidc_algorithms),
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            leeway=settings.oidc_leeway_seconds,
            options={"require": REQUIRED_CLAIMS},
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - every failure is the same 401
        raise _unauthorized("invalid_token", error=type(exc).__name__) from exc


def _principal(claims: dict[str, Any], settings: Settings) -> Principal:
    subject = claims.get("sub") or ""
    email = (claims.get("email") or "").strip().lower()

    if not email or claims.get("email_verified") is not True:
        # The email is what links a token to a seeded user row, so an unverified
        # address would let anyone claim someone else's pending invitation.
        raise _unauthorized("email_not_verified", subject=subject)

    authorized_party = claims.get("azp")
    if settings.oidc_allowed_azp and authorized_party not in settings.oidc_allowed_azp:
        raise _unauthorized("unexpected_azp", subject=subject, azp=authorized_party)

    realm_roles = claims.get("realm_access", {}).get("roles", [])
    return Principal(
        subject=subject,
        email=email,
        full_name=claims.get("name") or email,
        realm_roles=frozenset(realm_roles),
    )


def bearer_principal(
    request: Request, _scheme: object = Depends(_bearer_scheme)
) -> Principal:
    """The verified caller, or 401.

    ``get_settings()`` is called here rather than captured at import time so the
    tests can repoint the issuer/audience with a monkeypatch — ``main.py`` binds
    ``settings`` at import and that copy would be stale.

    ``_scheme`` é ignorado de propósito: ele está na assinatura para o FastAPI
    registrar o esquema de segurança no OpenAPI (ver ``_bearer_scheme``). O
    token continua saindo do header por ``_bearer_token``, que é o único que
    decide.
    """
    settings = get_settings()
    return _principal(_claims(_bearer_token(request), settings), settings)


CurrentPrincipal = Annotated[Principal, Depends(bearer_principal)]
