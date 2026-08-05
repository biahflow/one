"""Um Claude de mentira: registra o pedido, devolve o que o teste mandar (ADR 0021).

Mesmo idioma do ``drive_fake.py`` e pelo mesmo motivo: o que precisa ser provado
aqui é *comportamento de fronteira*, e "este texto nunca saiu daqui" só é
afirmável se houver alguém do outro lado contando o que recebeu. É a contraparte
de ``FakeDrive.media_requests``, uma camada acima.

Sem ele, o ``AnthropicResponder`` e o ``SYSTEM_PROMPT`` versionado seriam código
que nenhum teste executa — e as evals de prompt injection continuariam rodando no
``OfflineResponder``, um casador determinístico que **não tem como** obedecer a
uma instrução. Uma eval tautológica por construção.

Três detalhes carregam o valor do arquivo:

1. A resposta emite um bloco ``thinking`` **antes** do ``text``, que é a forma
   real do fio com ``thinking: adaptive``. Um falso que devolvesse só o bloco de
   texto deixaria passar um bug de ``content[0].text`` — é o filtro por
   ``block.type`` do respondedor que estaria sem prova.
2. ``messages.create(**kwargs)`` guarda os kwargs verbatim: é o que torna
   afirmável o que **não** foi enviado.
3. ``sent_text()`` achata tudo o que saiu num texto só, para o teste escrever
   ``assert PEPPER not in fake.sent_text()`` — a regra 2 do ``AGENTS.md`` como
   contra-asserção, e não como intenção.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeBlock:
    """Um bloco de conteúdo. ``type`` é lido por ``getattr``, como no SDK."""

    type: str
    text: str = ""
    thinking: str = ""


@dataclass
class FakeStopDetails:
    type: str = "refusal"
    category: str | None = None
    explanation: str | None = None


@dataclass
class FakeResponse:
    content: list[FakeBlock]
    stop_reason: str = "end_turn"
    stop_details: FakeStopDetails | None = None
    model: str = "claude-opus-5"


@dataclass
class FakeAnthropic:
    """O cliente. ``.messages.create(...)`` grava o pedido e devolve o combinado."""

    #: O texto do bloco ``text``. ``None`` com ``raises`` significa "nem chegou lá".
    reply: str | None = None
    stop_reason: str = "end_turn"
    stop_details: FakeStopDetails | None = None
    #: Provedor fora do ar: rede caída, 529, timeout.
    raises: Exception | None = None
    #: Emite o bloco de pensamento antes do texto, como o fio de verdade.
    with_thinking: bool = True
    #: Tudo o que passou por ``create``, na ordem. A prova negativa mora aqui.
    requests: list[dict[str, Any]] = field(default_factory=list)

    # --- construtores, na voz do que o teste quer dizer ----------------------

    @classmethod
    def answering(
        cls,
        answer: str,
        source_ids: list[str],
        sufficient: bool = True,
        **kwargs: Any,
    ) -> "FakeAnthropic":
        """Um modelo que responde no formato combinado — obediente ou hostil."""
        return cls(
            reply=json.dumps(
                {"answer": answer, "source_ids": source_ids, "sufficient": sufficient},
                ensure_ascii=False,
            ),
            **kwargs,
        )

    @classmethod
    def replying_raw(cls, text: str, **kwargs: Any) -> "FakeAnthropic":
        """Prosa em vez de JSON, ou JSON pela metade (resposta truncada)."""
        return cls(reply=text, **kwargs)

    @classmethod
    def truncated(cls, **kwargs: Any) -> "FakeAnthropic":
        """O caso do teto de tokens: metade de um objeto e ``stop_reason``."""
        return cls(
            reply='{"answer": "A entrada em produção está prevista para',
            stop_reason="max_tokens",
            **kwargs,
        )

    @classmethod
    def refusing(cls, category: str = "cyber", **kwargs: Any) -> "FakeAnthropic":
        """Classificador recusou: HTTP 200, ``content`` vazio, ``stop_reason``."""
        return cls(
            reply=None,
            stop_reason="refusal",
            stop_details=FakeStopDetails(category=category),
            with_thinking=False,
            **kwargs,
        )

    @classmethod
    def failing(cls, exc: Exception | None = None, **kwargs: Any) -> "FakeAnthropic":
        return cls(raises=exc or RuntimeError("provedor indisponível"), **kwargs)

    # --- a superfície que o respondedor usa ---------------------------------

    @property
    def messages(self) -> "_FakeMessages":
        return _FakeMessages(self)

    def _create(self, **kwargs: Any) -> FakeResponse:
        self.requests.append(kwargs)
        if self.raises is not None:
            raise self.raises
        blocks: list[FakeBlock] = []
        if self.with_thinking:
            blocks.append(FakeBlock(type="thinking", thinking=""))
        if self.reply is not None:
            blocks.append(FakeBlock(type="text", text=self.reply))
        return FakeResponse(
            content=blocks,
            stop_reason=self.stop_reason,
            stop_details=self.stop_details,
            model=str(kwargs.get("model", "claude-opus-5")),
        )

    # --- o que o teste interroga --------------------------------------------

    def sent_text(self) -> str:
        """Tudo o que saiu, achatado — o insumo das contra-asserções.

        Inclui o `system`, as mensagens e o `output_config`. **Não** inclui a
        chave da API, que nunca chega ao `create`: ela viaja no construtor do
        cliente, e é isso que o teste do segredo confere separadamente.
        """
        return json.dumps(self.requests, ensure_ascii=False, default=str)

    def last_request(self) -> dict[str, Any]:
        assert self.requests, "nenhum pedido chegou ao modelo"
        return self.requests[-1]

    def user_content(self) -> str:
        """O prompt do usuário do último pedido, que é onde a evidência viaja."""
        return str(self.last_request()["messages"][-1]["content"])


@dataclass
class _FakeMessages:
    client: FakeAnthropic

    def create(self, **kwargs: Any) -> FakeResponse:
        return self.client._create(**kwargs)
