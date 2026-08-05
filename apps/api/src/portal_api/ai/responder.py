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
from typing import Any, Protocol

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
    #: O que a chamada consumiu (Fase 5, ADR 0022). Com default, para o
    #: ``Protocol`` e o ``OfflineResponder`` não mudarem de assinatura: no caminho
    #: offline não há provedor, e zero é a verdade e não uma ausência de dado.
    #:
    #: Até esta fatia o ``response.usage`` que a SDK devolve em toda resposta era
    #: simplesmente descartado — e ``docs/observability.md`` listava "custo/latência
    #: de IA" entre os indicadores.
    input_tokens: int = 0
    output_tokens: int = 0


def _norm(text: str) -> str:
    stripped = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")
    return stripped.lower()


def _query_tokens(q: str) -> set[str]:
    """Termos com sinal na pergunta — os curtos aparecem em qualquer frase."""
    return {tok for tok in re.findall(r"\w+", q) if len(tok) >= 4}


class Responder(Protocol):
    #: O nome que vai para a coluna ``conversation_message.responder`` e para o
    #: log (ADR 0021). Atributo em vez de escada de ``isinstance`` no serviço:
    #: quem sabe qual respondedor é este é o próprio respondedor.
    name: str

    @property
    def model(self) -> str | None: ...

    def answer(self, evidence: list[Evidence], question: str) -> ResponderResult: ...


class OfflineResponder:
    """Deterministic, grounded matcher over the evidence. Never calls out; never invents."""

    name = "offline"

    @property
    def model(self) -> str | None:
        # Não há modelo: o "modelo" é este código, e quem o versiona é o git.
        return None

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


class ProviderRefused(RuntimeError):
    """O modelo recusou a requisição pelos classificadores de segurança (ADR 0021).

    Existe para o log do chat distinguir **recusa** de **parser quebrado**: sem
    ela, uma recusa (que devolve `content` vazio) chegava ao `json.loads` e virava
    um `JSONDecodeError`, e o runbook tinha de adivinhar qual dos dois incidentes
    estava lendo. O fallback é o mesmo nos dois casos — o `except Exception` de
    `ai/service.py` já pega esta —, mas o `reason` no log passa a ser verdade.
    """


def anthropic_client(api_key: str) -> Any:
    """O ponto de costura, na forma de ``google_drive.session_client`` (ADR 0016).

    Existe para o teste poder trocá-lo por um cliente que **registra o pedido** e
    devolve o que um atacante escolheria. Sem ele, o `AnthropicResponder` e o
    `SYSTEM_PROMPT` versionado seriam código que nenhum teste executa — que era
    exatamente o estado até a Fase 5, e o motivo pelo qual as evals de prompt
    injection rodavam num casador determinístico incapaz de obedecer a uma
    instrução, provando que uma pedra não atende ao telefone.
    """
    import anthropic  # lazy: keeps the package optional for offline/tests

    return anthropic.Anthropic(api_key=api_key)


class AnthropicResponder:
    """Uses the Claude Messages API with strict grounding + structured output."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def answer(self, evidence: list[Evidence], question: str) -> ResponderResult:
        client = anthropic_client(self._api_key)
        response = client.messages.create(
            model=self._model,
            # O teto vale para pensamento **mais** texto: com `thinking` adaptativo,
            # um turno que pensa demais devolvia JSON truncado sob os 1024 originais,
            # e o truncamento virava fallback offline silencioso (ADR 0021). `effort`
            # baixo é o freio certo aqui — extrair citação de alguns KB de evidência
            # não é tarefa sensível a inteligência —, e mora dentro de `output_config`.
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            output_config={
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
                "effort": "low",
            },
            messages=[{"role": "user", "content": build_user_prompt(evidence, question)}],
        )
        if getattr(response, "stop_reason", None) == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise ProviderRefused(str(category))
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        data = json.loads(text)
        valid_ids = {item.id for item in evidence}
        # Defensive: keep only citations that point at real evidence (no fabricated sources).
        source_ids = [sid for sid in data.get("source_ids", []) if sid in valid_ids]
        # `usage` é opcional na leitura de propósito: um número de custo ausente
        # não pode derrubar uma resposta que já foi produzida e paga. Zero aqui
        # subconta o mês, e o razão prefere subcontar a perder o turno.
        usage = getattr(response, "usage", None)
        return ResponderResult(
            str(data["answer"]),
            source_ids,
            bool(data["sufficient"]),
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )


def get_responder(settings: Settings) -> Responder:
    if settings.anthropic_api_key:
        return AnthropicResponder(settings.anthropic_api_key, settings.anthropic_model)
    return OfflineResponder()
