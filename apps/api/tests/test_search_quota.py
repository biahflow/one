"""Como as vinte vagas da busca são repartidas entre as espécies (ADR 0087).

Arquivo próprio e **sem Postgres**, ao contrário de ``test_search.py``, que é
``integration`` inteiro. O defeito que ``search._fit`` conserta é aritmético — nove
espécies a cinco são 45 candidatos para 20 vagas —, e um teste que precisasse do
banco para exercitá-lo seria um teste que **pula** na máquina de quem não subiu o
banco. Pular é o que fez as três asserções do backup passarem semanas sem rodar
(ADR 0019); aqui não há por que pagar esse risco, porque a função é pura.

O par com o mundo real está em ``test_search.py``
(``test_the_document_excerpt_survives_a_screenful_of_read_model_rows``): lá o
casamento é do Postgres, aqui é a repartição.
"""

from __future__ import annotations

from portal_api import search
from portal_api.tabs import TAB_DISCOVERY


def _hits(kind: str, quantity: int) -> list[search.Hit]:
    return [
        search.Hit(
            kind=kind,
            title=f"{kind} {index}",
            detail="",
            location="",
            tab=TAB_DISCOVERY,
        )
        for index in range(quantity)
    ]


def test_the_last_species_is_not_the_first_thing_to_disappear() -> None:
    """O caso que a fatia existe para consertar, no mínimo que o reproduz.

    Nove espécies cheias e uma décima com um candidato só. Com o corte por ordem de
    inserção — ``hits[:TOTAL_LIMIT]`` — a décima nunca aparece, e a décima é a dos
    trechos de documento.
    """
    groups = [_hits(f"kind{index}", search.PER_KIND_LIMIT) for index in range(9)]
    groups.append(_hits("chunk", 1))

    fitted = search._fit(groups)

    assert len(fitted) == search.TOTAL_LIMIT
    assert [hit for hit in fitted if hit.kind == "chunk"], (
        "a espécie que entra por último foi zerada pelas outras"
    )


def test_every_species_that_matched_gets_at_least_one_seat() -> None:
    """O piso, e é ele que a palavra "rodízio" promete.

    Vinte espécies para vinte vagas: cada uma leva exatamente uma. É o caso extremo
    do teto, e o que ele fixa é que nenhuma espécie **que casou** sai de mãos vazias
    enquanto houver vaga.
    """
    groups = [_hits(f"kind{index}", search.PER_KIND_LIMIT) for index in range(20)]

    fitted = search._fit(groups)

    assert len(fitted) == search.TOTAL_LIMIT
    assert len({hit.kind for hit in fitted}) == 20


def test_a_short_species_gives_its_leftover_seats_back() -> None:
    """Rodízio e não fatia igual: a sobra volta para quem tem candidato.

    Com duas espécies e vinte vagas, uma fatia igual daria dez a cada — e a que tem
    um candidato só devolveria nove vagas a ninguém, deixando resultado de fora com
    a lista pela metade.
    """
    fitted = search._fit([_hits("document", 1), _hits("chunk", 30)])

    assert len(fitted) == search.TOTAL_LIMIT
    assert [hit.kind for hit in fitted].count("chunk") == search.TOTAL_LIMIT - 1


def test_the_result_stays_grouped_by_species_in_the_order_they_were_collected() -> None:
    """O rodízio decide **quantos**, nunca em que ordem eles saem.

    Intercalar mudaria a lista que a tela já desenha por um ganho que ninguém pediu,
    e tornaria a ordem do resultado dependente do tamanho de cada grupo — o oposto
    de determinístico para quem lê a tela duas vezes.
    """
    fitted = search._fit([_hits("document", 3), _hits("chunk", 3)], limit=4)

    assert [hit.kind for hit in fitted] == ["document", "document", "chunk", "chunk"]


def test_nothing_matched_is_still_an_empty_list_and_never_an_error() -> None:
    """A regra 3 do módulo, no lugar onde um laço poderia não terminar."""
    assert search._fit([]) == []
    assert search._fit([[], [], []]) == []
