"""Adapter de embeddings (ADR 0014).

O caminho offline não é um mock: é o que roda na demo e no CI, e a recuperação
inteira depende das propriedades afirmadas aqui — dimensão fixa, determinismo e
separação entre trecho que responde e trecho que não tem nada a ver.
"""

from __future__ import annotations

import math

from portal_api.ai.embeddings import OfflineEmbedder, VoyageEmbedder, get_embedder
from portal_api.config import Settings
from portal_api.models import EMBEDDING_DIMENSIONS

TRECHO = (
    "O contrato prevê suporte por 12 meses após a entrega, com prazo de resposta "
    "de 4 horas para incidentes críticos."
)


def _embedder() -> OfflineEmbedder:
    return OfflineEmbedder(EMBEDDING_DIMENSIONS, 0.92)


def _distance(embedder: OfflineEmbedder, question: str, text: str) -> float:
    query = embedder.embed_query(question)
    document = embedder.embed_documents([text])[0]
    return 1.0 - sum(a * b for a, b in zip(query, document))


def test_the_vector_has_the_dimension_the_column_declares() -> None:
    """Mudar a dimensão sem migrar deixaria o índice ingravável — e silenciosamente."""
    assert len(_embedder().embed_query("qualquer pergunta")) == EMBEDDING_DIMENSIONS


def test_the_same_text_always_produces_the_same_vector() -> None:
    assert _embedder().embed_query(TRECHO) == _embedder().embed_query(TRECHO)


def test_the_vector_is_normalized_so_cosine_distance_is_comparable() -> None:
    vector = _embedder().embed_query(TRECHO)

    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-9)


def test_a_text_without_useful_tokens_is_reachable_by_nobody() -> None:
    """Vetor nulo grava e nunca é recuperado — melhor do que quebrar a ingestão."""
    assert set(_embedder().embed_query("42 -- 7")) == {0.0}


def test_the_relevant_excerpt_lands_inside_the_cut_and_the_unrelated_one_does_not() -> None:
    embedder = _embedder()

    relevant = _distance(embedder, "Qual o prazo de suporte previsto no contrato?", TRECHO)
    unrelated = _distance(embedder, "Quem ganhou a copa do mundo?", TRECHO)

    assert relevant < embedder.max_distance
    assert unrelated > embedder.max_distance


def test_the_cut_belongs_to_the_embedder_and_not_to_the_retriever() -> None:
    """Espaços diferentes, cortes diferentes: um número só serviria mal aos dois."""
    settings = Settings(voyage_api_key="", rag_max_distance=0.6, rag_offline_max_distance=0.92)

    assert get_embedder(settings).max_distance == 0.92
    assert get_embedder(settings.model_copy(update={"voyage_api_key": "k"})).max_distance == 0.6


def test_the_provider_is_chosen_by_the_key_alone() -> None:
    assert isinstance(get_embedder(Settings(voyage_api_key="")), OfflineEmbedder)
    assert isinstance(get_embedder(Settings(voyage_api_key="voyage-key")), VoyageEmbedder)


def test_the_model_name_travels_with_the_row() -> None:
    """Guardado por linha para uma troca de modelo ser visível e reindexável."""
    assert "offline" in _embedder().model_name
    assert VoyageEmbedder("k", "voyage-3", 1024, 0.6).model_name == "voyage:voyage-3"
