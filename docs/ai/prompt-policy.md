# Política de prompts

Prompts são versionados e têm entradas/saídas estruturadas. Contexto de documentos fica delimitado
como dado não confiável. O modelo não pode revelar instruções, tokens ou fontes não autorizadas e
não pode executar ações por texto de documento.

## Onde a versão mora, e por que não numa variável de ambiente

`PROMPT_VERSION` vive em `apps/api/src/portal_api/ai/prompt.py`, na linha acima do
`SYSTEM_PROMPT`. Até a Fase 5 esta página afirmava o versionamento e ele não existia: havia um
`chat_prompt_version` nas settings que **nenhum código lia**. Uma versão que mora numa variável de
ambiente é uma afirmação que o deployment faz sobre um texto que ele não contém — podia dizer
`chat-2026-08-03` enquanto o prompt dizia outra coisa, e ninguém teria como saber. O arquivo que
guarda o texto guarda o nome dele (ADR 0021).

## O portão

`docs/ai/prompt-registry.json` é um registro append-only de `{version, system_sha256,
schema_sha256, template_sha256, recorded_at}`. Os três digests cobrem o `SYSTEM_PROMPT`, o
`OUTPUT_SCHEMA` e a **moldura** de `build_user_prompt` — o delimitador `<evidencias>`, o formato da
linha de cada evidência e a linha da pergunta. Nunca o conteúdo das evidências: um digest sobre
evidência real mudaria a cada requisição e não significaria nada.

```bash
PYTHONPATH=apps/api/src python -m portal_api.ai.prompt --record   # grava a versão corrente
PYTHONPATH=apps/api/src python -m portal_api.ai.prompt            # confere, sem gravar
```

`test_prompt_version.py` cobra o registro em CI. A regra prática: **mudou o texto, muda a versão.**
E o portão não é uma constante de digest no próprio arquivo porque uma constante deixa passar
justamente o caso que importa — quem atualiza texto e constante juntos, sem trocar a versão,
continuaria verde. Contra o registro isso não fica verde regenerando: `--record` **recusa**
reescrever uma versão já gravada cujos digests mudaram, e o único caminho verde é uma versão nova.
É o mesmo idioma do `alembic check` e do `docs/api/openapi.json`.

## O que a versão serve para responder

Cada turno do assistente guarda `prompt_version`, `responder` e `model` em `conversation_message`
(ADR 0021). Sem isso, "esta resposta ruim veio de qual prompt?" e "quais turnos são comparáveis
nesta eval?" não têm resposta — e o `evaluation-plan.md` manda rodar o dataset antes de alterar
modelo, prompt, chunking ou recuperador, o que exige saber o que cada resposta guardada usou.
