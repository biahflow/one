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
    from portal_api.main import VALIDATION_DETAIL_FIELDS, app

    document = app.openapi()
    _prune_validation_error(document, VALIDATION_DETAIL_FIELDS)
    return document


def _prune_validation_error(document: dict[str, Any], fields: tuple[str, ...]) -> None:
    """Tira do ``ValidationError`` os campos que o 422 não devolve (ADR 0023).

    O FastAPI monta este componente a partir do erro do Pydantic, e a partir do
    ``0.141`` ele inclui ``ctx`` e ``input`` — sendo ``input`` o corpo inteiro de
    quem chamou. O handler de `main.py` os remove da resposta pelo motivo
    documentado lá; aqui o esquema para de anunciá-los, porque um contrato que
    promete campo que não vem é a mesma classe de defeito que a ADR 0020 recusou
    acrescentar quando tipou as respostas — só que na direção oposta, e a única
    das duas em que a ferramenta de quem consome é que fica errada.

    Poda em vez de modelo próprio: substituir o componente exigiria declarar de
    novo o ``loc`` polimórfico do Pydantic, que muda quando ele muda. Poda erra
    para o lado seguro — um campo novo do Pydantic some do contrato até alguém
    decidir sobre ele, em vez de aparecer na resposta sem ninguém ver.
    """
    component = document.get("components", {}).get("schemas", {}).get("ValidationError")
    if not component:
        return
    properties = component.get("properties", {})
    for name in [name for name in properties if name not in fields]:
        del properties[name]
    if "required" in component:
        component["required"] = [
            name for name in component["required"] if name in fields
        ]


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
