# ADR 0017 — Ciclo de vida do documento: varredura, URL temporária e retenção

**Status:** aceita — 05/08/2026
**Contexto:** Fase 5, primeira fatia. Substitui as pendências declaradas nas ADRs 0012, 0014,
0015 e 0016.

## Contexto

Três promessas do repositório não tinham implementação, e as três estavam escritas:

- `docs/security.md` prometia "URLs de arquivo temporárias, validação de upload e **varredura
  antimalware antes de indexar**", e `docs/threat-model.md` repetia na linha "Upload malicioso".
  Não havia varredura: `upload_document` gravava o objeto e o worker abria o arquivo com um
  parser.
- Não havia rota de download. O cliente lia "Documento: Contrato — página 3" e não tinha como
  abrir o documento — a citação apontava para uma evidência que só a equipe interna enxergava,
  o que é uma forma discreta de pedir confiança em vez de mostrar a fonte.
- Retenção estava adiada para a Fase 5 em nove lugares, e `docs/data-classification.md`
  prometia que o conteúdo é "removível por organização". Nada nunca era apagado.

O que amarra as três numa fatia só é serem o mesmo assunto: o que acontece com um arquivo entre
o momento em que ele chega e o momento em que ele deixa de existir.

## Decisão

### 1. A varredura é um eixo próprio, não mais um estado da ingestão

`document` ganha `scan_state` (`pending`/`clean`/`infected`/`skipped`/`error`) ao lado de
`ingest_state`, que ganha só `rejected`.

Seriam duas colunas onde caberia uma — se as perguntas fossem a mesma. Não são: "este arquivo é
seguro" e "este arquivo virou texto citável" podem ter respostas opostas no mesmo documento, e
juntá-las tornaria uma revarredura (assinatura nova sobre arquivo antigo) inexprimível. O
`rejected` em `ingest_state` existe pelo motivo que aquele enum já documentava sobre
`unsupported`: sem um estado para "barrado", a linha ficaria parada em `pending` para sempre.

### 2. Um scanner ausente devolve `skipped`, e nunca `clean`

Esta é a decisão que o resto se apoia, e a única que não se pode afrouxar depois.

O adapter tem a forma de `ai/embeddings.py` — ClamAV quando há `CLAMAV_HOST`, caminho
determinístico quando não há. Mas a analogia para aí. O embedder offline é uma resposta *pior*
à mesma pergunta; um antivírus offline seria uma resposta **inventada** a uma pergunta que
ninguém fez. É exatamente o que a regra 3 do `AGENTS.md` proíbe do assistente, e não há motivo
para o portal se permitir em segurança o que proíbe na IA.

Então `clean` significa "alguém capaz olhou e não achou nada" e `skipped` significa "ninguém que
pudesse afirmar isso olhou". Quem lê a coluna sabe a diferença, e a tela de administração pode
dizê-la.

O que o caminho sem ClamAV faz é reconhecer o **EICAR**, a cadeia de teste padrão da indústria
— inofensiva por construção, criada precisamente para provar que a varredura está ligada. É o
que permite ao CI e ao e2e exercitarem a rejeição sem antivírus e sem rede, do mesmo jeito que o
`drive-stub` prova o conector sem credencial do Google. Fora do EICAR ele responde `skipped`,
que é a verdade.

A cadeia é montada em pedaços no código-fonte. Escrita inteira e literal, faria todo antivírus
de verdade acusar o próprio arquivo que a contém — no checkout de quem clonar, no runner do CI,
no layer da imagem.

### 3. A indexação aceita `clean` **e** `skipped`, e a fronteira é conferida duas vezes

Exigir `clean` faria a stack local nunca indexar nada, porque ela não tem ClamAV. Aceitar
`skipped` é o que mantém a demo viva — e ele continua sendo *outra coisa* que `clean` no banco e
na tela, que é como "ninguém varreu" permanece dizível.

`queue_document_ingestion` deixou de ser a porta. Quem tem um documento novo chama
`queue_document_scan`, e os três chamadores passaram a apontar para lá — o upload, o
`reindex_project` e o sync do Drive. Ponto de entrada único é o que faz o arquivo vindo do Drive
passar pela mesma fronteira do que foi enviado na tela, sem código próprio para cada origem.

