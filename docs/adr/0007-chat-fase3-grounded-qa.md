# ADR 0007 — Chat contextual (Fase 3): grounded QA sobre o read model

**Status:** Aceito

## Contexto

O contrato de IA (ADR 0004, `docs/ai/*`, AGENTS regra 3) exige respostas só com evidência do
projeto, com citação, e pendência quando falta evidência — nunca inventar. O RAG completo
com pgvector sobre o texto dos documentos (ADR 0004) ainda não existe; o read model hoje só
tem dados estruturados (Projeto, Marcos, Pendências), pois documentos não são ingeridos como
texto.

## Decisão

O chat (`POST /api/v1/chat`) faz **grounded QA sobre o read model estruturado**, escopado por
tenant (identidade `X-Portal-User` → membership; ADR 0002). O pacote `portal_api.ai` separa:
recuperação (`retrieval`, filtrada pelo `TenantContext`), prompt **versionado** que trata a
evidência como dado não confiável (`prompt`), um **adapter de provedor** (`responder`) que usa
a API da Claude (`claude-opus-4-8`) quando `ANTHROPIC_API_KEY` está configurada e um
**respondedor offline determinístico** caso contrário, e a orquestração (`service`) que exige
citação de evidência real e, na ausência, cria uma pendência (`PendingItem`) — nunca fato sem
fonte.

## Consequências

Funciona na demo/CI sem chave (offline determinístico) e vira IA real ao configurar a chave —
mesma forma de saída `{answer, sources, confidence, pending_created}`. As avaliações
(`apps/api/tests/test_chat_ai.py`) cobrem os casos de `docs/ai/eval-dataset.md` (produção,
financeiro, pendências, fonte removida, lacuna, prompt injection, acesso a outro projeto,
integridade de citação) e bloqueiam regressão, conforme `docs/ai/evaluation-plan.md`. A
ingestão de documentos, chunking, embeddings e recuperação por similaridade permanecem o alvo
da ADR 0004 (Fase 4).
