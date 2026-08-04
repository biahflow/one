# FDD 002 — Chat contextual

Cliente pergunta em linguagem natural. A IA recupera somente fontes do projeto, responde com citações e registra pendência quando a evidência não for suficiente. Avaliações incluem produção, decisões financeiras, pendências e prompt injection.

## Fase 3 — implementação (ADR 0007)

Grounded QA sobre o read model estruturado (Projeto, Marcos, Pendências), escopado por tenant via `X-Portal-User`. Provedor por adapter: Claude (`claude-opus-4-8`) quando há `ANTHROPIC_API_KEY`, senão respondedor offline determinístico. Documentos como texto (pgvector) seguem na ADR 0004 (Fase 4).

**Critérios de aceite:** toda afirmação factual cita evidência real; sem evidência → cria pendência e retorna `confidence="insufficient_context"`; cliente só acessa o próprio projeto (permissão negativa → 404); instrução dentro da evidência é tratada como dado. **Testes/evals:** `apps/api/tests/test_chat_ai.py` cobre os 8 casos de `docs/ai/eval-dataset.md` e roda determinístico em CI (sem chave).