E `ingest_document` **recusa** o que não passou, mesmo sendo chamada direto. Uma task antiga na
fila ou um reenfileiramento manual chegam ali sem passar pela varredura, e indexar é
exatamente o que não pode acontecer. É a mesma dupla checagem da pasta do Drive na ADR 0016.

### 4. Arquivo infectado sai do bucket; a linha fica

Isto inverte de propósito o argumento de `delete_document`, que preserva o arquivo do cliente
porque é conteúdo no lugar errado. Aqui o arquivo é a coisa de que se quer distância: ele sai,
e `storage_key` vira nulo na mesma transação — um ponteiro para o que não existe faria a URL
temporária prometer um arquivo ausente.

A linha permanece para a tela explicar o que houve e o `audit_log` guardar o rastro. Um upload
malicioso que desaparece sem deixar registro é um upload malicioso que ninguém investiga.

### 5. O download é uma URL assinada e curta, na rota do cliente

`GET /api/v1/me/documents/{id}/download` devolve `{url, expires_at}` — endereço, não bytes. O
arquivo vai do storage direto para o navegador, o que tira do caminho de requisição o custo de
um PDF de 25 MiB.

Escopada em `/me/` como a caixa de avisos e o histórico da conversa, e não em
`/projects/{id}/`: a citação nasce no chat, que já roda sobre o projeto que `default_project`
resolve. O navegador não manda identificador de projeto nenhum, e o que ele não manda é o que
ninguém precisa validar (regra 1 do `AGENTS.md`).

A URL **não carrega sessão** — quem a tiver, abre. O que a contém é o TTL curto, não a
autenticação: ela é emitida depois da checagem de associação, e o que impede um vazamento de
virar acesso permanente é ela vencer. Nada a guarda; cada clique gera outra.

Só há URL para documento com `scan_state` em `clean`/`skipped`. `pending`, `error` e `infected`
respondem o mesmo 404 de sempre, sem distinguir "não existe" de "não passou" — o cliente não
precisa saber que o portal recebeu um arquivo infectado.

### 6. O prazo mora em tabela própria, não em colunas de `organization`

`organization` vem do snapshot do Biahflow e o `sync_snapshot` faz upsert nela; um prazo
guardado ali seria sobrescrito pelo primeiro webhook que não soubesse dele. É a lição que já
criou `document.origin` e `pending_item.origin`.

`organization_retention_policy` tem uma linha por organização, e **coluna nula significa "usa o
padrão do `config.py`"**, não "guarda para sempre". Um contrato que não fala de retenção não é
um contrato de retenção infinita — e se a ausência de linha significasse o contrário, a poda só
valeria para quem já tivesse sido configurado, ou seja, para ninguém no dia um.

A poda alcança aviso, evento de agente e conversa: as três famílias que crescem sem teto e cujas
ADRs pediram poda pelo nome. **Documento fica de fora**, e é decisão e não esquecimento: ele é a
evidência que sustenta uma citação já dada, e apagá-lo por aniversário tornaria uma resposta
antiga impossível de conferir.

A conversa é podada por `updated_at` e não por `created_at`. Uma thread aberta há um ano e
respondida ontem é a conversa corrente de alguém.

### 7. O expurgo é um pedido gravado, e quem cumpre é o worker

A ADR 0015 já tinha decidido isto quando adiou o assunto: "quando o expurgo chegar, não será o
caminho de requisição a fazê-lo". Uma requisição HTTP que apaga uma organização inteira é uma
transação longa cujo timeout deixa o trabalho pela metade, e é um botão cujo efeito não tem como
ser conferido antes de acontecer.

Então `portal_admin` grava um `data_erasure_request` — com motivo declarado e o `slug` da
organização digitado por extenso, que é o que obriga quem clica a olhar **qual** tenant está na
tela — e o worker o cumpre sob `portal_system`, o único papel que alcança todas as tabelas
envolvidas. A resposta é 202: o trabalho ainda não aconteceu quando ela sai.

