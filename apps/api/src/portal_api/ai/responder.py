"""Answer generation: Claude when a key is configured, deterministic offline otherwise.

Both paths are grounded — they may only produce facts present in the evidence, and flag
insufficiency instead of inventing (docs/ai/, ADR 0007). The offline responder makes the
whole flow work — and the eval harness deterministic — without any external call or key.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from portal_api.ai.prompt import OUTPUT_SCHEMA, SYSTEM_PROMPT, build_user_prompt
from portal_api.ai.retrieval import Evidence
from portal_api.config import Settings

GAP_MESSAGE = (
    "Não encontrei evidências suficientes nos materiais deste projeto para responder com "
    "segurança. Registrei uma pendência para o time responsável retornar com a informação."
)

_PRODUCTION_KW = ("produc", "no ar", "go live", "lancamento", "live")
_PENDING_KW = ("pend", "abert", "bloque", "falta", "aprovac")
_STATUS_KW = ("status", "andamento", "progresso", "conclu", "porcent", "percentu", "como esta")
_SCHEDULE_KW = ("marco", "entrega", "cronograma", "prazo", "etapa", "proxim", "quando")


@dataclass(frozen=True)
class ResponderResult:
    answer: str
    source_ids: list[str]
    sufficient: bool


def _norm(text: str) -> str:
    stripped = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")
    return stripped.lower()


def _query_tokens(q: str) -> set[str]:
    """Termos com sinal na pergunta — os curtos aparecem em qualquer frase."""
    return {tok for tok in re.findall(r"\w+", q) if len(tok) >= 4}


class Responder(Protocol):
    def answer(self, evidence: list[Evidence], question: str) -> ResponderResult: ...


class OfflineResponder:
    """Deterministic, grounded matcher over the evidence. Never calls out; never invents."""

    def answer(self, evidence: list[Evidence], question: str) -> ResponderResult:
        q = _norm(question)
        selected = self._select(evidence, q)
        if not selected:
            # Topic gating means a specific unanswerable question (e.g. production date when
            # that source was removed) is a gap, not an off-topic fact.
            return ResponderResult(GAP_MESSAGE, [], False)
        answer = " ".join(item.text for item in selected)
        return ResponderResult(answer, [item.id for item in selected], True)

    def _select(self, evidence: list[Evidence], q: str) -> list[Evidence]:
        def by(pred) -> list[Evidence]:  # type: ignore[no-untyped-def]
            return [item for item in evidence if pred(item)]

        # O trecho de documento entra em todos os ramos (ADR 0014): a recuperação
        # por similaridade já filtrou por relevância antes de chegar aqui, então
        # descartá-lo por não ser marco nem pendência seria jogar fora a única
        # evidência que responde a pergunta. Os ramos abaixo continuam mandando
        # em *qual* evidência estruturada é pertinente.
        documents = self._matching_documents(evidence, q)

        # Priority-ordered, gated topics: the most specific intent wins and only matches its
        # own evidence — never falling back to an unrelated fact.
        if any(kw in q for kw in _PRODUCTION_KW):
            return by(lambda e: "produc" in _norm(f"{e.source} {e.text}")) + documents
        if any(kw in q for kw in _PENDING_KW):
            return by(lambda e: e.id.startswith("pending")) + documents
        if any(kw in q for kw in _SCHEDULE_KW):
            return by(lambda e: e.id.startswith("milestone")) + documents
        if any(kw in q for kw in _STATUS_KW):
            return by(lambda e: e.id == "project") + documents
        # Generic fallback: direct token overlap with the evidence.
        tokens = _query_tokens(q)
        return by(lambda e: any(tok in _norm(f"{e.source} {e.text}") for tok in tokens))

    def _matching_documents(self, evidence: list[Evidence], q: str) -> list[Evidence]:
        """Trechos que compartilham ao menos um termo da pergunta.

        A segunda peneira existe porque o corte de distância é generoso por
        desenho: um trecho que veio junto do relevante, mas não fala do assunto,
        viraria citação de enfeite embaixo de uma resposta correta.
        """
        tokens = _query_tokens(q)
        return [
            item
            for item in evidence
            if item.id.startswith("chunk-")
            and any(tok in _norm(item.text) for tok in tokens)
        ]


class AnthropicResponder:
    """Uses the Claude Messages API with strict grounding + structured output."""

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def answer(self, evidence: list[Evidence], question: str) -> ResponderResult:
        import anthropic  # lazy: keeps the package optional for offline/tests

        client = anthropic.Anthropic(api_key=self._api_key)
        response = client.messages.create(
            model=self._model,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            messages=[{"role": "user", "content": build_user_prompt(evidence, question)}],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        data = json.loads(text)
        valid_ids = {item.id for item in evidence}
        # Defensive: keep only citations that point at real evidence (no fabricated sources).
        source_ids = [sid for sid in data.get("source_ids", []) if sid in valid_ids]
        return ResponderResult(str(data["answer"]), source_ids, bool(data["sufficient"]))


def get_responder(settings: Settings) -> Responder:
    if settings.anthropic_api_key:
        return AnthropicResponder(settings.anthropic_api_key, settings.anthropic_model)
    return OfflineResponder()
