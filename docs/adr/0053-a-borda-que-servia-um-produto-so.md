# ADR 0053 — A borda que passou a servir um produto só

**Status:** aceito
**Data:** 13/08/2026
**Substitui:** ADR 0048 (a barreira que o navegador não atravessa), na parte em que ela
põe o balanceador global da GCP no caminho do SPA
**Relacionadas:** ADR 0046 (o Terraform de HML), ADR 0048 (a borda), ADR 0051 (três
states, um por dono)

## Contexto

O portal do cliente saiu do ar por decisão de produto: a jornada do cliente passa a ser
conduzida no WhatsApp, e o portal volta quando houver quem o opere. Isso não é uma
decisão de arquitetura, é o fato de onde esta decisão parte.

O que ele levou junto foi a metade da borda. A ADR 0048 escolheu um balanceador global
da GCP e justificou o custo com uma conta específica:

> "A alternativa seria uma borda por produto, e o preço estaria em três lugares:
> dobraria as regras de encaminhamento (o único custo fixo de HML), exigiria um segundo
> IP global e, como o nome `nip.io` contém o IP, **mudaria os hostnames de um dos
> dois**."

Os três termos dessa conta eram sobre **dois** produtos. Com um só, ela não sobrevive:
não há o que dobrar, não há segundo IP a evitar, e não há um segundo conjunto de
hostnames para não quebrar. O que sobrou foi um balanceador global servindo uma
aplicação, a um preço que não caiu junto com o uso:

| Item | Custo parado |
|---|---|
| 2 regras de encaminhamento globais | ~US$ 18/mês (US$ 0,025/h para as cinco primeiras, somadas) |
| IP global reservado | ~US$ 7/mês — e **fora de uso a tarifa é o dobro** da de "em uso" |
| NEG, backend service, url map, proxies, certificado | zero |

O interruptor `var.borda_ligada`, aplicado horas antes desta decisão, já tinha derrubado
o primeiro item. Ele resolvia o custo por hora e não o resto: o IP continuava reservado
justamente porque os hostnames `nip.io` o contêm, e liberá-lo forçaria reemissão de
certificado a cada religada. A própria variável dizia onde essa amarra se desfaz — "isso
só deixa de valer quando `var.dominio` estiver preenchida".

E havia uma segunda borda no ambiente o tempo todo. O site de marketing (`biahflow-site`)
já é servido pela Cloudflare, que já é autoridade de `biahflow.ai` e já termina TLS para
a zona. Manter duas bordas para um produto cada é o desperdício que a ADR 0048 procurava
evitar quando escolheu uma para dois.

## Decisão

### A borda do CRM passa a ser a Cloudflare

Um registro DNS `app.biahflow.ai` proxied apontando para a `run.app` da `biahflow-web`,
mais uma Origin Rule que reescreve o `Host`. O balanceador global da GCP — NEG, backend
service, certificado gerenciado, url maps, proxies e regras de encaminhamento — é
apagado, e o IP global `hml-entrada` é liberado.

A regra de `Host` não é detalhe: a Cloudflare repassa o `Host` original, e o Cloud Run
roteia por `Host`. Sem reescrever, todo request morre em 404 do Google — sem log nosso, e
com um sintoma que não fala de header. Override de `Host` em Origin Rules existe no plano
gratuito.

`var.dominio` deixa de ser opcional. O fallback `nip.io` existia para dar nome estável ao
`issuer` do Keycloak antes de haver domínio; o Keycloak saiu com o portal, e o IP sobre o
qual o fallback era montado deixou de existir. Um default que constrói hostname a partir
de um recurso destruído produz erro pior do que exigir o valor.

### O SPA volta a falar com a API por dentro

A ADR 0048 tirou o `proxy_pass` do nginx do caminho e entregou `/api|/admin|/static` da
borda direto à `biahflow-api`. Sem borda, o caminho volta a ser
`Cloudflare → biahflow-web → nginx → biahflow-api`.

Isto custou zero linhas de aplicação, e é o ponto: o `nginx.conf.template` do SPA nunca
perdeu aqueles `location`, e o Terraform nunca deixou de injetar `API_UPSTREAM` e
`DNS_RESOLVER`. A ADR 0048 registrou por escrito que eles ficariam — "elas saem no mesmo
commit em que `biahflow-portal` apagar aqueles dois `location`" —, e a razão dada na
época (um `proxy_pass` errado deve falhar dizendo o nome certo) acabou pagando um retorno
que ninguém previu.

### Um quarto valor de `acesso`: `interno-sem-iam`

A `biahflow-api` era `balanceador`, que é `INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER`:
aceita tráfego da VPC **e** do balanceador. Sem balanceador, o segundo termo é uma porta
aberta para ninguém. Passa a ser `INGRESS_TRAFFIC_INTERNAL_ONLY` — um aperto, não um
risco, porque o primeiro é superconjunto do segundo e todo o tráfego real vem da VPC.

Não é o `interno` que já existia, e a diferença é a que a ADR 0046 deixou aberta e a 0048
nomeou: `interno` amarra IAM, e **nenhum dos dois chamadores sabe assinar**. O nginx não
emite ID token. O relay do site de marketing autentica por `X-Intake-Token`
(`backend/server.py` daquele repo), não por IAM. Sob `interno`, os dois tomariam 403 — e
o 403 do Cloud Run não aparece em log nosso.

`balanceador` fica no módulo, órfão. Removê-lo esconderia que existiu, e é justamente a
diferença entre ele e `interno-sem-iam` que explica por que a troca foi segura.

### `deletion_protection` deixa de ser efeito colateral

Descoberto ao desmontar o portal: o provider 6.x liga a trava por default nos três
recursos do Cloud Run, então tudo nasceu protegido sem que arquivo nenhum dissesse isso.
O `destroy` reprovou três vezes, uma por tipo de recurso, cada uma depois de já ter
derrubado o que não era protegido. Agora é `var.protegido`, default `true`.

## Consequências

**Some o log de borda.** O `backend_service` tinha `log_config` com `sample_rate = 1.0` —
uma linha por requisição, que era a única prova de "chegou na borda" num 502 ou num
timeout, exatamente o caso em que a aplicação não tem log nenhum. A Cloudflare no plano
gratuito dá analytics agregado, não log por requisição. Quem depurar um 502 daqui em
diante começa pelo log do Cloud Run.

**O Access protege o nome, não o serviço.** A `biahflow-web` continua `publico`, e precisa
ser: quem a alcança é a Cloudflare, que chega pela internet como qualquer outro cliente.
Então a `run.app` dela segue aberta, e quem a descobrir passa ao largo do Access — a
barreira que vale nesse caminho é o login do próprio Django. Fechar isso exigiria mTLS ou
um túnel, e nenhum dos dois se paga em homologação.

**`NUM_PROXIES` ficou mais errado, e de propósito.** A cadeia passou de
cliente → balanceador → Cloud Run para cliente → Cloudflare → Cloud Run → Cloud Run.
O valor `2` já era raciocínio e não medição (ADR 0050); trocá-lo por outro palpite não
melhora nada. Medir está no runbook e fica aberto.

**A borda mudou de fatura, não de dono.** Ela continua na fundação, e pela mesma razão de
antes: quem derivasse o próprio hostname precisaria da zona, e a zona não é de produto
nenhum. O que mudou é que agora ela também precisa de `CLOUDFLARE_API_TOKEN` no ambiente
de quem aplica — o `infra-hml.yml` não o tem, então o apply da fundação passou a ser um
ato local até alguém cadastrar o secret.
