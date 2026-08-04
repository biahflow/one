"""Token validation without a Keycloak (ADR 0010).

A real RSA pair is generated here and the JWKS client is stubbed to hand back the
public half, so every branch of ``portal_api.auth`` is exercised offline — the CI
job needs no realm, and the assertions are deterministic.

The cases are the ones that matter for a resource server: a token from another
issuer, for another audience, expired, unsigned, or signed with the *wrong kind*
of key. That last one is the algorithm-confusion attack, and it is the reason the
algorithm allowlist is not optional.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from starlette.requests import Request

from portal_api import auth
from portal_api.config import get_settings

KID = "portal-local-test"
SETTINGS = get_settings()


@pytest.fixture(scope="module")
def keypair() -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


@pytest.fixture
def jwks(keypair: tuple[bytes, bytes], monkeypatch: pytest.MonkeyPatch):
    """Stand in for ``PyJWKClient``, optionally failing like an unknown ``kid``."""
    _, public_pem = keypair

    def _install(error: Exception | None = None) -> None:
        def _client(*_args: Any, **_kwargs: Any) -> Any:
            def get_signing_key_from_jwt(_token: str) -> Any:
                if error is not None:
                    raise error
                return SimpleNamespace(key=public_pem)

            return SimpleNamespace(get_signing_key_from_jwt=get_signing_key_from_jwt)

        monkeypatch.setattr(auth, "_jwks_client", _client)

    _install()
    return _install


def _claims(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "sub": "6b1f0f2a-0000-4000-8000-000000000001",
        "iss": SETTINGS.oidc_issuer,
        "aud": SETTINGS.oidc_audience,
        "azp": "portal-web",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "email": "Marina.Farias@acme.com.br",
        "email_verified": True,
        "name": "Marina Farias",
        "realm_access": {"roles": ["client_member"]},
        **overrides,
    }


def _token(private_pem: bytes, **overrides: Any) -> str:
    return jwt.encode(
        _claims(**overrides), private_pem, algorithm="RS256", headers={"kid": KID}
    )


def _request(token: str | None) -> Request:
    headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def _rejects(token: str | None) -> None:
    with pytest.raises(HTTPException) as excinfo:
        auth.bearer_principal(_request(token))

    assert excinfo.value.status_code == 401
    # The body never says *why*: the reason would be a probing oracle.
    assert excinfo.value.detail == "Not authenticated"


# --- the happy path -------------------------------------------------------


def test_a_valid_token_becomes_a_principal(keypair, jwks) -> None:
    private_pem, _ = keypair

    principal = auth.bearer_principal(_request(_token(private_pem)))

    assert principal.subject == "6b1f0f2a-0000-4000-8000-000000000001"
    # Normalized, because the e-mail is compared against `lower(email)` both in
    # the RLS predicate and when linking a seeded row.
    assert principal.email == "marina.farias@acme.com.br"
    assert principal.full_name == "Marina Farias"
    assert principal.is_internal is False


def test_a_realm_role_marks_internal_staff(keypair, jwks) -> None:
    private_pem, _ = keypair
    token = _token(private_pem, realm_access={"roles": ["internal_admin"]})

    assert auth.bearer_principal(_request(token)).is_internal is True


# --- rejections -----------------------------------------------------------


def test_a_request_without_a_bearer_token_is_rejected(jwks) -> None:
    _rejects(None)


def test_a_token_from_another_issuer_is_rejected(keypair, jwks) -> None:
    private_pem, _ = keypair

    _rejects(_token(private_pem, iss="https://evil.example/realms/portal-local"))


def test_a_token_for_another_audience_is_rejected(keypair, jwks) -> None:
    private_pem, _ = keypair

    _rejects(_token(private_pem, aud="account"))


def test_an_expired_token_is_rejected(keypair, jwks) -> None:
    private_pem, _ = keypair
    long_gone = datetime.now(UTC) - timedelta(hours=1)

    _rejects(_token(private_pem, exp=int(long_gone.timestamp())))


def test_a_token_missing_required_claims_is_rejected(keypair, jwks) -> None:
    private_pem, _ = keypair
    claims = _claims()
    del claims["iat"]

    _rejects(jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": KID}))


def test_an_unsigned_token_is_rejected(keypair, jwks) -> None:
    """``alg: none`` — the oldest trick, and the allowlist is what stops it."""
    _rejects(jwt.encode(_claims(), key="", algorithm="none"))


def test_a_token_signed_with_the_public_key_as_hmac_secret_is_rejected(
    keypair, jwks
) -> None:
    """Algorithm confusion: HS256 using the *public* key as the shared secret.

    Handcrafted because PyJWT refuses to produce it — which is the point: only an
    attacker builds this, and a server that accepted `algorithms=[...]` from the
    header would verify it happily.
    """
    _, public_pem = keypair

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
    payload = b64(json.dumps(_claims()).encode())
    signature = hmac.new(
        public_pem, f"{header}.{payload}".encode(), hashlib.sha256
    ).digest()

    _rejects(f"{header}.{payload}.{b64(signature)}")


def test_an_unknown_key_id_is_rejected(keypair, jwks) -> None:
    private_pem, _ = keypair
    jwks(error=jwt.exceptions.PyJWKClientError("no key for kid"))

    _rejects(_token(private_pem))


def test_an_unverified_email_is_rejected(keypair, jwks) -> None:
    """The e-mail links a token to a seeded row, so an unverified one would let
    anyone claim someone else's pending invitation."""
    private_pem, _ = keypair

    _rejects(_token(private_pem, email_verified=False))


def test_a_token_from_an_unexpected_client_is_rejected(keypair, jwks) -> None:
    private_pem, _ = keypair

    _rejects(_token(private_pem, azp="some-other-app"))
