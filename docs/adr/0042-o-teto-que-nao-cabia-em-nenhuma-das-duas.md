# ADR 0042 — O teto que não cabia em nenhuma das duas

**Status:** aceito
**Data:** 07/08/2026
**Fase:** 7 — primitiva compartilhada, pré-requisito da FDD 021 e da FDD 022

## Contexto

Duas features abertas pedem a mesma coisa pelo nome, e nenhuma das duas pode hospedá-la.

A FDD 021 (canal de WhatsApp) fecha com:

> **Teto de frequência por pessoa**, compartilhado com os demais avisos e com a pesquisa da
> FDD 022. Um canal de abertura quase total é o mais fácil de queimar: cada contato entrega
> algo — informação, valor, solução — ou não acontece.

A FDD 022 (pesquisa de satisfação) escreve a mesma frase do outro lado, com a razão dela:

> Gatilho por evento vira spam se todo micro-evento pedir nota, e pesquisa demais derruba a
> taxa de resposta até sobrar só quem estava com raiva o bastante para clicar — o pior viés
> possível.

O combinado era entregar o teto **junto da FDD 022**. Ele não sobrevive ao calendário: a
FDD 022 está bloqueada por uma condição que não é código — o laço de ação do funil precisa
estar fechado, com o time respondendo a alerta de cliente travado —, e a FDD 021 não tem
bloqueio nenhum. Manter o combinado deixaria dois desfechos, os dois ruins: o canal sai **sem
teto**, no exato canal que a FDD descreve como o mais fácil de queimar; ou o canal fica
bloqueado atrás de uma condição que não é dele.

Há um terceiro caminho que parece o barato e é o caro: pôr o teto dentro da FDD 021 e deixar
a FDD 022 reusar. Um teto que mora dentro de um consumidor não é compartilhado — é o teto
daquele consumidor com um nome maior, e nasceria com a forma de "aviso" (chave estável do
`diff` do sync) enquanto a pesquisa dispara por **evento de jornada**, que é outra coisa.

## Decisão

**O teto é fatia própria, e sai antes dos dois consumidores.** Escritor primeiro, leitor
depois — a disciplina que a ADR 0033 deixou de herança e que a ADR 0039 já aplicou ao funil.

### O orçamento é da pessoa, e é um só

Não há teto por canal somando-se a outro. Quem recebeu três mensagens recebeu três mensagens,
e de qual cota elas saíram é problema do portal, não dele. Dois números em `config.py`
(`contact_window_days`, `contact_cap_per_window`) e nenhum mapa por canal.

### Razão, e não contador — contra o precedente mais próximo

O `chat_rate_window` (ADR 0021) é um contador de três colunas, e esta tabela não o copia. O
argumento está no docstring daquele módulo: sob concorrência um contador **subconta**, o que
"seria inaceitável para um contador de faturamento". No chat subcontar deixa passar uma
pergunta a mais num limite de abuso. Aqui deixa passar **uma mensagem a mais para uma
pessoa**, que é exatamente o dano que o teto existe para impedir. É a escolha que a ADR 0022
já tinha feito para a conta de IA: um `INSERT` por evento não disputa, e a soma é um `COUNT`.

O preço é declarado e pago. A razão guarda comportamento de pessoa identificada — a classe de
dado que a FDD 020 tratou como a mais sensível do portal —, então a tabela carrega
`organization_id`, tem policy na mesma migração, é podada por idade e é alcançada pelo
apagamento por decisão. Um contador escaparia dessas quatro obrigações por não guardar
histórico nenhum, e é essa a troca.

### A chave de dedupe não é enfeite: é o que impede o silêncio permanente

`claim()` recebe um `dedupe_key` que identifica **o contato**, não a pessoa. Sem ele, a task
de envio — que retenta sobre `whatsapp_sent_at IS NULL`, na forma do digest — encontraria na
segunda passagem o orçamento gasto **por ela mesma** na primeira, e o aviso sumiria do canal
para sempre. Uma indisponibilidade de minutos do fornecedor viraria um silêncio definitivo, e
ninguém veria: o aviso continua no sino, e o que faltou não deixa rastro.

