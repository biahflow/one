"""Contextual chat (Fase 3, ADR 0007).

Grounded QA over the project read model: answers only from retrieved evidence, cites its
source, and — when there is no evidence — declares the gap and creates a pendência instead
of inventing (AGENTS regra 3; docs/ai/). Full pgvector RAG over document text stays the
target of ADR 0004.
"""
