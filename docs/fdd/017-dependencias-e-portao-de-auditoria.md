# FDD — Dependências vulneráveis e o portão de auditoria

Fase 5, ADR 0023.

## Objetivo e não objetivos

**Objetivo.** Fechar os avisos de segurança abertos nos dois ecossistemas e fazer com que o
próximo apareça sozinho, no vermelho de um portão, em vez de virar uma linha escrita à mão no
roadmap que atravessa duas fatias.

**Não objetivos.** **Lockfile de transitivas do lado Python** (`pip-compile`/`uv.lock`): é a
resposta certa para a classe de problema do achado 5, e é fatia própria — trocar o mecanismo
de resolução junto com uma remediação torna impossível saber qual dos dois quebrou, mesmo
argumento com que a ADR 0020 adiou os produtores tipados. **SBOM e verificação de proveniência
do registro**: o portão mede o que as ferramentas conhecem, e pacote comprometido sem aviso
publicado é outro controle. **Ligar o CodeQL**: continua sendo configuração de repositório, não
de workflow (ADR 0018). **Migrar o `TestClient` para `httpx2`**, que o Starlette novo
recomenda por depreciação: é aviso de log, não de segurança, e misturá-lo aqui esconderia o que
esta fatia mediu.

## Jornada e interface

**Nenhuma superfície do cliente muda.** O portal continua idêntico na tela — a fatia é
dependência, CI e uma resposta de erro.

Para quem desenvolve, a jornada nova é uma:

```bash
npm run audit     # node scripts/audit.mjs — os dois ecossistemas
```

Reprovou? O caminho está em `docs/runbooks/dependency-advisory.md`. Conserto é bump. Se o bump
não existir ou não couber agora, a única alternativa é escrever a linha em
`docs/security/advisories.json` **com prazo e motivo** — e ela vence.

Para quem integra a API, muda uma coisa e ela é declarada: o corpo de um **422** passa a levar
só `type`, `loc` e `msg`. O `input` que o FastAPI 0.141 acrescentou nunca chegou a ser
publicado — o handler e o esquema saíram no mesmo commit em que o FastAPI subiu.

## Permissões e estados

Nada aqui tem permissão de usuário: não há rota nova, tabela nova nem migração. O 422 é
anterior a qualquer decisão de tenant, e é o mesmo para quem está autenticado e para quem não
está — pelo motivo de sempre, não virar oráculo.

Estados do portão, e cada um é um teste:

| Estado | Resultado |
|---|---|
| Nenhum aviso | passa |
| Aviso sem entrada no registro | **reprova** |
| Aviso com entrada e `review_by` no futuro | passa, e imprime motivo e prazo |
| Aviso com entrada e `review_by` no passado | **reprova** — risco aceito tem prazo |
| Entrada que não casa com aviso nenhum | **reprova** — o arquivo não apodrece |
| Entrada com `id` certo e `package` errado | **reprova dos dois lados** |

## Critérios de aceite

1. `npm audit` e `pip-audit` sem avisos, e `docs/security/advisories.json` **vazio** — a fatia
   consertou em vez de aceitar.
2. O job `dependency-audit` roda em `push` e em `pull_request`, e pode reprovar.
3. Um aviso novo publicado amanhã reprova o CI sem ninguém alterar nada.
4. Uma exceção só existe com motivo e data, e deixa de valer sozinha.
5. Nenhum 422 devolve o corpo da requisição, e o esquema publicado concorda com a resposta.
6. O contrato publicado muda **uma linha**, e ela é revisável.

## Telemetria

Nenhum evento novo. O portão é do CI e fala por código de saída — a decisão da ADR 0018 sobre
alerta ser evento nomeado com limiar escrito não se aplica a algo que não roda em produção.

O que muda em telemetria é por subtração: sete constantes de status depreciadas deixaram de
emitir `StarletteDeprecationWarning` em todo import. Log poluído por aviso que ninguém vai ler
treina a não ler o log, que é a premissa da ADR 0018.

## Testes e avaliações de IA

- `tests/audit-harness.test.mjs`, nove casos, sem build e sem rede. Dois sobre os parsers
  (contra recortes **reais** da saída das ferramentas antes desta fatia) e sete sobre o
  mecanismo de exceção — que é a parte perigosa: um portão cuja lista de exceções nunca foi
  exercitada é indistinguível, no verde do CI, de um portão desligado. Foi assim que as três
  asserções do backup passaram semanas pulando (ADR 0020).
- `apps/api/tests/test_main.py::test_a_422_says_what_is_wrong_without_echoing_what_was_sent`,
  afirmando os **dois** lados: o conteúdo não volta, e o que sobra ainda diz o que consertar.
  Só a primeira metade deixaria passar um handler que devolvesse `{"detail": []}`.
- `apps/api/tests/test_openapi_contract.py`: sem caso novo, e é o ponto — o gate de deriva já
  existente foi quem **pegou** a mudança de contrato do FastAPI novo, que é para o que ele foi
  feito.
- **Sem eval de IA.** Nada aqui toca prompt, recuperador, modelo ou ferramenta.
- **Sem spec de e2e novo.** O que a fatia pede do e2e é o que ele já faz: o `login.spec.ts`
  exercita o Server Action inline e o `proxy.ts` na imagem real, que são os dois pontos onde um
  bump de Next machuca.
