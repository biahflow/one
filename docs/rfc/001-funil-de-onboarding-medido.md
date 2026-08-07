# RFC 001 — Funil de onboarding medido

**Status:** **parcialmente implementada** — 07/08/2026. Passos 1, 2 e 3 do plano de rollout de
pé (ADR 0039, ADR 0040); o passo 4, a vigília da IA, segue aberto pela condição que ele mesmo
declara. O recorte construível é a **FDD 020**, que é quem carrega o estado item a item.

*Corrigido em 07/08/2026 (ADR 0041): esta linha dizia `**Status:** proposta — 07/08/2026.
Nada aqui está implementado.` e passou o dia inteiro sendo falsa — o funil foi carimbado pela
manhã (ADR 0039) e ganhou leitor e alerta à tarde (ADR 0040). É pequena e é exatamente a
espécie de frase que este repositório passou nove ADRs consertando: um documento afirmando um
estado que já mudou. Fica registrada em vez de apagada, pelo motivo de sempre.*

## Contexto

Hoje o produto sabe se um projeto está **no prazo**. Não sabe se o cliente está
**engajando**. São coisas diferentes, e a diferença é onde o churn silencioso mora: um
projeto verde, com entregas em dia e health saudável, cujo cliente parou de logar há três
semanas. Ninguém descobre isso até ele reclamar ou sumir.

A cegueira é estrutural, não acidental. Todo o instrumental existente — health score, ROI
apurado, risco de atraso — mede **a execução do projeto**. Nada mede a relação do cliente com
o produto. Grep por `funil`, `onboarding`, `engajamento` ou `time-to-value` nos documentos
deste repositório devolve zero.

O barato disso é que **os eventos já acontecem**; falta carimbá-los. Primeiro login,
primeira pendência respondida, primeira conversa com o assistente, primeiro documento
aberto, primeiro ROI visto — todos existem como estado no read model ou no `audit_log`. Do
lado do Biahflow, artefato saindo de `sent` para `accepted` e entregável saindo de
`pending` são os degraus que nascem lá. O funil não é uma tela: é uma sequência de estados
que já ocorre e que ninguém registra **quando** ocorreu.

Esta RFC existe porque o assunto **atravessa os dois repositórios** e define um contrato
entre eles. Vale registrar honestamente que ele **não** aciona nenhum dos gatilhos listados
no `docs/rfc/README.md` — não é conector externo, papel novo, mudança de retenção, ferramenta
de IA com efeito externo nem alteração incompatível de contrato. É RFC pela travessia, e por
introduzir uma classe de dado pessoal que não existia: comportamento de pessoa identificada.

## Proposta

**Degraus de valor com carimbo de tempo, por cliente.** Cada degrau é um estado que já
ocorre; o que se acrescenta é a data em que ocorreu pela primeira vez, por organização e por
pessoa quando fizer sentido. A régua que importa não é a taxa de conversão agregada, é o
**time-to-first-value**: quanto o cliente demora do ganho até a primeira aprovação e até o
primeiro ROI visto. Esse número prediz retenção melhor que qualquer health score de projeto.

**Degraus deste repositório:** convite aceito e primeiro login (`user.external_subject`
deixando de ser nulo), primeiro documento aberto, primeira pendência respondida, primeira
conversa com o assistente, primeiro ROI visto.

**Degraus do Biahflow:** artefato aceito (`sent → accepted`) e primeiro entregável saindo de
`pending`. *Os dois estão de pé desde 07/08/2026 — o entregável na ADR 0039, o artefato na ADR
0041, este último depois de a FDD 031 do Biahflow pôr a data no snapshot, porque ela não
estava lá.* Eles chegam pelo sync que já existe, e é aqui que a invariante da ADR 0006/0008
tem de valer sem exceção: **o portal não origina status**. O funil observa e carimba; não
inventa progresso que o Biahflow não afirmou.

**O valor não está no gráfico — está no alerta por cliente travado.** "Cliente ganho há nove
dias, convite enviado, nunca logou" é um sinal que hoje é invisível e que, aos nove dias,
ainda se resolve com um telefonema. Aos trinta, virou churn.

**Duas travas que decidem se o funil serve ou engana:**

**Instrumentar degraus de valor, não vaidade.** "Logou doze vezes" não é sinal de nada — pode
ser um cliente perdido procurando o que deveria estar óbvio. O degrau tem de ser um momento
em que o cliente **recebeu** algo (aprovou, viu ROI, baixou o entregável), nunca um em que
ele se esforçou. Instrumentar esforço é otimizar engajamento e medir ansiedade.

