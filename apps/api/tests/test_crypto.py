"""Cifra do refresh token do Drive (ADR 0016).

Três propriedades, e cada uma existe por um motivo diferente:

* o segredo **volta em claro** — é o que ``agent_auth`` não podia oferecer, e a
  razão de o módulo existir;
* o segredo está **amarrado ao tenant** — ``portal_admin`` escreve nesta tabela, e
  um ciphertext sem AAD é copiável de uma linha para outra;
* a falha é **fechada** — um módulo de cifra que degrada em silêncio para "guarda
  em claro" é pior do que não existir.
"""

from __future__ import annotations

import uuid

import pytest

from portal_api.config import Settings
from portal_api.crypto import (
    SealedSecretError,
    aad_for,
    generate_key,
    needs_resealing,
    seal,
    unseal,
)

TOKEN = "1//0gK-refresh-token-do-google-com-tamanho-realista-e-tudo"
ORG = uuid.UUID("11111111-1111-4111-8111-111111111111")
PROJECT = uuid.UUID("22222222-2222-4222-8222-222222222222")
AAD = aad_for(ORG, PROJECT)


def _settings(key: str | None = None, previous: str = "") -> Settings:
    return Settings(
        drive_token_encryption_key=key if key is not None else generate_key(),
        drive_token_encryption_key_previous=previous,
    )


def test_a_sealed_secret_comes_back() -> None:
    """A propriedade que o HMAC da chave de agente não tem, e por isso este módulo existe."""
    settings = _settings()

    assert unseal(seal(TOKEN, aad=AAD, settings=settings), aad=AAD, settings=settings) == TOKEN


def test_the_sealed_text_does_not_contain_the_secret() -> None:
    assert TOKEN not in seal(TOKEN, aad=AAD, settings=_settings())


def test_sealing_twice_produces_different_text() -> None:
    """Nonce por selagem: dois projetos com o mesmo token não se parecem no banco."""
    settings = _settings()

    assert seal(TOKEN, aad=AAD, settings=settings) != seal(TOKEN, aad=AAD, settings=settings)


def test_a_ciphertext_moved_to_another_project_does_not_open() -> None:
    """O AAD é a segunda barreira: a RLS impede ler, isto impede reaproveitar."""
    settings = _settings()
    sealed = seal(TOKEN, aad=AAD, settings=settings)
    other = aad_for(ORG, uuid.UUID("33333333-3333-4333-8333-333333333333"))

    with pytest.raises(SealedSecretError, match="does not open"):
        unseal(sealed, aad=other, settings=settings)


def test_a_ciphertext_moved_to_another_organization_does_not_open() -> None:
    settings = _settings()
    sealed = seal(TOKEN, aad=AAD, settings=settings)
    other = aad_for(uuid.UUID("44444444-4444-4444-8444-444444444444"), PROJECT)

    with pytest.raises(SealedSecretError, match="does not open"):
        unseal(sealed, aad=other, settings=settings)


def test_without_a_key_nothing_seals_and_nothing_opens() -> None:
    """Falha fechada, como `hash_key` sem pepper — nunca um fallback em claro."""
    settings = _settings("")

    with pytest.raises(SealedSecretError, match="not configured"):
        seal(TOKEN, aad=AAD, settings=settings)
    with pytest.raises(SealedSecretError, match="not configured"):
        unseal("v1.abcdef12.nonce.ct", aad=AAD, settings=settings)


def test_a_malformed_key_is_a_configuration_error_and_not_a_crash() -> None:
    with pytest.raises(SealedSecretError, match="malformed"):
        seal(TOKEN, aad=AAD, settings=_settings("chave-curta-demais"))


def test_the_previous_key_still_opens_what_it_sealed() -> None:
    """Sem esta janela, girar a chave obrigaria cada projeto a refazer o consentimento."""
    old = generate_key()
    sealed = seal(TOKEN, aad=AAD, settings=_settings(old))

    rotated = _settings(generate_key(), previous=old)

    assert unseal(sealed, aad=AAD, settings=rotated) == TOKEN


def test_what_the_previous_key_sealed_is_flagged_for_resealing() -> None:
    """É o que faz a rotação terminar sozinha, no sync seguinte."""
    old = generate_key()
    sealed = seal(TOKEN, aad=AAD, settings=_settings(old))
    rotated = _settings(generate_key(), previous=old)

    assert needs_resealing(sealed, rotated) is True
    assert needs_resealing(seal(TOKEN, aad=AAD, settings=rotated), rotated) is False


def test_a_key_that_was_dropped_says_so_instead_of_failing_obscurely() -> None:
    """Banco restaurado noutro ambiente: o erro tem de apontar para "reconecte"."""
    sealed = seal(TOKEN, aad=AAD, settings=_settings())

    with pytest.raises(SealedSecretError, match="unknown key"):
        unseal(sealed, aad=AAD, settings=_settings())


def test_a_tampered_text_does_not_open() -> None:
    """GCM autentica: mexer no ciphertext devolve erro, não lixo."""
    settings = _settings()
    sealed = seal(TOKEN, aad=AAD, settings=settings)
    tampered = sealed[:-4] + ("aaaa" if not sealed.endswith("aaaa") else "bbbb")

    with pytest.raises(SealedSecretError):
        unseal(tampered, aad=AAD, settings=settings)


def test_a_text_in_another_format_is_refused_before_any_key_is_tried() -> None:
    with pytest.raises(SealedSecretError, match="expected format"):
        unseal("apenas-uma-string", aad=AAD, settings=_settings())
