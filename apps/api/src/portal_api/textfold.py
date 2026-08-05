"""A dobra de acento e caixa, que a busca e o índice têm de fazer igual (ADR 0024).

Módulo folha — depende só do SQLAlchemy — pela razão de :mod:`portal_api.scanner`
ser um: quem define a expressão do índice não pode depender de quem consulta, e
``models/document.py`` importa daqui do mesmo jeito que importa ``ScanState`` de
lá. A seta aponta para o lado seguro.

Ele existe porque a mesma expressão aparece em **três** lugares que precisam ser
idênticos ou o índice deixa de ser usado sem nada ficar vermelho: a declaração em
``DocumentChunk.__table_args__``, o ``CREATE INDEX`` da migração e a consulta em
:mod:`portal_api.search`. Dois deles são texto (o metadata e a migração, pela
regra que ``models/document.py`` já escreveu no índice parcial do Drive); este
módulo é o que impede o terceiro de divergir por conta própria.

**Por que ``translate`` e não ``unaccent``** (ADR 0024, decisão 3): ``unaccent``
é extensão, e extensão é objeto de **banco** — não entra num ``pg_dump -n
portal``, então teria de nascer no bootstrap, no init e na migração, que é
exatamente o defeito que a ADR 0019 encontrou no ``btree_gist`` no dia do
restore. E ``unaccent()`` é ``STABLE``, de modo que um índice funcional sobre ela
ainda exigiria uma função ``IMMUTABLE`` própria — mais um objeto de banco que o
``roles.sql`` teria de possuir. ``translate()`` é builtin, ``IMMUTABLE`` e
indexável.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, literal_column

#: As duas cadeias têm de ter o mesmo comprimento **em caracteres**, e só cobrem
#: minúsculas porque a dobra sempre vem depois de ``lower()``.
FOLD_FROM = "áàâãäéèêëíìîïóòôõöúùûüçñ"
FOLD_TO = "aaaaaeeeeiiiiooooouuuucn"

#: A configuração de busca textual. Literal e não parametrizada — ver
#: :func:`text_vector`.
REGCONFIG = literal_column("'portuguese'")

_PYTHON_FOLD = str.maketrans(FOLD_FROM, FOLD_TO)


def fold(value: str) -> str:
    """A dobra do lado do Python, para o termo digitado.

    O par existe porque a comparação tem dois lados: a coluna é dobrada pelo
    Postgres, o termo é dobrado aqui. Um sem o outro faria a busca achar
    "reuniao" e não achar "reunião" — ou o contrário, que é pior.
    """
    return value.casefold().translate(_PYTHON_FOLD)


def folded(column: ColumnElement[str]) -> ColumnElement[str]:
    """``translate(lower(<coluna>), …)`` — a expressão que o índice repete."""
    return func.translate(func.lower(column), FOLD_FROM, FOLD_TO)


def text_vector(column: ColumnElement[str]) -> ColumnElement:
    """O ``tsvector`` do texto, na forma **exata** da expressão do índice GIN.

    ``literal_column`` e não bind param: ``to_tsvector('portuguese', …)`` com a
    configuração literal é ``IMMUTABLE`` e casa com a expressão do índice; com um
    parâmetro, o planejador não reconhece o índice e a busca vira varredura
    sequencial sobre o texto de todos os documentos do projeto.
    """
    return func.to_tsvector(REGCONFIG, folded(column))


def index_expression(column_name: str) -> str:
    """O mesmo ``tsvector``, em SQL, para o ``Index`` e para a migração.

    Gerado a partir das mesmas constantes em vez de digitado duas vezes: a
    igualdade entre a expressão do índice e a da consulta é a única coisa que
    faz o índice ser usado, e ela não pode depender de alguém reparar num
    caractere.
    """
    return (
        f"to_tsvector('portuguese', translate(lower({column_name}), "
        f"'{FOLD_FROM}', '{FOLD_TO}'))"
    )