A linha do pedido **sobrevive ao próprio expurgo**, e é o ponto. Apagar tudo sem deixar registro
de que se apagou tornaria "o que aconteceu com aquela organização" impossível de responder —
exatamente a pergunta que alguém faz depois. Por isso o expurgo remove o conteúdo dos projetos e
os vínculos, e **não** remove a linha `organization`, que é a âncora que segura o registro.

Também não remove a linha `user`: a identidade é do realm, não do portal, e uma pessoa pode
pertencer a mais de uma organização. Apagar a conta por causa de um tenant tiraria acesso a
outro. O que se desfaz é o vínculo.

A ordem é storage **antes** do banco, e é o inverso da do upload. Lá a linha nasce primeiro
porque o id dela compõe a chave do objeto; aqui a linha é o que sabe quais objetos existem, e
perdê-la primeiro deixaria os arquivos sem quem os encontrasse. Um objeto que sobrevive a uma
falha no meio é recolhido na passagem seguinte pelo prefixo; uma linha apagada com o arquivo de
pé não teria segunda chance.

### 8. `portal_app` não ganha policy nenhuma nas duas tabelas novas

Mesmo desenho de `agent_api_key` (0010) e `project_drive_connection` (0013): o papel do caminho
de requisição herda o SELECT do `ALTER DEFAULT PRIVILEGES` do `roles.sql`, mas nenhuma policy é
`TO portal_app`, então a leitura volta **zero linhas**. É a diferença entre "você não tem
permissão" e "a regra não é sobre você".

Aqui isso guarda uma coisa específica: "suas conversas serão apagadas em 30 dias" é uma frase
que precisa ser dita por uma tela que a explique, não descoberta por quem alcançar a tabela.

E `portal_admin` tem `SELECT, INSERT` no pedido — sem `UPDATE`. Quem pediu não reescreve o
registro do que foi pedido; quem carimba o resultado é o worker, que fez o trabalho. É a mesma
razão do GRANT de coluna da `notification` na ADR 0012.

## Consequências

- A stack local e o CI seguem indexando sem antivírus, e o e2e prova a rejeição com o EICAR.
  Subir ClamAV no compose passa a ser opcional, e em produção é `CLAMAV_HOST` e nada mais.
- O documento antigo do acervo entra com `scan_state = skipped` pelo `server_default`, não
  `clean`. Não há revarredura retroativa nesta migração — quando ela vier, o eixo próprio é o
  que a torna possível de expressar.
- A citação vira link e o cliente confere a página 3. Foi o que faltava para "a IA cita fonte"
  ser verificável por quem lê, e não só por quem escreveu o retriever.
- A poda roda diariamente e é ligada por padrão, ao contrário do sync do Drive: aquele precisa
  de credencial de terceiro, este só precisa do próprio banco.
- **Fica em aberto:** revarredura periódica por assinatura nova, e a tela do cliente que explica
  o prazo de retenção dos dados dele. As duas são funcionalidade, não dívida — o modelo já as
  comporta.

## Alternativas consideradas

- **Varrer no caminho de requisição, dentro do upload.** Um arquivo de 25 MiB contra um ClamAV
  ocupado transformaria o upload num timeout, e a tela não teria como distinguir "demorou" de
  "falhou". A varredura é assíncrona pelo mesmo motivo que a ingestão é.
- **`scan_state` como mais um valor de `ingest_state`.** Cabe até o dia em que se queira
  revarrer um documento já indexado — e aí não há como dizer "limpo e indexado" e "por revarrer
  e indexado" com o mesmo campo.
- **A API servindo os bytes do documento.** Simples e sem URL vazável, mas põe o tráfego de
  arquivo no processo que valida token, e transforma cada download num limite de memória a mais
  para dimensionar.
- **Colunas de retenção em `organization`.** Menos uma tabela e menos uma policy, ao custo de o
  próximo `sync_snapshot` apagar a configuração — o erro que a Fase 2 já cometeu uma vez com as
  pendências.
- **`DELETE /organizations/{id}/data` que apaga na hora.** Direto de ler e impossível de operar:
  sem registro do pedido, sem contagem do que saiu, e com o resultado dependendo de a conexão
  HTTP sobreviver ao trabalho.
