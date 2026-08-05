"""Adapter do Google Drive: OAuth, travessia e download (ADR 0016).

O que estes testes protegem é a fronteira. "Apenas conteúdo da pasta autorizada é
sincronizado e indexado" (FDD 003) é uma frase de produto; aqui ela vira asserção
sobre quais bytes o portal chegou a pedir. Nenhum deles toca banco, Celery ou
rede — o Drive é um acervo de mentira com contador de downloads.
"""

from __future__ import annotations

import pytest

from portal_api.config import Settings
from portal_api.integrations import google_drive as drive
from drive_fake import DOC_MIME, SHEET_MIME, SHORTCUT_MIME, FakeDrive, FakeFile

ROOT = "folder-autorizada"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "google_drive_client_id": "client-id",
        "google_drive_client_secret": "client-secret",
        "google_drive_api_base_url": "http://drive/drive/v3",
        "google_oauth_token_url": "http://drive/token",
        "google_drive_redirect_uri": "http://localhost:3000/admin/conhecimento/drive-callback",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _drive_with_one_contract() -> FakeDrive:
    fake = FakeDrive()
    fake.folder(ROOT, "Contratos")
    fake.add(
        FakeFile(
            id="contrato",
            name="contrato.txt",
            mime_type="text/plain",
            parents=[ROOT],
            content=b"O contrato preve suporte por 12 meses.",
        )
    )
    return fake


# --- configuração e OAuth --------------------------------------------------------


def test_without_credentials_the_connector_fails_closed() -> None:
    """Como `StorageDisabled`, e não como o embedder: um "Drive offline" não seria
    o Drive de ninguém, então não há caminho degradado que signifique algo."""
    with pytest.raises(drive.DriveDisabled):
        drive.authorize_url(_settings(google_drive_client_id=""), state="s", code_verifier="v")


def test_the_consent_url_asks_for_offline_access_and_forces_the_prompt() -> None:
    """Sem `prompt=consent`, uma reconexão volta sem refresh token — e o erro só
    aparece no primeiro sync, longe da causa."""
    url = drive.authorize_url(_settings(), state="estado", code_verifier="verificador")

    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "code_challenge_method=S256" in url
    assert "state=estado" in url
    assert "drive.readonly" in url
    # O verificador do PKCE nunca viaja: só o desafio.
    assert "verificador" not in url


def test_a_broader_granted_scope_is_not_accepted() -> None:
    """O Google pode conceder diferente do que foi pedido; aceitar "mais do que
    pedi" faria do escopo readonly uma intenção em vez de um controle."""
    settings = _settings()

    assert drive.scope_is_exactly_readonly(settings.google_drive_scope, settings) is True
    assert (
        drive.scope_is_exactly_readonly("https://www.googleapis.com/auth/drive", settings) is False
    )
    assert (
        drive.scope_is_exactly_readonly(
            f"{settings.google_drive_scope} https://www.googleapis.com/auth/gmail.readonly",
            settings,
        )
        is False
    )


def test_a_revoked_consent_is_told_apart_from_a_generic_failure() -> None:
    """A resposta operacional é outra: reconectar, não repetir."""
    fake = _drive_with_one_contract()
    fake.consent_revoked = True

    with fake.client() as client:
        with pytest.raises(drive.DriveAuthError):
            drive.refresh_access_token(_settings(), "refresh", client=client)


def test_the_code_exchange_returns_the_refresh_token_and_the_granted_scope() -> None:
    fake = _drive_with_one_contract()

    with fake.client() as client:
        tokens = drive.exchange_code(_settings(), "code", "verifier", client=client)

    assert tokens.refresh_token == "refresh-token-do-google"
    assert tokens.scope == "https://www.googleapis.com/auth/drive.readonly"


# --- a fronteira da pasta --------------------------------------------------------


