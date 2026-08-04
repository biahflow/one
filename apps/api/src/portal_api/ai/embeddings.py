"""Embeddings: Voyage quando há chave, offline determinístico quando não (ADR 0014).

Mesma forma do :mod:`portal_api.ai.responder`, e pelo mesmo motivo: a stack local
e o CI precisam indexar e recuperar sem chave e sem rede, e o caminho offline não
pode ser um mock — é o que roda na demo.

A Claude API não tem endpoint de embeddings; o provedor recomendado pela
Anthropic é a Voyage, e é ele que entra aqui.

**O corte de distância pertence ao adapter, não à recuperação.** Um espaço
semântico treinado põe pergunta e resposta perto mesmo sem palavra em comum; o
embedder offline é lexical, e nele a distância entre uma pergunta curta e um
parágrafo longo é sempre alta, mesmo quando o parágrafo responde. Um número só
para os dois deixaria a demo sem citar nada ou o provedor real citando ruído.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Protocol

from portal_api.config import Settings

#: Tokens curtos carregam pouco sinal e aparecem em toda frase. É o mesmo corte
#: que o `OfflineResponder` usa para casar pergunta e evidência.
_MIN_TOKEN = 4
_TOKEN = re.compile(r"\w+", re.UNICODE)


class Embedder(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def max_distance(self) -> float: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _tokens(text: str) -> list[str]:
    stripped = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")
    return [tok for tok in _TOKEN.findall(stripped.lower()) if len(tok) >= _MIN_TOKEN]


class OfflineEmbedder:
    """Projeção determinística por hashing — recuperação lexical, sem rede.

    Cada token vira uma posição e um sinal derivados do seu próprio hash, com
    peso sublinear na frequência. Não entende sinônimo nem paráfrase, e não
    finge que entende: serve para a demo e para o CI acharem o trecho que
    repete as palavras da pergunta, que é exatamente o que os testes afirmam.
    """

    def __init__(self, dimensions: int, max_distance: float) -> None:
        self._dimensions = dimensions
        self._max_distance = max_distance

    @property
    def model_name(self) -> str:
        return f"offline-hashing-v1-{self._dimensions}"

    @property
    def max_distance(self) -> float:
        return self._max_distance

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        counts: dict[str, int] = {}
        for token in _tokens(text):
            counts[token] = counts.get(token, 0) + 1

        vector = [0.0] * self._dimensions
        for token, count in counts.items():
            seed = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(seed[:4], "big") % self._dimensions
            sign = 1.0 if seed[4] % 2 == 0 else -1.0
            vector[index] += sign * (1.0 + math.log(count))

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            # Texto sem token útil (só números, só símbolos). Vetor nulo teria
            # distância indefinida; devolver zeros mantém a linha gravável e a
            # busca simplesmente nunca a alcança.
            return vector
        return [value / norm for value in vector]


class VoyageEmbedder:
    """Adapter da Voyage. ``input_type`` separa documento de pergunta — o modelo
    é treinado para assimetria, e ignorar isso custa qualidade de recuperação."""

    def __init__(self, api_key: str, model: str, dimensions: int, max_distance: float) -> None:
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._max_distance = max_distance

    @property
    def model_name(self) -> str:
        return f"voyage:{self._model}"

    @property
    def max_distance(self) -> float:
        return self._max_distance

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        import voyageai  # lazy: mantém o pacote opcional para o caminho offline

        client = voyageai.Client(api_key=self._api_key)
        vectors: list[list[float]] = []
        # Em lotes porque um documento longo passa do limite de itens por
        # chamada, e uma reindexação inteira não deve virar uma requisição só.
        for start in range(0, len(texts), 96):
            response = client.embed(
                texts[start : start + 96],
                model=self._model,
                input_type=input_type,
                output_dimension=self._dimensions,
            )
            vectors.extend(response.embeddings)
        return vectors


def get_embedder(settings: Settings) -> Embedder:
    if settings.voyage_api_key:
        return VoyageEmbedder(
            settings.voyage_api_key,
            settings.voyage_model,
            settings.embedding_dimensions,
            settings.rag_max_distance,
        )
    return OfflineEmbedder(settings.embedding_dimensions, settings.rag_offline_max_distance)