É a mesma memória que a ADR 0040 reusou para não criar tabela de estado de alerta — o
`dedupe_key` que a ADR 0012 já desenhou estável entre passagens do sync.

### A policy nega, e nega por escrito

Não há leitor. Não existe tela de histórico de contato, e o que a FDD 021 mostra em `/admin` é
o estado da *integração*, não o da pessoa.

As tabelas anteriores sem leitor de requisição — `agent_api_key`, `project_drive_connection`,
`onboarding_step` — resolveram isso **omitindo** a policy `TO portal_app`: nenhuma regra se
aplica ao papel, e a leitura devolve zero linhas. Aqui a omissão não estava disponível, porque
o meta-teste de `test_rls_isolation.py` exige ao menos uma policy de toda tabela com
`organization_id`. A saída fácil seria conceder um `SELECT` ao `portal_admin` "para a tela que
virá" — e é precisamente o defeito da ADR 0033 escrito ao contrário: campo publicado sem
consumidor.

Então a regra existe e diz não: `FOR ALL TO portal_app, portal_admin USING (false)`. No dia em
que a FDD 022 precisar ler, ela é substituída por uma escopada, e a substituição aparece no
diff em vez de uma linha nova surgir do nada.

### Nada é engolido em silêncio

Ao contrário de `onboarding.stamp`, que declara o silêncio porque medir engajamento não pode
derrubar o que o cliente veio fazer. Lá o carimbo é efeito colateral de outra coisa; aqui o
chamador **é** o remetente, e uma exceção que sobe simplesmente não envia. O desfecho seguro
já é o automático, então não há o que engolir — e o aviso continua no sino de qualquer forma,
que é a premissa em que a FDD 021 apoia o canal inteiro.

### `ContactKind` nasce com uma espécie só

`survey_invite` **não** entra agora, pela regra que a ADR 0039 aplicou a `artifact_accepted` e
a ADR 0041 honrou: só entra espécie que tem produtor. A FDD 022 não envia convite nenhum
ainda.

## Consequências

**O que esta fatia mediu e a FDD 022 não sabia.** O teto global **não** satisfaz sozinho o
critério de aceite (2) daquela FDD — *"um segundo evento na mesma semana não gera segundo
convite"*. Aquilo é uma afirmação sobre **aquela espécie**, não sobre o volume total: com um
orçamento de três por semana e nenhum outro contato, dois convites de pesquisa passam. Falta
um intervalo mínimo por espécie, e ele entra junto de `survey_invite`. Fica registrado na
emenda da FDD 022 em vez de virar dívida que alguém redescobre implementando.

**A poda usa a janela da notificação**, e não uma própria. O contato e o aviso são o mesmo
fato visto de dois lados; dois relógios sobre um fato só divergem no primeiro que alguém
editar, e o modo de falha seria o registro de que falamos com a pessoa sobrevivendo ao aviso
que o originou. A janela do teto (`contact_window_days`, uma semana) é outra coisa: ela decide
por quanto tempo a linha **conta**, não por quanto tempo ela existe.

**A terceira exclusão escrita à mão em `run_erasure`.** A regra que a ADR 0039 deixou escrita
— *"toda tabela nova com `organization_id` e sem `project_id` precisa de uma linha aqui"* —
foi cumprida sem susto desta vez, porque já existia quando a tabela nasceu.

**O valor padrão do teto não tem medição por trás**, e por isso é setting e não constante de
módulo — ao contrário do `INSTRUMENTED_SINCE` do funil, que é fato sobre o código. Três por
semana é um palpite informado; a primeira medição virá do próprio `contact.suppressed`. Errar
para baixo atrasa um aviso que continua no sino; errar para cima queima o canal, e canal
queimado não se recupera baixando o teto depois.

**Fica aberto, e nomeado:** teto de **horário** (não mandar às 3 da manhã). A FDD 021 não o
pede e a RFC 0004 do Biahflow pede o equivalente para cobrança; é decisão do remetente, não do
orçamento, e entra com o canal.
