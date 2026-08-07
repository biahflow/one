# RFC 002 — Canal de WhatsApp

**Status:** proposta — 07/08/2026. Nada aqui está implementado. RFC **obrigatória** pelo
gatilho de **conector externo** do `docs/rfc/README.md`.

## Contexto

O canal de menor atrito vence sempre. No Brasil, o WhatsApp tem abertura quase total e
resposta imediata; o portal exige lembrar que existe e entrar. Se os dois disputarem o mesmo
trabalho — "onde a gente acompanha o projeto" —, o WhatsApp ganha e o portal esvazia. Seria
investir num eixo para depois drená-lo com as próprias mãos.

A conclusão, porém, não é evitar o WhatsApp: é **não usar a primitiva errada**. A razão de
existir de um grupo é conversa de muitos para muitos. Se justamente a conversa é o que não se
quer que more lá, o grupo não serve. O trabalho real é outro: **um aviso importante chegar à
pessoa certa e puxá-la ao portal** — coisa que o e-mail faz mal.

Este repositório já tem tudo de que esse trabalho precisa, menos o canal. A produção de aviso
existe e é disciplinada: o sync fotografa o read model antes de escrever, compara, e cria uma
notificação por destinatário com chave de deduplicação (ADR 0012). A preferência por pessoa
existe (`notify_by_email`), com `UPDATE` escopado por coluna. A identidade existe. O destino
do link existe, com conteúdo que vale a abertura — jornada, aprovações, ROI apurado,
documentos, busca, assistente ancorado em citação.

Por isso o recorte aqui é estreito e o custo é baixo: **acrescentar um canal ao lado do sino
e do digest**, no ponto de extensão que a ADR 0012 já descreve.

## Proposta

**Canal novo, não pipeline novo.** Um tipo de notificação, um ramo no `diff` com chave de
deduplicação estável e uma entrada na audiência — exatamente o que a ADR 0012 estabeleceu
como o custo de acrescentar um aviso. O envio vai para a fila do worker, tolerante a broker
morto: a notificação já está gravada e aparece no portal de qualquer forma.

**Mensagem 1:1 por template, nunca grupo.** Sem Groups API e sem sala compartilhada onde a
conversa se acomode. Menos risco de ilha, porque não existe ilha.

**Opt-in e telefone como preferência da pessoa**, ao lado de `notify_by_email` e com o mesmo
`UPDATE` escopado por coluna — que é o que impede "mudar minha preferência" de virar
"reescrever o aviso" ou "promover-me a interno". Opt-in é **coluna, não configuração**.

**O aviso leva o mínimo e um link.** O que importa mora no portal; a mensagem diz que algo
aconteceu e leva até lá, caindo na coisa exata — a entrega a aprovar, não a home a três
cliques. Todo login é um imposto que o WhatsApp não cobra, e perder no último metro é perder.

**Entrada, se houver, é evento — não conversa.** Uma resposta do cliente no canal é
capturada como evento do projeto, para nada se perder, e a resposta substantiva volta pelo
portal. **Spoke, nunca hub.**

## Alternativas e trade-offs

**Grupo por projeto.** Rejeitada. É a primitiva errada pelo argumento acima, e o resultado
padrão — não o risco de cauda — é o portal esvaziar. O único caso em que faria sentido é se o
objetivo explícito fosse presença e relacionamento; aí exigiria trava estrutural (grupo
enquadrado como "avisos e link rápido" na criação, equipe treinada a responder "respondi no
portal", mensagens importantes capturadas como evento), e não força de vontade.

**Só e-mail.** É o estado atual. Funciona para o digest e falha para o urgente, porque a taxa
de abertura não sustenta o trabalho de "puxar de volta no momento certo".

**Provedor não oficial ou automação de conta pessoal.** Rejeitada: viola os termos da
plataforma, quebra sem aviso e coloca o canal do cliente numa base instável.

**Construir a régua de envio aqui.** Rejeitada: o `diff` do sync já decide o que merece
aviso. Um segundo lugar decidindo isso faria "o que o cliente é notificado sobre" deixar de
caber num arquivo.

## Segurança, privacidade e IA

**Opt-in registrado é pré-requisito, não refinamento.** Mensagem por template exige opt-in
pela política da plataforma, e a LGPD exige base legal e revogação. Isso é **modelagem**:
coluna de consentimento, instante e origem, com revogação que tem efeito imediato e sem
apelação. Revogado é revogado, inclusive para avisos já enfileirados.

**Retenção.** O registro de envio e o telefone entram na `data-classification.md` e são
alcançados pela política por organização e pelo apagamento por decisão (ADR 0017).

**Webhook de entrada assinado e idempotente**, no precedente da rota autenticada por chave
da ADR 0013: verificação antes de qualquer efeito, reentrega do mesmo evento é no-op, e toda
recusa de credencial é o mesmo erro opaco com a razão no log.

**O conteúdo do aviso não pode conter o que a citação protege.** Vai o fato e o link, nunca
o trecho do documento — o canal não tem as garantias que o portal tem. E **nenhum dado
comercial**: a fronteira que o snapshot respeita vale aqui inteira.

**Nada de IA neste recorte.** O texto do aviso é template. Um modelo redigindo mensagem que
sai por um canal externo, sem revisão, é efeito colateral autônomo — exatamente o que a
arquitetura de agentes proíbe.

## Plano de testes e rollout

1. **Atrás de flag**, com o preflight de homologação cobrindo a credencial nova e os dois
   portões independentes contra o segredo de exemplo (ADR 0022) valendo para ela.
2. **Teste do opt-in como portão**: sem consentimento não há envio, por nenhum caminho; a
   revogação cancela o que está enfileirado.
3. **Teste de idempotência** do webhook de entrada e da deduplicação de saída — reentrega não
   duplica mensagem.
4. **Teste de que o conteúdo não vaza**: nenhum trecho de documento, nenhum dado comercial e
   nenhum identificador de outro tenant na mensagem.
5. **Teste de isolamento**: o aviso alcança exatamente os destinatários que a audiência
   define, e ninguém mais.

**Teto de frequência por pessoa**, compartilhado com os demais avisos e com a pesquisa de
satisfação (FDD 022). Um canal com abertura quase total é também o mais fácil de queimar: o
cliente bem servido é o que sente que só é incomodado quando importa. Cada contato entrega
algo — informação, valor, solução — ou não acontece.
