# ADR 0016 — Conector Google Drive: OAuth por projeto e sincronização idempotente

**Status:** Aceito — 04/08/2026

## Contexto

A ADR 0014 deu olhos ao assistente e deixou uma porta só: o upload de administração.
Fechou dizendo por que o conector do Drive ficava para depois — *"o conector é uma forma de
**encher** o índice, e sem índice não há o que encher"*. O índice existe agora, e o item que
sobrou na Fase 4 é este.

O que está errado hoje: o arquivo que vive no Drive do cliente chega ao portal como metadado
com link, espelhado do snapshot do Biahflow. Ele aparece na aba Documentos e o assistente
**não consegue citá-lo**. Quem quiser que o chat responda sobre um contrato precisa baixá-lo do
Drive e reenviá-lo pela administração — trabalho manual que se desatualiza em silêncio, porque
nada avisa quando a versão no Drive muda.

Restrições herdadas, e todas mordem aqui:

1. **Apenas conteúdo da pasta autorizada é sincronizado e indexado** (FDD 003), com **escopo
   readonly e folder allowlist**, e o `docs/threat-model.md` cobra nominalmente um *teste de
   sync fora da pasta*.
2. **Preservar último índice válido** (`docs/runbooks/drive-sync-failure.md`). Falha do
   provedor não pode virar perda de conhecimento do cliente.
3. **Privilégio mora na credencial** (ADR 0010/0011), e **toda tabela com `organization_id` sai
   com policy na mesma migração**.