def test_only_the_authorized_folder_is_listed() -> None:
    fake = _drive_with_one_contract()
    fake.folder("outra-pasta", "Pessoal")
    fake.add(
        FakeFile(
            id="alheio",
            name="pessoal.txt",
            mime_type="text/plain",
            parents=["outra-pasta"],
            content=b"nada a ver",
        )
    )

    with fake.client() as client:
        listing = drive.walk_folder(_settings(), "token", ROOT, client=client)

    assert [f.id for f in listing.files] == ["contrato"]


def test_a_file_whose_parent_is_another_folder_is_never_downloaded() -> None:
    """A barreira que o threat model cobra nominalmente ("teste de sync fora da
    pasta"). O Drive devolve o arquivo na listagem da pasta autorizada, mas ele
    declara outro pai — e nenhum byte dele é pedido."""
    fake = _drive_with_one_contract()
    fake.smuggled.append(
        FakeFile(
            id="infiltrado",
            name="segredo.txt",
            mime_type="text/plain",
            parents=["outra-pasta"],
            content=b"segredo",
        )
    )

    with fake.client() as client:
        listing = drive.walk_folder(_settings(), "token", ROOT, client=client)
        for found in listing.files:
            drive.download(_settings(), "token", found, client=client)

    assert [f.id for f in listing.files] == ["contrato"]
    assert listing.rejected == 1
    assert "infiltrado" not in fake.media_requests


def test_a_shortcut_inside_the_folder_is_ignored_not_followed() -> None:
    """O atalho mora na pasta autorizada com um `parents` legal e aponta para
    qualquer arquivo do Drive: segui-lo abriria a fronteira por dentro."""
    fake = _drive_with_one_contract()
    fake.add(
        FakeFile(id="atalho", name="atalho", mime_type=SHORTCUT_MIME, parents=[ROOT])
    )

    with fake.client() as client:
        listing = drive.walk_folder(_settings(), "token", ROOT, client=client)

    assert [f.id for f in listing.files] == ["contrato"]
    assert listing.rejected == 1
    assert fake.media_requests == []


def test_the_walk_descends_into_subfolders_up_to_the_configured_depth() -> None:
    fake = _drive_with_one_contract()
    fake.folder("nivel-1", "Anexos", parents=[ROOT])
    fake.folder("nivel-2", "Fundo", parents=["nivel-1"])
    fake.add(FakeFile(id="raso", name="a.txt", mime_type="text/plain", parents=["nivel-1"], content=b"a"))
    fake.add(FakeFile(id="fundo", name="b.txt", mime_type="text/plain", parents=["nivel-2"], content=b"b"))

    with fake.client() as client:
        deep = drive.walk_folder(_settings(drive_max_depth=5), "token", ROOT, client=client)
        shallow = drive.walk_folder(_settings(drive_max_depth=1), "token", ROOT, client=client)

    assert {f.id for f in deep.files} == {"contrato", "raso", "fundo"}
    assert {f.id for f in shallow.files} == {"contrato", "raso"}
    assert shallow.subfolders_skipped == 1


def test_a_folder_cycle_does_not_hang_the_walk() -> None:
    """O Drive permite mais de um pai, então a árvore é um grafo."""
    fake = _drive_with_one_contract()
    fake.folder("ciclo", "Ciclo", parents=[ROOT])
    fake.files["ciclo"].parents.append("ciclo")

    with fake.client() as client:
        listing = drive.walk_folder(_settings(), "token", ROOT, client=client)

    assert [f.id for f in listing.files] == ["contrato"]


def test_the_file_cap_truncates_instead_of_running_forever() -> None:
    fake = _drive_with_one_contract()
    for index in range(10):
        fake.add(
            FakeFile(
                id=f"extra-{index}",
                name=f"{index}.txt",
                mime_type="text/plain",
                parents=[ROOT],
                content=b"x",
            )
        )

    with fake.client() as client:
        listing = drive.walk_folder(_settings(drive_max_files=4), "token", ROOT, client=client)

    assert len(listing.files) == 4
    assert listing.truncated is True


# --- formatos --------------------------------------------------------------------


