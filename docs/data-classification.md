# Classificação de dados

- **Público:** material comercial aprovado.
- **Interno:** cronograma, status e documentação de operação.
- **Confidencial do cliente:** transcrições, documentos, eventos e indicadores por projeto.
- **Segredo:** chaves, tokens, credenciais e material criptográfico.
- **Comportamento de pessoa identificada:** *quando* uma pessoa nomeada alcançou cada degrau de
  valor no portal (ADR 0039). Classe própria, e não "confidencial do cliente", porque o risco é de
  outra natureza: as demais descrevem o **projeto**, e esta descreve a **pessoa**. É por isso que
  ela não é exposta a nenhuma rota de cliente, que o papel de requisição não tem policy sobre ela,
  e que o log carrega só o tenant e o nome do degrau — nunca o `user_id`, que fica na linha, onde a
  retenção e o apagamento o alcançam. *Desde a ADR 0040 ela sai do banco por duas portas — a rota
  `GET /api/v1/admin/organizations/{id}/onboarding`, restrita a `internal_admin` e negando com 404,
  e a linha de notificação cuja audiência é `_INTERNAL_ONLY` —, e **nenhuma das duas carrega
  pessoa**: o que trafega é o degrau, uma contagem de dias e de que lado está a espera. Quem
  alcançou o degrau continua sendo pergunta que só a linha responde.* *(E desde a ADR 0041 um dos
  sete degraus **atravessa a fronteira entre os dois sistemas**: `artifact_accepted_at` sai do
  Biahflow no snapshot. O que cruza é o instante da primeira aprovação daquele **cliente** — não
  `kind`, não `title`, não `content`, não valor, não pessoa —, e a linha "nenhum dado comercial é
  exposto" do `portal.py` de lá foi qualificada em emenda na ADR 0003 daquele repositório em vez de
  contornada: nenhuma das três coisas que ela nomeia (Opportunity, PipelineStage, valores) sai. O
  carimbo deste lado herda o `user_id` nulo do degrau do entregável, porque o fato é do outro
  sistema e não há pessoa daqui a nomear.)* *(E desde a ADR 0042 esta classe tem um **segundo**
  membro, que é a mesma pergunta pelo avesso: o funil registra o que a pessoa fez, e o
  `contact_event` registra o que **nós fizemos com ela** — com quem falamos, por qual canal e
  quando. Os controles são os mesmos por serem o mesmo risco: nenhuma rota de cliente, nenhuma
  leitura pelo papel de requisição — aqui por uma policy que diz `USING (false)`, e não pela
  omissão das outras —, e o log com o tenant, a espécie e o motivo, nunca a pessoa.)*

A fronteira entre essas classes e a tela do cliente deixou de ser convenção na ADR 0082: o que
o One expõe é **lista positiva**, campo a campo, em [`docs/contracts/one-visibility.json`](contracts/one-visibility.json),
com a razão escrita de cada campo — e a regra é a **negação por omissão**, de modo que campo que
ninguém classificou não sai. Ela é o par das nove proibições da §3 do
[Language Map](ontology/language-map.md): `Lead`, `Qualification` e seu resultado,
`CommercialOpportunity`/`PipelineStage`/valor/probabilidade, Evidence não revisada e transcrição
bruta, `PriorityAssessment.rationale`, preço de tabela/margem/`Service.price`, Case de outros
clientes, dado de outra Account, e nada com `epistemic_status=hypothesis` como fato. *Duas
qualificações que a medição impôs: a proibição é por **recurso** e por **par explícito**, nunca
por palavra — `DecisionOut.rationale` é o racional da decisão publicada e é legítimo, enquanto o
do `PriorityAssessment` é avaliação interna e não sai; e `MeetingOut.has_transcript` é o booleano
que diz que a transcrição existe **sem** expô-la, que é o oposto de vazá-la. E o critério "dado de
outra Account" não ganhou guarda nova: ele já tinha duas — `test_authorization.py`, derivada do
contrato publicado, e `test_rls_isolation.py` —, e o que entrou foi só a metade que um contrato
consegue afirmar, que nenhuma rota de cliente aceita o cliente **nomear** uma Account.*

Desde a ADR 0016 há um segredo **em repouso no banco**: o refresh token do Google Drive, um por projeto. Ele é cifrado com AES-256-GCM sob uma chave que vive só no ambiente — nunca no banco que ela protege — e amarrado à organização e ao projeto pelo dado associado, de modo que um ciphertext movido de linha não abre. É o único segredo do portal que precisa voltar em claro; todos os outros são verificados por hash e nunca recuperados.

Dados confidenciais e segredos não entram em logs. Conteúdo enviado ao provedor de IA segue a política contratada de não treinamento/retenção e deve ser removível por organização. *(A remoção existe desde a ADR 0017:
prazo por organização com poda diária, e apagamento por pedido gravado que o worker cumpre —
inclusive os objetos do storage, pelo prefixo `org/<id>/`. O documento nunca sai por idade: é a
evidência que sustenta uma citação já dada.)* *(E desde a ADR 0039 o funil tem prazo próprio,
mais longo que os outros — a régua só significa algo comparada com a de coortes anteriores — e é a
segunda exclusão escrita à mão no apagamento por decisão: escopado por organização, ele não vem no
CASCADE do projeto.)* *(O `contact_event` é a **terceira**, pela mesma regra e sem susto — ela já
existia escrita quando a tabela nasceu. A poda dele, ao contrário, **não** ganhou prazo próprio: usa
o da notificação, porque o contato e o aviso são o mesmo fato visto de dois lados e dois relógios
sobre um fato só divergem no primeiro que alguém editar. ADR 0042.)*
