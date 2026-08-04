# ADR 0014 — Ingestão de documentos e recuperação por similaridade

**Status:** Aceito — 04/08/2026

## Contexto

O aceite da Fase 4 diz: *"perguntas sobre produção, decisões financeiras e pendências retornam
fontes corretas; falta de evidência cria uma pendência, sem resposta inventada."* A segunda
metade já valia desde a ADR 0007 — o chat é *grounded*, cita ou declara lacuna. A primeira não:
a recuperação enxergava só o read model estruturado (projeto, marcos, pendências), e qualquer
pergunta cuja resposta estivesse num contrato, numa ata ou num manual virava pendência. O
assistente não estava errado; estava cego.

A tabela `document` existia desde a migração `0002` carregando apenas metadado — `storage_key`
nasceu nullable com um comentário dizendo "Fase 4" — e `worker.reindex_project` era um
placeholder que devolvia `{"status": "queued"}` sem fazer nada. Nenhum arquivo jamais entrou no
portal.

Restrições herdadas que moldam a solução:

1. **O portal não origina status** (ADR 0006/0008), e o sync **substitui** o que espelha.
2. **Privilégio mora na credencial** (ADR 0010/0011); `portal_app` é o caminho de requisição e
   escreve em pouquíssimas tabelas.
3. **Toda tabela com `organization_id` sai com policy na mesma migração**, e um meta-teste
   quebra o CI se não sair.