**Separar "travou no cliente" de "travou em nós".** Se o degrau não avança porque a entrega
não saiu, o alerta é sobre a equipe, não sobre o cliente. Os dois sinais são úteis e não
podem ser confundidos na hora de priorizar — e a arquitetura ajuda, porque "quem origina o
status" já é uma fronteira explícita aqui.

**Onde a IA entra, e só aí.** Ela **vigia o funil e escreve o sinal; não conversa**. Varre
quem empacou, prioriza por gravidade e entrega ao time em linguagem de ação: travou no degrau
tal, há tantos dias, provável causa, sugestão. É a mecânica de recomendação revisável que o
PRD do Biahflow já descreve para risco de projeto, apontada para engajamento do cliente — o
humano lê e age. **Nenhum bot voltado ao cliente**: o assistente deste repositório responde
ancorado em evidência com citação, e vira bot de CS no instante em que passa a deflectir
atendimento.

## Alternativas e trade-offs

**Ferramenta de analytics de produto de terceiro.** Rejeitada: manda comportamento de pessoa
identificada de cliente para fora, o que a `data-classification.md` não permite tratar de
leve, e reintroduz uma fonte de verdade paralela ao read model.

**Derivar tudo na leitura, a partir do `audit_log`.** Tentador porque não acrescenta tabela.
Frágil porque o log é operacional: seu formato muda por razões de operação, ele é purgado por
idade, e nem todo degrau deixa rastro lá. Um funil que se reescreve quando o log rotaciona
não é medição.

**Medir só a conversão agregada, sem alerta por cliente.** É a versão que vira slide e não
muda nada. O princípio que rege este documento é **medir para agir, não para reportar** — se
a medição não dispara ação, ela não entra.

**Carimbar tudo, inclusive vaidade, e decidir depois o que importa.** Rejeitada: dado de
comportamento é o que mais custa guardar em risco e o que menos custa recoletar depois de uma
decisão consciente.

## Segurança, privacidade e IA

**Comportamento de pessoa identificada é dado sensível.** Entra na
`data-classification.md` com classe própria, respeita a política de retenção por organização
e é alcançado pela purga por idade e pelo apagamento por decisão (ADR 0017). Um funil que
sobrevive ao apagamento do tenant seria o mesmo defeito que aquela ADR fechou.

**Toda tabela nova com `organization_id` nasce com policy na mesma migração** — o meta-teste
de isolamento reprova o CI se não. O funil não é exceção, e o degrau que carrega `user_id`
segue a forma de `notification`, cuja linha pertence a uma pessoa e cujas policies somam o
predicado do usuário ao do tenant.

**Escrita é do produtor, não do cliente.** O carimbo nasce do sync ou de um observador do
lado do servidor, sob a credencial de sistema — o papel de aplicação não ganha `INSERT` sobre
o funil. Um caminho de requisição capaz de escrever o próprio degrau é um caminho capaz de
falsear o próprio engajamento.

**A IA não recebe o corpus, recebe o agregado.** Ela lê quem travou em qual degrau e há
quanto tempo, não o conteúdo das conversas nem dos documentos daquele cliente. Herda o
registro de prompt versionado, as avaliações adversariais e a quota por organização já
existentes. E o sinal que ela escreve é **para o time**, nunca para o cliente.

## Plano de testes e rollout

1. **Carimbar sem expor.** Primeiro os degraus e as datas, sem tela e sem alerta — inclusive
   para acumular dado antes de qualquer painel. Este repositório já tem a cicatriz do painel
   publicado sobre um campo que nunca teve escritor; a ordem aqui é deliberada.
2. **Teste de isolamento** entre organizações no funil, junto do meta-teste que já existe, e
   teste de que a purga e o apagamento alcançam os degraus.
3. **Alerta de cliente travado**, com o time agindo de fato — e só então a leitura agregada.
4. **A IA por último**, quando houver histórico suficiente para o sinal ser priorizável.

**Um sinal de cada vez.** O gargalo não é construir sinal, é a capacidade do time de
responder a ele; três radares tocando para um time que não dá conta de agir em um é pior que
um radar que ele respeita. Este é o primeiro — a pesquisa de satisfação (FDD 022) só começa
depois que este laço estiver fechado de verdade.

**E o pré-requisito que nenhum radar substitui:** sinal traz o cliente de volta, valor o
retém. Se ao voltar não houver algo que importa — uma aprovação, um ROI visível, uma decisão
registrada —, nenhum alerta salva. Os dois investimentos andam juntos.
