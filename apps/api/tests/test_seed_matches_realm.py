"""The realm import and the seed have to describe the same three people.

Keycloak's user ``id`` becomes the ``sub`` claim, and the seed writes that value
into ``User.external_subject`` — so a UUID edited on one side and not the other
produces a user who authenticates and then matches no row, which surfaces much
later as "everyone sees 404". This test is the tripwire: it runs in the unit
suite, with no Keycloak and no Postgres.
"""

from __future__ import annotations

import json
from pathlib import Path

from portal_api.models import MemberRole
from portal_api.seed import SEED_USERS, load_snapshot

REALM_PATH = (
    Path(__file__).resolve().parents[3] / "infra" / "keycloak" / "portal-local-realm.json"
)


def _realm() -> dict:
    return json.loads(REALM_PATH.read_text(encoding="utf-8"))


def _people() -> list[dict]:
    """Usuários de verdade — service accounts não têm `sub` nem entram no seed."""
    return [u for u in _realm()["users"] if "serviceAccountClientId" not in u]


def test_realm_users_match_the_seed_one_to_one() -> None:
    realm_users = {user["id"]: user for user in _people()}
    seeded = {user.subject: user for user in SEED_USERS}

    assert realm_users.keys() == seeded.keys(), "realm e SEED_USERS divergem no `sub`"

    for subject, seed_user in seeded.items():
        realm_user = realm_users[subject]
        assert realm_user["email"] == seed_user.email
        assert realm_user["emailVerified"] is True, "sem e-mail verificado o token é rejeitado"
        assert (
            f"{realm_user['firstName']} {realm_user['lastName']}" == seed_user.full_name
        )
        # O realm role é indício de papel; a autoridade é a membership (ADR 0010).
        # Ainda assim os dois vocabulários são 1:1 e precisam continuar assim.
        assert realm_user["realmRoles"] == [seed_user.role.value]


def test_local_realm_is_declared_http_only() -> None:
    """`sslRequired: none` é deliberado — e só vale para este realm de desenvolvimento.

    A stack local inteira é HTTP (`KC_HOSTNAME: http://localhost:8080`). Sem esta
    declaração o Keycloak decide por heurística de "requisição local", e quem chega
    pelo gateway do Docker leva "HTTPS required" — o login quebra num ambiente e
    funciona em outro. Produção usa TLS (`docs/security.md`); este arquivo não é o
    realm de produção.
    """
    assert _realm()["sslRequired"] == "none"


def test_realm_declares_the_three_roles_of_the_enum() -> None:
    realm_roles = {role["name"] for role in _realm()["roles"]["realm"]}
    assert realm_roles == {role.value for role in MemberRole}


def test_web_client_is_confidential_and_mints_the_api_audience() -> None:
    clients = {client["clientId"]: client for client in _realm()["clients"]}

    web = clients["portal-web"]
    assert web["publicClient"] is False, "o code exchange acontece no BFF, com secret"
    assert web["secret"], "client confidencial sem secret não fecha o fluxo"
    assert "post.logout.redirect.uris" in web["attributes"], "logout RP-initiated exige a URI"

    # Sem este mapper o `aud` do access token é `account` e a API rejeita 100%
    # dos tokens — é a falha mais provável de toda a configuração do realm.
    audiences = {
        mapper["config"]["included.client.audience"]
        for mapper in web["protocolMappers"]
        if mapper["protocolMapper"] == "oidc-audience-mapper"
    }
    assert "portal-api" in audiences


def test_invitation_needs_its_own_client_smtp_and_permissions() -> None:
    """O convite depende de três coisas cuja falta só aparece em produção.

    Sem SMTP o Keycloak aceita o pedido e ninguém recebe nada; sem
    `manage-users` a criação falha; e o client do convite tem de ser separado do
    `portal-web`, porque quem autentica usuário não precisa poder criá-lo.
    """
    realm = _realm()

    assert realm["smtpServer"]["host"], "sem SMTP o convite é enviado para lugar nenhum"

    clients = {client["clientId"]: client for client in realm["clients"]}
    admin = clients["portal-admin"]
    assert admin["serviceAccountsEnabled"] is True
    assert admin["standardFlowEnabled"] is False, "não é client de login de usuário"

    service_account = next(
        user
        for user in realm["users"]
        if user.get("serviceAccountClientId") == "portal-admin"
    )
    assert set(service_account["clientRoles"]["realm-management"]) == {
        "manage-users",
        "view-users",
    }
    assert "manage-users" not in str(clients["portal-web"]), "o client de login não administra"


def test_seed_snapshot_is_loadable_and_shaped_like_a_biahflow_payload() -> None:
    snapshot = load_snapshot()
    assert snapshot["project"]["client"]["name"]
    assert snapshot["milestones"] and snapshot["journey"]["phases"]
