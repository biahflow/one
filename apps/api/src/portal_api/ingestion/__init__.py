"""Ingestão de documentos: arquivo → texto → trechos citáveis (ADR 0014).

Duas etapas puras, sem banco e sem rede, para poderem ser testadas sozinhas:
:mod:`portal_api.ingestion.extract` transforma bytes em páginas e
:mod:`portal_api.ingestion.chunk` transforma páginas em trechos. Quem persiste é
o worker.
"""

from portal_api.ingestion.chunk import Chunk, chunk_pages
from portal_api.ingestion.extract import (
    SUPPORTED_MIME_TYPES,
    ExtractedPage,
    ExtractionFailed,
    UnsupportedDocument,
    extract,
)

__all__ = [
    "SUPPORTED_MIME_TYPES",
    "Chunk",
    "ExtractedPage",
    "ExtractionFailed",
    "UnsupportedDocument",
    "chunk_pages",
    "extract",
]
