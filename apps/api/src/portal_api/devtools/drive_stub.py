"""Um Google Drive de mentira para a stack local e o e2e (ADR 0016).

Existe porque o conector é a única peça da Fase 4 que não pode ser provada ponta a
ponta sem credencial de um provedor externo — e o threat model **exige** um teste
de sync fora da pasta. Sem isto, a barreira mais importante do conector seria
verificada só em teste unitário, e o e2e pararia em "a tela abre".

Roda com a mesma imagem da API (nenhum build novo) e só entra no compose local.
Apontar o conector para cá é trocar três variáveis, exatamente a mesma manobra que
``BIAHFLOW_BASE_URL`` já permite — e a mesma razão pela qual ``OIDC_ISSUER`` e
``OIDC_JWKS_URL`` são separadas: o navegador vai a um endereço e o servidor a
outro.

O acervo é escolhido para o e2e conseguir provar o que importa:

* um ``.txt`` com um termo que não existe em nenhum outro lugar do seed, para a
  citação no chat ser inequívoca;
* uma planilha do Google, para o export virar um formato que o portal lê. É uma
  planilha e não um documento porque o export de Docs é DOCX — e um DOCX de
  mentira teria de ser um zip válido com a estrutura toda, trabalho que não prova
  nada além do que ``test_drive_adapter.py`` já prova sobre o mapa de formatos;
* **um atalho e um arquivo de outra pasta**, para a fronteira ser provada no
  navegador e não só no unitário.
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"

ROOT = "pasta-do-projeto"
OUTSIDE = "pasta-pessoal"

#: O termo que o e2e procura na citação. Não aparece em `seed.py`, então encontrá-lo
#: na resposta do chat só é possível se o arquivo tiver mesmo sido indexado.
CANARY = "girassol-cravado-42"

_CONTRACT = (
    "Clausula de suporte do projeto.\n\n"
    f"O codigo interno deste contrato e {CANARY}, e o prazo de resposta para "
    "incidentes criticos e de 4 horas.\n"
).encode()

#: O que o `files.export` de uma planilha devolve: CSV, e **só a primeira aba** —
#: limitação do Google, registrada na FDD 010 para o usuário ler na tela em vez de
#: descobrir pela ausência da citação.
_EXPORTED_SHEET = "entrega,prazo\nIntegracao,2026-09-01\nRelatorios,2026-10-15\n".encode()

_SECRET = b"Este arquivo nao esta na pasta autorizada e nao pode ser indexado."


def _file(
    file_id: str,
    name: str,
    mime: str,
    parents: list[str],
    content: bytes = b"",
    exported: bytes | None = None,
) -> dict[str, Any]:
    return {
        "id": file_id,
        "name": name,
        "mimeType": mime,
        "parents": parents,
        "content": content,
        "exported": exported,
        "modifiedTime": "2026-08-01T10:00:00.000Z",
    }


FILES: dict[str, dict[str, Any]] = {
    item["id"]: item
    for item in [
        _file(ROOT, "Contratos do Projeto", FOLDER_MIME, []),
        _file(OUTSIDE, "Pessoal", FOLDER_MIME, []),
        _file("contrato", "Contrato de suporte.txt", "text/plain", [ROOT], _CONTRACT),
        _file("cronograma", "Cronograma de entregas", SHEET_MIME, [ROOT], exported=_EXPORTED_SHEET),
        _file("atalho", "Atalho para pessoal", SHORTCUT_MIME, [ROOT]),
        _file("segredo", "Confidencial.txt", "text/plain", [OUTSIDE], _SECRET),
    ]
}

app = FastAPI(title="Google Drive (stub)", docs_url=None, redoc_url=None)


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    data = {
        "id": item["id"],
        "name": item["name"],
        "mimeType": item["mimeType"],
        "parents": list(item["parents"]),
        "modifiedTime": item["modifiedTime"],
    }
    if item["mimeType"] != FOLDER_MIME and item["exported"] is None:
        data["size"] = str(len(item["content"]))
        data["md5Checksum"] = hashlib.md5(item["content"]).hexdigest()
    return data


@app.get("/authorize")
def authorize(redirect_uri: str, state: str) -> RedirectResponse:
    """Consente sem tela: devolve o navegador na hora, com um código fixo.

    Uma tela de login aqui só acrescentaria passos ao e2e sem provar nada — quem
    prova login de verdade é o Keycloak em ``tests/e2e/login.spec.ts``.
    """
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{separator}code=stub-code&state={state}", status_code=302)


@app.post("/token")
async def token(request: Request) -> JSONResponse:
    form = await request.form()
    payload: dict[str, Any] = {
        "access_token": "stub-access-token",
        "expires_in": 3600,
        "scope": "https://www.googleapis.com/auth/drive.readonly",
        "token_type": "Bearer",
    }
    if form.get("grant_type") == "authorization_code":
        payload["refresh_token"] = "stub-refresh-token"
    return JSONResponse(payload)


@app.get("/drive/v3/about")
def about() -> JSONResponse:
    return JSONResponse({"user": {"emailAddress": "equipe@portallabs.local"}})


@app.get("/drive/v3/files")
def list_files(q: str = "") -> JSONResponse:
    if FOLDER_MIME in q and "in parents" not in q:
        found = [item for item in FILES.values() if item["mimeType"] == FOLDER_MIME]
    else:
        parent = q.split("'")[1] if "'" in q else ""
        found = [item for item in FILES.values() if parent in item["parents"]]
    return JSONResponse({"files": [_metadata(item) for item in found]})


@app.get("/drive/v3/files/{file_id}/export")
def export_file(file_id: str) -> Response:
    item = FILES.get(file_id)
    if item is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return Response(content=item["exported"] or b"", media_type="application/octet-stream")


@app.get("/drive/v3/files/{file_id}")
def get_file(file_id: str, alt: str = "") -> Response:
    item = FILES.get(file_id)
    if item is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if alt == "media":
        return Response(content=item["content"], media_type="application/octet-stream")
    return JSONResponse(_metadata(item))