def test_a_google_doc_is_classified_for_export_and_a_spreadsheet_as_csv() -> None:
    """Depois do export é o `extract.py` de sempre: o conector não traz extrator novo."""
    fake = _drive_with_one_contract()
    fake.add(
        FakeFile(id="doc", name="Ata", mime_type=DOC_MIME, parents=[ROOT], exported=b"PK docx")
    )
    fake.add(
        FakeFile(id="planilha", name="Custos", mime_type=SHEET_MIME, parents=[ROOT], exported=b"a,b")
    )

    with fake.client() as client:
        listing = drive.walk_folder(_settings(), "token", ROOT, client=client)
        by_id = {f.id: f for f in listing.files}
        exported = drive.download(_settings(), "token", by_id["doc"], client=client)

    assert by_id["doc"].target_mime == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert by_id["planilha"].target_mime == "text/csv"
    assert exported == b"PK docx"


def test_a_native_file_without_an_export_becomes_a_reason_and_not_an_exception() -> None:
    """Formulário e desenho não têm equivalente legível; a tela precisa dizer isso."""
    fake = _drive_with_one_contract()
    fake.add(
        FakeFile(
            id="form",
            name="Pesquisa",
            mime_type="application/vnd.google-apps.form",
            parents=[ROOT],
            exported=b"",
        )
    )

    with fake.client() as client:
        listing = drive.walk_folder(_settings(), "token", ROOT, client=client)

    form = next(f for f in listing.files if f.id == "form")
    assert form.target_mime is None
    assert form.unsupported_reason is not None


def test_an_unknown_binary_format_says_which_one() -> None:
    fake = _drive_with_one_contract()
    fake.add(
        FakeFile(id="zip", name="tudo.zip", mime_type="application/zip", parents=[ROOT], content=b"PK")
    )

    with fake.client() as client:
        listing = drive.walk_folder(_settings(), "token", ROOT, client=client)

    zipped = next(f for f in listing.files if f.id == "zip")
    assert zipped.target_mime is None
    assert "application/zip" in (zipped.unsupported_reason or "")


def test_a_native_file_carries_no_md5_so_modified_time_is_the_gate() -> None:
    """Não é detalhe: usar md5 como portão deixaria todo Google Doc parecendo
    alterado a cada sync, e o portal recobraria embeddings sem motivo."""
    fake = _drive_with_one_contract()
    fake.add(FakeFile(id="doc", name="Ata", mime_type=DOC_MIME, parents=[ROOT], exported=b"x"))

    with fake.client() as client:
        listing = drive.walk_folder(_settings(), "token", ROOT, client=client)

    by_id = {f.id: f for f in listing.files}
    assert by_id["doc"].md5_checksum is None
    assert by_id["doc"].modified_time is not None
    assert by_id["contrato"].md5_checksum is not None


# --- falha do provedor -----------------------------------------------------------


def test_a_listing_that_fails_midway_raises_instead_of_returning_a_short_list() -> None:
    """É o que impede o runbook de ser violado: uma lista curta silenciosa viraria
    base para remoção, e o índice do cliente sumiria por indisponibilidade do Google."""
    fake = _drive_with_one_contract()
    fake.folder("nivel-1", "Anexos", parents=[ROOT])
    fake.fail_listing_after = 1

    with fake.client() as client:
        with pytest.raises(drive.DriveError):
            drive.walk_folder(_settings(), "token", ROOT, client=client)


def test_a_refused_credential_is_an_auth_error_and_not_a_generic_one() -> None:
    fake = _drive_with_one_contract()

    def refuse(request):  # type: ignore[no-untyped-def]
        import httpx as _httpx

        return _httpx.Response(401, content=b"{}", headers={"content-type": "application/json"})

    fake.handle = refuse  # type: ignore[method-assign]

    with fake.client() as client:
        with pytest.raises(drive.DriveAuthError):
            drive.walk_folder(_settings(), "token", ROOT, client=client)
