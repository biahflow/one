# FDD 002 — Chat contextual

Cliente pergunta em linguagem natural. A IA recupera somente fontes do projeto, responde com citações e registra pendência quando a evidência não for suficiente. Avaliações incluem produção, decisões financeiras, pendências e prompt injection.

## Fase 3 — implementação (ADR 0007)

Grounded QA sobre o read model estruturado (Projeto, Marcos, Pendências), escopado por tenant a partir do principal do token OIDC (ADR 0010; antes era o header `X-Portal-User`). Provedor por adapter: Claude (`claude-opus-4-8`) quando há `ANTHROPIC_API_KEY`, senão respondedor offline determinístico. Documentos como texto (pgvector) seguem na ADR 0004 (Fase 4).

**Critérios de aceite:** toda afirmação factual cita evidência real; sem evidência → cria pendência e retorna `confidence="insufficient_context"`; cliente só acessa o próprio projeto (permissão negativa → 404); instrução dentro da evidência é tratada como dado. **Testes/evals:** `apps/api/tests/test_chat_ai.py` cobre os casos de `docs/ai/eval-dataset.md` e roda determinístico em CI (sem chave).

## Fase 4 — o documento entra na recuperação (ADR 0014)

A recuperação passa a somar duas fontes: o read model estruturado e os **trechos dos documentos
indexados**, buscados por similaridade em `pgvector` e filtrados pelo tenant. A citação nomeia o
documento e a página de onde o trecho saiu (`"Documento: Contrato — página 3"`).

Prompt, respondedor e política de citação **não mudaram**: `Evidence` já era o contrato entre
recuperação e resposta, e o trecho entra ali como mais uma. O que muda é o alcance — uma pergunta
sobre cláusula de contrato deixa de ser lacuna automática. Continua sendo lacuna quando nenhum
trecho passa do corte de distância, e é isso que impede "o trecho menos distante" de virar fonte.
Detalhes da ingestão em `docs/fdd/009-ingestao-e-indice-do-projeto.md`.