4. **Resposta sem citação não existe** (AGENTS.md #3), e citação errada é pior que citação
   nenhuma — quem confere não encontra e para de confiar no resto.

## Decisão

### 1. A porta de entrada é o upload de administração, não o Drive

O item de Fase 4 mais visível no roadmap é o conector do Google Drive. Ele fica para depois, e a
ordem é deliberada: o conector é uma forma de **encher** o índice, e sem índice não há o que
encher. Fazê-lo primeiro exigiria OAuth, uma pasta permitida por projeto e reconciliação
idempotente antes de existir uma única linha em `document_chunk` — e a primeira prova de que o
chat cita documento dependeria de credencial de um provedor externo que o ambiente local não tem.

O upload vive em `admin.py`, sob `portal_admin`, ao lado das chaves de agente e das premissas
financeiras. É escrita, e escrita de configuração já mora lá. O cliente não envia documento: ele
pergunta, e a resposta cita o que foi indexado. Um upload no lado do cliente inverteria a
direção do produto — o portal presta contas do projeto, não recebe material dele.

### 2. `document` ganha `origin`, senão indexar tem prazo de validade

`sync_snapshot` apaga e recria os documentos do projeto a cada webhook. Um arquivo enviado no
portal — e todo o índice dele — morreria no snapshot seguinte, sem erro, sem log, sem nada na
tela. A coluna `origin` (`biahflow` | `portal`) faz o delete do sync alcançar só o que ele
espelha, exatamente como `PendingItem.origin` resolveu o mesmo problema para a pendência que a
IA abre por lacuna (migração `0006`).

Consequência assumida: documento espelhado do Biahflow **não é apagável** pela tela do portal.
Ele voltaria no próximo sync, e oferecer o botão prometeria uma remoção que o portal não tem
como cumprir.

### 3. Quem escreve o índice é o worker, sob `portal_system`

A ADR 0013 argumentou o oposto para a ingestão de eventos: escrever sob `portal_app` com
`WITH CHECK`, para a RLS ser a segunda barreira justamente na rota que recebe `projectId` de
fora. A diferença aqui é qual é a entrada não confiável. Na ingestão de agentes, é o corpo da
requisição. Na ingestão de documentos, o tenant vem dos argumentos de uma task que só foi
enfileirada por uma rota de administração que já verificou `internal_admin` — não há
identificador vindo de fora para desconfiar.

O que se ganha em troca é mais valioso: `portal_app` fica **SELECT-only** em `document_chunk`.
Se o caminho de requisição pudesse gravar um trecho, poderia gravar a "evidência" que quisesse
ver citada — e a política de citação inteira (ADR 0007) passaria a se apoiar em algo que o
próprio pedido do usuário pode escrever. É o mesmo desenho de `notification`, e pelo mesmo
motivo: o request path lê o que outro produziu.

`portal_admin` ganha `INSERT/UPDATE/DELETE` em `document`, porque é ele que recebe o arquivo.

### 4. O trecho nunca cruza a fronteira da página

A citação diz "página 3". Ou isso é verdade, ou a citação é ruído com aparência de fonte. Como o
chunking é quem decide onde o texto é cortado, é ele quem decide se a página é verdade: o corte
recomeça em toda virada de página, e um trecho carrega a localização da única página de onde
saiu. Dentro da página, o corte segue parágrafos com sobreposição — a frase que responde
costuma estar na emenda de dois trechos.

Formato sem paginação confiável (`.docx`, `.md`, `.txt`) declara página 0 e a citação sai **sem
localização**. Estimar uma página a partir de contagem de caracteres seria produzir exatamente o
erro que a regra existe para evitar.

### 5. Embeddings por adapter, com caminho offline determinístico

Mesma forma da ADR 0007 para o respondedor, e pelo mesmo motivo: CI e demo precisam indexar e
recuperar sem chave e sem rede, e o caminho offline não pode ser um mock — é o que roda na
demonstração. Com `VOYAGE_API_KEY` o provedor é a Voyage (`voyage-3`, 1024 dimensões); sem ela, é
uma projeção determinística por hashing de tokens, normalizada, na mesma dimensão.

Voyage e não Anthropic porque a Claude API não tem endpoint de embeddings; é o provedor que a
própria Anthropic recomenda. A dimensão é fixa na coluna: vetores de dimensões diferentes não são
comparáveis, então trocar de modelo é uma migração mais uma reindexação — nunca uma variável de
ambiente. Cada trecho guarda o `embedding_model` que o produziu, para essa troca ser visível.

**O corte de distância pertence ao adapter, não à recuperação.** Um espaço semântico treinado
aproxima pergunta e resposta mesmo sem palavra em comum; o embedder offline é lexical, e nele a
distância entre uma pergunta curta e um parágrafo longo é estruturalmente alta mesmo quando o
parágrafo responde. Um número só para os dois deixaria a demo sem citar nada ou o provedor real
citando qualquer coisa. Por isso são duas configurações, e quem escolhe é o embedder.

Sem corte nenhum, toda pergunta encontraria "o trecho menos distante" e o citaria. É o corte que
faz a recuperação conseguir dizer *não há evidência* — que é como ela deixa o serviço abrir a
pendência, em vez de responder com o que sobrou.

### 6. `Evidence` já era o contrato, e por isso o RAG não tocou no prompt

`ai/retrieval.Evidence` é `{id, source, location, text}` desde a Fase 3. O trecho de documento
entra como mais uma evidência, e `prompt.py`, `responder.py` e `service.py` — cite-or-gap,
integridade de citação, pendência por lacuna — não mudaram uma linha. A única mudança no
respondedor offline foi passar a considerar trechos nos ramos temáticos: a recuperação por
similaridade já filtrou por relevância antes, e descartar o trecho por ele não ser marco nem
pendência jogaria fora a única evidência capaz de responder.

O texto do documento continua sendo tratado como **dado, não instrução**, pela mesma delimitação
`<evidencias>` que já existia. Um documento com prompt injection dentro é conteúdo do cliente
como qualquer outro.

### 7. O `search_path` passa a incluir `public`

A extensão `vector` é criada pelo bootstrap no schema `public`, mas a conexão fixa
`search_path=portal` (ADR 0010) para DDL e reflexão ficarem sem qualificação. O tipo `vector`
simplesmente não resolvia. `portal` continua sendo o primeiro da lista — tabela nova sem
qualificação segue nascendo nele e o `alembic check` continua limpo — e `public` entra só para o
tipo. O `roles.sql` já concedia `USAGE ON SCHEMA public` prevendo isto.

### 8. Documento apagado é apagado

Ao contrário da chave de agente, que é **revogada** para preservar o rastro de que existiu e foi
usada. Um documento enviado por engano é conteúdo do cliente no lugar errado, e mantê-lo
"revogado" seria manter o problema. Linha, trechos (por CASCADE) e objeto no storage saem juntos;
a remoção do objeto é best-effort, porque a linha é o que a tela mostra e um objeto órfão é
problema de retenção — item da Fase 5 —, não um erro na cara de quem apagou.

## Consequências

- **`portal_app` não ganhou nenhuma escrita nova.** A lista da ADR 0010 continua com quatro
  tabelas; `document_chunk` é leitura pura para ele.
- **A ingestão é assíncrona e o estado é visível.** `document.ingest_state` (`pending` |
  `indexed` | `failed` | `unsupported`) existe para "por que a IA não sabe disso?" ter resposta
  na tela. `unsupported` é estado e não erro: um `.zip` enviado por engano, ou um PDF digitalizado
  sem texto, não são falha de sistema.
- **Idempotência pelo hash do arquivo.** Task reentregue não recobra embeddings. Arquivo trocado
  reescreve o índice inteiro do documento, o que mantém `ordinal` contíguo quando ele encolhe.
- **Broker morto degrada, não derruba.** O upload responde 201 com o documento em `pending`;
  `reindex_project` varre o que ficou para trás. Mesma tolerância de `queue_project_digests`.
- **Cinco dependências novas** — `boto3`, `pgvector`, `pypdf`, `python-docx`, `voyageai` — e a
  primeira delas que fala com um serviço fora do Postgres no caminho de requisição.
  `VOYAGE_API_KEY` é opcional por construção.
- **O índice não tem reindexação em massa por troca de modelo.** Trocar de embedder exige rodar
  `reindex_project` por projeto, e os trechos antigos continuam recuperáveis (e errados) até lá.
  Detectar `embedding_model` obsoleto e reindexar sozinho é evolução natural.
- **A busca dentro do portal continua não existindo.** O aceite da Fase 1 previa filtro por
  organização/projeto na busca; o que existe agora é recuperação para o chat, não uma tela de
  busca.

## Alternativas consideradas

**Indexar sob `portal_app` com `WITH CHECK`, como a ADR 0013 fez para eventos.** Manteria a
simetria entre as duas ingestões. Mas ali a RLS defende contra um `projectId` recebido de fora, e
aqui não há nenhum — o que a simetria custaria é dar ao caminho de requisição a capacidade de
escrever a evidência que ele mesmo vai citar.

**Chunk por número de tokens, ignorando páginas.** Melhor aproveitamento da janela de contexto e
menos trechos. Custa a única coisa que a citação tem para oferecer: a localização verificável.

**Embedder único, sem caminho offline.** Metade do código. Deixaria o CI dependente de uma chave
de terceiro e a demonstração local sem chat com documentos — e o eval determinístico da ADR 0007,
que é o que bloqueia regressão de citação, deixaria de ser determinístico.

**Guardar o texto extraído em `document` e recuperar por `tsvector`/ILIKE.** Sem dependência de
provedor e sem pgvector. Recuperaria só o que repete as palavras da pergunta — que é exatamente o
teto do embedder offline, adotado aqui como *fallback* e não como desenho.
