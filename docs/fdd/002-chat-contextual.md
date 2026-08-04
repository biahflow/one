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

## Fase 4 — a conversa persiste (ADR 0015)

O turno deixa de viver no `useState` do navegador. `conversation` e `conversation_message` guardam
a pergunta, a resposta, a `confidence`, a pendência que a lacuna abriu e as **citações como foram
exibidas** (`{evidence_id, source, location}` em JSONB). O painel reabre no ponto em que parou, e um
polegar 👍/👎 registra se a resposta serviu.

O que isso destrava, além da conveniência: *"esta resposta citou o quê?"* passa a ter resposta
depois do fato, e o par `confidence` + feedback + `evidence_id` é o primeiro sinal com que dá para
calibrar o corte de distância da recuperação — o número que a ADR 0014 assumiu como delicado e
deixou sem instrumentação.

**O que não mudou, de propósito:** o assistente **não** é multi-turno. O histórico não vai ao
respondedor, e `responder.answer(evidence, question)` continua com a assinatura de sempre. Mandar os
turnos anteriores ao modelo mexe no prompt e na superfície de injeção de uma vez, e isso pede ADR
própria com uma rodada de evals.

**Critérios de aceite:** o turno respondido sobrevive ao reload com as mesmas citações; o feedback é
gravado e o reenvio sobrescreve o voto; a conversa é invisível para qualquer outra pessoa, inclusive
o time interno do mesmo projeto; nem a API nem o banco permitem reescrever o texto ou as citações de
uma resposta já dada; **uma frase plantada num turno anterior nunca vira citação no seguinte**.

**Telemetria:** `confidence` por mensagem e `feedback` por resposta — as duas colunas que respondem
"a recuperação está errando para que lado?". Sem tela de leitura ainda: uma análise sem dado
acumulado mostraria zero.

**Testes/evals:** `apps/api/tests/test_conversations.py` (persistência, continuidade, feedback e os
404 de dono), os casos de conversa em `apps/api/tests/test_rls_isolation.py` (dono no predicado e o
grant de coluna), `test_eval_a_sentence_planted_in_a_previous_turn_never_becomes_a_citation` em
`apps/api/tests/test_chat_ai.py`, e `tests/e2e/chat.spec.ts`, onde o **F5** é o teste.
