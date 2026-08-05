"""O esquema OpenAPI como artefato versionado (ADR 0020).

``python -m portal_api.openapi`` imprime; ``--write`` grava em
``docs/api/openapi.json``. É a mesma forma de ``portal_api.seed``, e existe pelo
mesmo motivo que ``alembic check`` existe: a deriva entre o que o código faz e o
que o contrato promete precisa aparecer **na revisão**, não na produção.

Por que um arquivo no repositório, se o FastAPI serve `/openapi.json` de graça:
porque um esquema que só existe num processo no ar não pode ser comparado com o
da semana passada. Versionado, a mudança de contrato vira uma linha de diff que
alguém aprova — e `test_openapi_contract.py` recusa o commit que a esqueceu.

``sort_keys`` é deliberado: sem ele uma troca de versão do FastAPI reordena
chaves e produz um diff enorme onde nada mudou, que é como se ensina uma equipe
a aprovar diff de contrato sem ler.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

#: ``apps/api/src/portal_api/openapi.py`` → raiz do repositório.
REPO_ROOT = Path(__file__).resolve().parents[4]
ARTIFACT = REPO_ROOT / "docs" / "api" / "openapi.json"


def schema() -> dict[str, Any]:
    # Importado aqui, e não no topo, porque importar ``main`` sobe a aplicação
    # inteira (configura o logging, lê as settings) e este módulo é importado
    # pelo teste só para chegar ao caminho do artefato.
    from portal_api.main import app

    return app.openapi()


def render(document: dict[str, Any] | None = None) -> str:
    """O texto exato do artefato, com quebra de linha final."""
    return json.dumps(
        document if document is not None else schema(),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    ) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    rendered = render()
    if "--write" in argv:
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(rendered, encoding="utf-8")
        print(f"escrito: {ARTIFACT.relative_to(REPO_ROOT)}", file=sys.stderr)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
