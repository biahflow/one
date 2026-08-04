"""Divisão do texto em trechos citáveis (ADR 0014).

Uma regra manda em todo o resto: **o trecho nunca cruza a fronteira da página**.
É o que faz "página 3" na citação ser verdade e não estimativa — e citação que
aponta para o lugar errado é pior do que não citar, porque o cliente confere e
não encontra (docs/ai/eval-dataset.md).

Dentro da página, o corte segue parágrafos, não caracteres: um trecho que começa
no meio de uma frase chega ao modelo como evidência truncada. A sobreposição
existe pelo motivo inverso — a frase que responde a pergunta pode estar
justamente na emenda de dois trechos.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from portal_api.ingestion.extract import ExtractedPage

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_WHITESPACE = re.compile(r"[ \t]+")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str
    #: Rótulo exibido na citação ("página 3"), vazio quando o formato não pagina.
    location: str
    content_hash: str


def chunk_pages(
    pages: list[ExtractedPage], *, size: int = 1200, overlap: int = 150
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in pages:
        location = f"página {page.number}" if page.number else ""
        for text in _split(page.text, size=size, overlap=overlap):
            chunks.append(
                Chunk(
                    ordinal=len(chunks),
                    text=text,
                    location=location,
                    content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
    return chunks


def _split(text: str, *, size: int, overlap: int) -> list[str]:
    parts: list[str] = []
    for block in _PARAGRAPH_BREAK.split(text):
        cleaned = _WHITESPACE.sub(" ", block).strip()
        if not cleaned:
            continue
        parts.extend(_hard_split(cleaned, size) if len(cleaned) > size else [cleaned])

    out: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}\n\n{part}" if current else part
        if current and len(candidate) > size:
            out.append(current)
            tail = _tail(current, overlap)
            # O trecho seguinte pode passar de `size` pelo tamanho da emenda; o
            # teto real é `size + overlap`, e é intencional — cortar a
            # sobreposição para caber no número redondo desfaria o efeito dela.
            current = f"{tail}\n\n{part}" if tail else part
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def _hard_split(block: str, size: int) -> list[str]:
    """Quebra um parágrafo maior que o trecho, preferindo o espaço mais à direita."""
    parts: list[str] = []
    start = 0
    while start < len(block):
        end = min(start + size, len(block))
        if end < len(block):
            cut = block.rfind(" ", start + size // 2, end)
            if cut > start:
                end = cut
        fragment = block[start:end].strip()
        if fragment:
            parts.append(fragment)
        start = end
    return parts


def _tail(text: str, overlap: int) -> str:
    """O fim do trecho anterior, começando numa fronteira de palavra."""
    if overlap <= 0:
        return ""
    if len(text) <= overlap:
        return text
    fragment = text[-overlap:]
    space = fragment.find(" ")
    return fragment[space + 1 :].strip() if space != -1 else fragment.strip()
