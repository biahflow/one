"""The authenticated caller, as proven by the OIDC access token (ADR 0010).

Kept in its own module so that ``db.session`` can bind a principal to a
transaction without importing the JWT machinery in ``portal_api.auth``.
"""

from __future__ import annotations

from dataclasses import dataclass

INTERNAL_REALM_ROLES = frozenset({"internal_admin", "internal_member"})


@dataclass(frozen=True)
class Principal:
    """Claims we trust after signature, issuer, audience and expiry checks.

    ``subject`` is the Keycloak ``sub`` and is the durable identity — it maps to
    ``User.external_subject``. ``email`` is only used to *link* a seeded row that
    has no subject yet, and never as an identity on its own.
    """

    subject: str
    email: str
    full_name: str
    realm_roles: frozenset[str] = frozenset()

    @property
    def is_internal(self) -> bool:
        """Whether the realm marks this caller as staff.

        Only a hint, used when provisioning the user row. Authorization always
        comes from ``membership`` — a realm role cannot say *which project*.
        """
        return bool(self.realm_roles & INTERNAL_REALM_ROLES)
