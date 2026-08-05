# Avaliações de IA

Antes de alterar modelo, prompt, chunking ou recuperador, execute dataset de avaliação. Bloqueie regressão em correção, qualidade de citações, isolamento de tenant, recusa de lacunas e resistência a prompt injection.

Desde a ADR 0021 o gatilho de "alterou o prompt" é mecânico e não depende de alguém lembrar:
mudar o `SYSTEM_PROMPT`, o `OUTPUT_SCHEMA` ou a moldura do prompt do usuário sem trocar a
`PROMPT_VERSION` reprova em `test_prompt_version.py`. E a comparação entre execuções passou a ser
possível sobre histórico real, porque cada turno guarda `prompt_version`, `responder` e `model` em
`conversation_message` — antes, uma resposta guardada não sabia o que a produziu.

