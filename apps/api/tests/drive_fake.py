"""Um Google Drive falso sobre ``httpx.MockTransport`` (ADR 0016).

Não é um mock de biblioteca: é um Drive de mentira com acervo próprio, que
responde às mesmas rotas REST que o adapter chama. A diferença importa porque o
que precisa ser provado aqui é *comportamento de fronteira* — "este arquivo nunca
foi baixado" só é afirmável se houver um servidor contando quem pediu o quê.

O mesmo acervo alimenta o stub do compose (``portal_api.devtools.drive_stub``),
para o que o teste unitário prova e o que o e2e exercita não divergirem.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
SLIDES_MIME = "application/vnd.google-apps.presentation"

_PARENT_QUERY = re.compile(r"'([^']+)' in parents")


@dataclass
class FakeFile:
    id: str
    name: str
    mime_type: str
    parents: list[str]
    content: bytes = b""
    modified_time: str = "2026-08-01T10:00:00.000Z"
    #: Os nativos do Google não têm md5 — é a razão de o portão barato do sync ser
    #: o `modifiedTime`, e o acervo tem de refletir isso para o teste valer.
    md5: str | None = None
    #: O que o `files.export` devolve. Só para nativos.
    exported: bytes | None = None

    def metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "mimeType": self.mime_type,
            "modifiedTime": self.modified_time,
            "parents": list(self.parents),
        }
        if self.mime_type != FOLDER_MIME and self.exported is None:
            data["size"] = str(len(self.content))
            data["md5Checksum"] = self.md5 or hashlib.md5(self.content).hexdigest()
        return data


@dataclass
class FakeDrive:
    """Acervo + transporte. ``media_requests`` é o que prova a fronteira."""

    files: dict[str, FakeFile] = field(default_factory=dict)
    account: str = "interno@portallabs.local"
    granted_scope: str = "https://www.googleapis.com/auth/drive.readonly"
    refresh_token: str | None = "refresh-token-do-google"
    #: Quando ligado, o token endpoint responde `invalid_grant` — o consentimento
    #: revogado, que o sync tem de tratar preservando o índice.
    consent_revoked: bool = False
    #: Faz a listagem falhar depois de N páginas, para provar que uma enumeração
    #: incompleta nunca vira base para remoção.
    fail_listing_after: int | None = None
    #: Arquivos que a listagem devolve **mesmo não estando na pasta pedida** — um
    #: Drive que responde errado, ou um id infiltrado. É o cenário que a segunda
    #: barreira do adapter existe para recusar, e sem poder encená-lo a barreira
    #: seria só uma linha de código que ninguém prova.
    smuggled: list[FakeFile] = field(default_factory=list)

    media_requests: list[str] = field(default_factory=list)
    list_calls: int = 0

    def add(self, file: FakeFile) -> FakeFile:
        self.files[file.id] = file
        return file

    def folder(self, folder_id: str, name: str, parents: list[str] | None = None) -> FakeFile:
        return self.add(
            FakeFile(id=folder_id, name=name, mime_type=FOLDER_MIME, parents=parents or [])
        )

    # --- transporte ------------------------------------------------------------

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle), base_url="http://drive")

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return self._token(request)
        if path.endswith("/about"):
            return self._json({"user": {"emailAddress": self.account}})
        if path.endswith("/files"):
            return self._list(request)
        if path.endswith("/export"):
            return self._export(request)
        media = request.url.params.get("alt") == "media"
        return self._file(request, media=media)

    # --- rotas -----------------------------------------------------------------

    def _token(self, request: httpx.Request) -> httpx.Response:
        if self.consent_revoked:
            return self._json({"error": "invalid_grant"}, status=400)
        body = dict(httpx.QueryParams(request.content.decode()))
        payload: dict[str, Any] = {
            "access_token": "access-token-de-uma-hora",
            "scope": self.granted_scope,
            "expires_in": 3600,
        }
        if body.get("grant_type") == "authorization_code" and self.refresh_token:
            payload["refresh_token"] = self.refresh_token
        return self._json(payload)

    def _list(self, request: httpx.Request) -> httpx.Response:
        self.list_calls += 1
        if self.fail_listing_after is not None and self.list_calls > self.fail_listing_after:
            return self._json({"error": "backend error"}, status=503)

        query = request.url.params.get("q", "")
        if FOLDER_MIME in query and "in parents" not in query:
            matches = [f for f in self.files.values() if f.mime_type == FOLDER_MIME]
        else:
            parent = _PARENT_QUERY.search(query)
            parent_id = parent.group(1) if parent else ""
            matches = [f for f in self.files.values() if parent_id in f.parents]
            matches.extend(self.smuggled)
        return self._json({"files": [f.metadata() for f in matches]})

    def _file(self, request: httpx.Request, *, media: bool) -> httpx.Response:
        file_id = request.url.path.rsplit("/", 1)[-1]
        found = self.files.get(file_id)
        if found is None:
            return self._json({"error": "not found"}, status=404)
        if not media:
            return self._json(found.metadata())
        self.media_requests.append(file_id)
        return httpx.Response(200, content=found.content)

    def _export(self, request: httpx.Request) -> httpx.Response:
        file_id = request.url.path.split("/")[-2]
        found = self.files.get(file_id)
        if found is None:
            return self._json({"error": "not found"}, status=404)
        self.media_requests.append(file_id)
        return httpx.Response(200, content=found.exported or b"")

    @staticmethod
    def _json(payload: dict[str, Any], status: int = 200) -> httpx.Response:
        return httpx.Response(
            status, content=json.dumps(payload), headers={"content-type": "application/json"}
        )