4. **Quem escreve o índice é o worker sob `portal_system`** (ADR 0014 §3).
5. **Citação errada é pior que citação nenhuma** (AGENTS.md #3).

## Decisão

### 1. OAuth por projeto, e o consentimento é de uma conta

Uma conexão por projeto, garantida por `UniqueConstraint` na tabela: "uma pasta permitida por
projeto" é a fronteira em que todo o resto se apoia, e duas linhas fariam "a pasta autorizada"
deixar de ter resposta.

A alternativa era uma service account do Google Cloud com a pasta compartilhada com ela.
Custaria menos código — nada de fluxo OAuth, nada de refresh token guardado — mas exigiria que
alguém do lado do cliente fizesse o compartilhamento manualmente, e não funciona fora do
Workspace. O consentimento delegado é o que o ROADMAP descreve e o que funciona com um Drive
pessoal.

O escopo é `drive.readonly` e **só ele**. O Google pode conceder um conjunto diferente do
pedido; quando concede, a conexão é recusada sem gravar nada. Aceitar "mais do que pedi"
transformaria o escopo somente-leitura numa intenção em vez de um controle — e é um controle
que o threat model nomeia.

### 2. O primeiro segredo **reversível** do repositório

A ADR 0013 escreveu o argumento oposto e continua certa no terreno dela: a chave de agente vira
HMAC sob pepper porque *"o que precisamos é que o conteúdo do banco, sozinho, não valha nada"*.
Isso funciona porque a chave só precisa ser **verificada**.

Um refresh token não tem essa forma. Ele é **reapresentado** ao Google a cada sincronização, e
não existe "comparar" um refresh token — existe usá-lo. Hash não serve.

O que se perde é real e fica escrito: com a chave de cifra, o conteúdo do banco vira
credencial. Daí três escolhas:

- **AES-256-GCM com AAD**, e não uma cifra sem dado associado. `portal_admin` escreve nesta
  tabela, e um ciphertext sem vínculo criptográfico ao tenant é copiável de uma linha para
  outra. Amarrando o AAD a `drive-refresh:<organization_id>:<project_id>`, um refresh token
  movido para outro projeto **falha a decifra** em vez de sincronizar a pasta errada. A RLS já
  impede a leitura cruzada; isto é a segunda barreira, e custa uma string.
- **A chave vive só em variável de ambiente**, nunca no banco que ela protege, e sem ela a
  falha é fechada — como `hash_key` sem pepper.
- **Duas chaves, e a segunda não é luxo.** O pepper da 0013 pode ser girado porque chaves de
  agente são reemissíveis. Aqui não: girar sem uma janela de decifra obrigaria **cada projeto a
  refazer o consentimento no Google**. O identificador da chave viaja no texto selado, então o
  sync seguinte decifra com a anterior e re-sela com a atual, sem migração de dados.

Só o refresh token fica em repouso. O access token vale uma hora, é pedido a cada sync e vive
em memória — guardar o de vida curta aumentaria a superfície para poupar uma chamada.

### 3. O callback mora no BFF, e **fora de `/api/`**

Duas razões, e a primeira encerra a discussão: o `redirect_uri` registrado no Google é um
endereço que o **navegador** visita, e a API não é publicamente roteável (`API_BASE_URL:
http://api:8000`, rede interna). Não existe endereço da API para o Google mandar o navegador.
De quebra, a API continua sem uma segunda rota sem `principal` — `POST /api/v1/agent-events`
segue sendo a única exceção.

A segunda razão é do Next: `proxy.ts` responde **401 JSON** a tudo sob `/api/` e só redireciona
para `/login` fora dele. O callback é navegação de topo vinda de outro site; se a sessão
expirar enquanto a pessoa está na tela de consentimento, `/api/drive/callback` entregaria JSON
no lugar da tela de login. Em `/admin/conhecimento/drive-callback` ela cai no login e recomeça.

**O code exchange fica na API**, não no BFF: é lá que moram o `client_secret` do Google e a
chave de cifra. Fazer a troca no BFF traria o refresh token em claro para uma camada que não
precisa dele.

O `state` tem três defesas independentes: o callback só é alcançável com sessão (o portão do
`proxy.ts`); o lastro no banco é **hash, com prazo e de uso único**, consumido *antes* da troca
— quem chega em segundo não acha mais nada; e o PKCE S256 faz um `code` interceptado sozinho
não virar token. Nada disso *autoriza*: a autorização é o `internal_admin` verificado no
`_authorized` de sempre, mais a conferência de que quem voltou é quem pediu.

A rota do callback **não recebe `project_id`**: ele sai da linha achada pelo `state`, do mesmo
jeito que o tenant da ADR 0013 sai da chave em vez do corpo. Um `project_id` ali seria um
identificador de fora para desconfiar sem motivo.

### 4. `document.origin` ganha um terceiro valor

`DocumentSource.drive` já existe e quer dizer outra coisa: o documento que o Biahflow espelha
como metadado e link, sem arquivo nenhum. Os dois falam do Drive e significam o oposto —
"existe lá" contra "veio de lá e está indexado aqui".

Sem o terceiro valor de `origin`, ou o `DELETE ... WHERE origin='biahflow'` do `sync_snapshot`
apagaria o conteúdo sincronizado, ou o sync do Drive apagaria o que a administração enviou. É o
mesmo argumento que criou a coluna na 0011.

**Custo assumido, e ele aparece na migração:** o Postgres aceita `ALTER TYPE ... ADD VALUE`
dentro de uma transação mas recusa **usar** o valor antes que ela feche, e o índice único
parcial `WHERE origin = 'drive'` usa. Como o `env.py` roda o upgrade inteiro numa transação só,
dividir em duas revisões não resolveria. A 0013 recria o tipo — a restrição é sobre valor
adicionado, não sobre tipo criado —, ao preço de uma reescrita da tabela `document`. O
predicado tem de ser comparação de enum, e não `origin::text = 'drive'`: um predicado de índice
só aceita função `IMMUTABLE`, e o cast de enum para texto é `STABLE`.

Consequência de produto: documento vindo do Drive **não é apagável pela tela**, pela mesma
razão do espelhado do Biahflow (ADR 0014 §2) — ele voltaria no próximo sync. A forma de removê-lo
é tirá-lo da pasta.

### 5. A pasta é a fronteira, e ela é verificada duas vezes

Primeiro porque **não existe caminho que aceite um id de arquivo vindo de fora**: a única fonte
de ids é a travessia, que começa na pasta conectada. Depois porque, antes de qualquer download,
o arquivo tem de declarar como pai uma das pastas que a travessia alcançou. A segunda checagem
parece redundante e não é — ela é a que um teste consegue atacar, e o threat model cobra
exatamente esse teste.

Duas armadilhas tratadas por nome:

- **atalho não é seguido.** `application/vnd.google-apps.shortcut` mora dentro da pasta
  autorizada com um `parents` perfeitamente legal e aponta para qualquer arquivo do Drive.
  Segui-lo abriria a fronteira por dentro. É ignorado e contado.
- **a árvore é um grafo.** O Drive permite mais de um pai, então a travessia em largura carrega
  um conjunto de visitados; sem ele, um ciclo trivial trava o sync.

A recursão tem teto de profundidade e teto de arquivos. Estourar o teto **não** é erro: marca
`truncated`, e o que foi enumerado continua válido — o que não pode é a listagem truncada ser
tratada como completa.

### 6. Só remove sobre listagem completa

É a tradução direta do runbook. Uma enumeração que falhou no meio, ou que estourou o teto,
descreve um Drive menor do que o real; tratá-la como verdade apagaria o índice do cliente por
causa de uma indisponibilidade do Google. Consentimento revogado é o mesmo caso: pausa a pasta
(`enabled = false`), carimba o motivo, **e não toca no índice**.

Quando a listagem é completa e um arquivo sumiu, ele sai de verdade — linha, trechos e objeto.
Continuar citando um contrato que o cliente apagou do Drive é exatamente a citação que quem
confere não encontra.

### 7. Dois portões antes de gastar

O barato é o `modifiedTime`, que evita o download. O exato é o SHA-256 dos bytes, que evita o
`put_object` e os embeddings — alguém abrir e fechar um documento muda a data e não muda o
conteúdo. Um sync horário de uma pasta parada custa uma listagem e nada mais.

O portão barato é `modifiedTime` e **não** `md5Checksum` porque arquivo nativo do Google não
tem md5: usar o md5 faria todo Google Doc parecer alterado a cada sync, e o portal recobraria
embeddings para sempre sem nada ter mudado.

### 8. O beat, que ainda não existia

A ADR 0005 já reivindicava o sync do Drive como job desde sempre; o que faltava era quem
acordasse. O `beat_schedule` entra agora, com um serviço próprio no compose porque **o beat é
singleton**: duas réplicas significam ticks duplicados. O tick só faz fan-out — sincronizar
dentro dele faria uma pasta lenta atrasar todas as outras.

A guarda de sobreposição é um `UPDATE` condicional na própria linha, não um lock em Redis:
mesmo argumento da janela de rate limit da 0013. Dois ticks chegando juntos precisam que
exatamente um ganhe, e quem decide isso é o banco. A janela de `sync_started_at` é o que impede
um worker morto no meio de travar a pasta para sempre.

### 9. Nenhuma dependência nova de rede

O Drive v3 é REST e o refresh é um POST de formulário. O `google-api-python-client` traria uma
árvore de dependências para dois endpoints; o `httpx` já está aqui desde o Biahflow. O
`cryptography` passa a ser declarado **direto** — ele já chegava pelo `pyjwt[crypto]`, e
depender de trânsito de outra biblioteca para um módulo de cifra é dívida.

## Consequências

- **O portal passa a guardar credencial de terceiro.** É novidade de categoria, não de volume:
  `docs/data-classification.md` já classificava token como segredo, mas até aqui nenhum vivia
  em repouso no banco.
- **Um serviço novo no compose para o e2e.** O `drive-stub` é a única forma de provar o
  conector ponta a ponta sem credencial do Google — e o threat model exige o teste de sync fora
  da pasta. Roda com a mesma imagem da API, e as três URLs de base existem separadas
  justamente para poderem apontar para ele, como `BIAHFLOW_BASE_URL` já permitia.
- **O beat é infraestrutura nova a operar.** Precisa de réplica única, e um beat parado é um
  índice que envelhece em silêncio — o botão "Sincronizar agora" existe também por isso.
- **A planilha exporta só a primeira aba.** Limitação do Google, registrada na FDD 010 para o
  usuário ler na tela em vez de descobrir pela ausência da citação.
- **Reindexação por troca de modelo de embedding continua em aberto**, como na 0014.
- **Retenção veio na ADR 0017.** A conexão sai junto com o projeto, por CASCADE, no expurgo
  por organização.

## Alternativas consideradas

**Service account com pasta compartilhada.** Sem fluxo OAuth e sem segredo reversível em
repouso — teria evitado a decisão mais cara desta ADR. Custa exigir uma ação manual do cliente
para cada projeto e não funciona fora do Workspace.

**Push notifications do Drive.** Quase tempo real, em vez de um intervalo. Exige URL pública
com TLS, renovação do canal a cada ~7 dias e uma rota nova sem principal. Muita superfície para
trocar minutos por segundos num portal de acompanhamento de projeto.

**Sem recursão, só a pasta raiz.** Tornaria "apenas a pasta autorizada" literal e trivial de
provar. Custa exigir que o cliente reorganize o Drive dele numa pasta plana — e um Drive real
já vem organizado em subpastas. A recursão com teto e conjunto de visitados dá o mesmo controle
com uma travessia a mais.

**Guardar também o access token.** Pouparia uma chamada por sync. Aumentaria a superfície em
repouso para economizar um round-trip a cada 15 minutos.

**Seguir atalhos.** É o que o usuário esperaria ao ver o atalho na pasta. Também é o buraco
mais fácil de deixar aberto: um atalho é um ponteiro para fora da fronteira com aparência de
conteúdo dentro dela.
