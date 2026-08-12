# ADR 0048 — A barreira que o navegador não atravessa

**Status:** aceito
**Data:** 12/08/2026
**Fecha:** os três "fica aberto" da ADR 0046 e o da ADR 0044
**Relacionadas:** ADR 0019 (backup e restore), ADR 0044 (bootstrap em Postgres gerenciado),
ADR 0045 (worker no Cloud Run), ADR 0046 (o Terraform de HML)

## Contexto

A ADR 0046 subiu a HML na GCP como código e deixou três coisas escritas como abertas, mais uma
herdada da ADR 0044. Nenhuma era do tipo "falta rodar" — eram quatro lacunas sem dono, e três
delas o repositório já cobrava por escrito, em **quatro arquivos que citavam um runbook que não
existia**.

Ao construí-las, apareceram três defeitos que ninguém tinha olhado, e os três são da mesma
família: um controle que parece estar de pé e não está.

**1. A chamada `portal-api → biahflow-api` está quebrada em HML, e nada denuncia.** O defeito 9
da ADR 0046 — "a segunda barreira não era atravessada por ninguém" — foi consertado só do lado
TypeScript. `app/lib/serviceIdentity.ts` cunha o ID token que o BFF apresenta em
`X-Serverless-Authorization`, e **não há equivalente em Python**: `integrations/biahflow.py:114`
manda `Authorization: Bearer <BIAHFLOW_READ_TOKEN>`, que é segredo de aplicação e não diz nada ao
provedor. Com ingress interno mais IAM invoker, aquela chamada leva **403 do Cloud Run antes da
aplicação** — e um 403 do Cloud Run não aparece em log nosso, então a depuração começaria no
Django, que nunca foi chamado. O sync do Biahflow morreria em silêncio.

**2. `https://app.<base>/healthz/` devolve o SPA com 200.** O bloco próprio das sondas no
`nginx.conf.template` existe com a justificativa escrita: sem ele a sonda cai no `try_files` e
recebe o `index.html`, e "um balanceador leria saudável com a API fora do ar". Mas a regex é
`^/(healthz|readyz)$` e **não casa a barra final**, enquanto o `HealthProbeMiddleware` do Django
faz `request.path.rstrip("/")` e responde as duas formas — o comentário de lá antecipa o caso por
extenso. O defeito que o bloco existe para impedir sobrevivia por uma barra.

**3. Uma mudança de Terraform entrava num PR sem prova nenhuma.** O `ci.yml` não tocava Terraform,
e o `infra-hml.yml` — que roda `fmt`, `validate` e `plan` em PR — autentica por
`vars.WIF_PROVIDER`, que é criado **pelo próprio Terraform**. É o bloqueio de ação humana da ADR
0046 outra vez, um nível acima: enquanto ninguém aplica, ninguém consegue nem saber se o HCL
parseia.

## Decisão

### `acesso` tem três valores, e o terceiro não é uma barreira a mais

`variable "publico"` (bool) virou `variable "acesso"` (string, com `validation`): `publico`,
`interno`, `balanceador`. O ingress é escolhido por índice de mapa e não por ternário aninhado —
com três casos, o ternário é onde o quarto valor entra errado sem nada ficar vermelho.

**Sob `balanceador`, o IAM fica aberto de propósito, e isto é a parte que precisa estar escrita.**
Um NEG sem servidor **não cunha ID token**; exigir IAM ali seria exigir do balanceador uma
credencial que ele não tem, e o serviço responderia 403 a toda requisição legítima. A barreira é o
ingress: a `run.app` deixa de existir para a internet, e a borda passa a ser nossa.

Então o que esta fatia entrega são **ingress mais roteamento**, e não duas barreiras. A ADR 0046
já tinha escrito o argumento — *"para um serviço cujo cliente é o navegador, IAM invoker não é a
segunda barreira"* — e teria sido fácil contradizê-la aqui alegando duas, que é exatamente o
defeito que ela diagnosticou: um comentário afirmando duas barreiras onde havia uma. A segunda
barreira honesta seria Cloud Armor no `hml-biahflow-api`, e fica declarada como **não feita**.

**De carona, isso conserta o defeito 1** — sem IAM no caminho, `portal-api → biahflow-api` volta a
funcionar. O preço, declarado: aquele caminho passa a ser barrado só pelo `BIAHFLOW_READ_TOKEN`
que a aplicação já manda. Medido, é **mais** do que ele tinha, porque hoje ele não passa. E é por
isso que o equivalente Python do `serviceIdentity.ts` **não** foi escrito nesta fatia: com
`allUsers`, o ID token seria decoração. Se a `biahflow-api` voltar um dia a `interno`, aquele
caminho quebra de novo em silêncio — fica nomeado abaixo.

### O módulo da borda separa backends de rotas, e o certificado sai de rotas

`variable "servicos"` virou duas: `backends` (alimenta NEG e backend service) e `rotas` (alimenta
`host_rule`, `path_matcher` e os `path_rule`). A `biahflow-api` entra na primeira e **não** na
segunda: ela é destino de caminho, não dona de nome.

A separação não é arrumação — é o que protege o certificado. **`domains` sai de `rotas`, nunca de
`backends`**, e derivar de `backends` produziria um `null` (a `biahflow-api` não tem host) ou um
nome a mais; trocar a lista **recria o certificado**, derrubando o HTTPS dos três nomes por quinze
minutos a uma hora. A ordem também é identidade: o provider tipa `domains` como `list` e não como
`set` — conferido no `providers schema` antes de escrever a linha —, e `for` sobre map visita as
chaves em ordem lexicográfica, de modo que uma rota nova cuja chave ordene antes das existentes é
uma **reemissão**, não um acréscimo. Mantidas as chaves de hoje, a lista sai byte a byte igual e o
certificado não aparece no plano.

**Sem `distinct()`, e a recusa é a decisão.** Ele não mudaria nada hoje e *engoliria* uma
configuração que a API recusa de qualquer jeito: dois `host_rule` com o mesmo host dão `Host rule
has a duplicate host`. Com `distinct()`, o certificado sairia bem-formado e o erro apareceria
noutro recurso, falando de outra coisa. No lugar dele, duas `validation` — hosts únicos, e a
sintaxe dos `paths` que o próprio provider documenta.

**A cobertura da primeira foi medida, e é menor do que parece:** com `var.dominio` vazio, o host
deriva do IP de entrada, que é desconhecido antes de existir, e uma condição sobre valor
desconhecido não é avaliada — o `validate` do primeiro dia passa. Ela dispara com host conhecido,
que é todo plano posterior. Está escrito no módulo, porque a cobertura de um portão é a dos ramos
que a amostra percorre (ADR 0038), e alguém ia lê-la como se cobrisse o caso em que mais dói.

### Sete caminhos, e não os três que a ADR 0046 nomeou

`/api/*`, `/admin/*`, `/static/*`, `/healthz`, `/healthz/`, `/readyz`, `/readyz/`. Os dois pares
de sonda entram pelo argumento que o nginx já tinha escrito, e **com barra** pelo defeito 2. As
regras moram num local irmão, `rotas_internas`, fora de `servicos_http`: aquele mapa alimenta um
`for_each` que só o aceita porque os cinco valores têm atributos idênticos, e um campo presente em
um só quebra a unificação do tipo.

**Nenhuma linha do `biahflow-portal` muda.** O SPA pede `"/api/v1"` relativo e `VITE_API_URL` não
é build arg, então trocar quem responde àquele caminho é invisível ao navegador, sem rebuild.
`DJANGO_ALLOWED_HOSTS` já continha `app.<base>` — o Host que o balanceador preserva, porque um NEG
sem servidor não o reescreve, ao contrário do `proxy_set_header Host $proxy_host` do nginx.

**`API_UPSTREAM` e `DNS_RESOLVER` ficam**, sem cliente, e isso foi decidido contra o instinto. O
`Dockerfile` do SPA declara `API_UPSTREAM=http://api:8000` e `DNS_RESOLVER=127.0.0.11` como
default da imagem: removê-las do Terraform **não** faria o nginx falhar — faria com que, no dia em
que um `path_rule` estivesse errado, ele respondesse 502 dizendo que não conseguiu resolver
**`api`**, um nome de rede do Docker dentro do Cloud Run. Trocaríamos um caminho que funciona por
um diagnóstico que mente. Elas saem no commit em que o outro repositório apagar os dois `location`
que as lêem: configuração e leitor morrem juntos.

### O `restore.sh` sabe descrever um alvo gerenciado

A ADR 0044 deixou aberto que o restore num Postgres gerenciado nunca fora exercitado. O script
presumia o compose em quatro pontos, e o mais caro **não era** o que aquela ADR previa:

**No Neon a unidade não é o cluster, é o branch.** Os papéis pertencem ao branch. Isso corta nos
dois sentidos: `--database ensaio` no mesmo branch redefine as senhas em vigor exatamente como o
aviso do script descreve — "banco descartável" não protege nada ali —, e criar um branch é a saída
barata, porque ele nasce com os papéis copiados e é descartável de verdade. Não estava escrito em
lugar nenhum.

`RESTORE_ADMIN_URL` aceita a DSN administrativa inteira, porque montá-la trocando usuário e senha
sobre a URL do migrator não alcança um gerenciado: o papel de maior privilégio **e o endpoint**
mudam por branch. `POSTGRES_MAINTENANCE_DB` porque o banco de manutenção nem sempre se chama
`postgres`. Ambas com default que preserva o compose.

E uma **precondição nomeada** entre os passos 2 e 3: `pg_has_role(current_user, 'portal_migrator',
'MEMBER')`. O `pg_restore --clean` derruba objetos cujo dono é o migrator, e desde o PG 16
transferir posse exige ser membro do papel — o que hoje funciona só porque o `roles.sql` concede
essa associação no ramo de não-superusuário da ADR 0044. Era uma dependência de ordem que nenhum
comentário registrava, e cuja falha aparecia no meio do restore como erro de posse de um objeto,
longe da causa.

**De quebra, o `--help` truncava em silêncio.** Ele era `sed -n '2,26p'`, um intervalo escrito à
mão: crescer o cabeçalho cortava a ajuda sem avisar, e foi o que aconteceu ao documentar tudo
isto. Agora é derivado, e o caso de teste afirma sobre a **última** linha do cabeçalho — que é a
que se perde.

### O instrumento de comando/hora, e o que ele mostrou

A ADR 0045 fixou "comando/hora com a fila vazia, lido no painel do Upstash" como condição para HML
ser declarada pronta, e escreveu que era *"uma promessa a medir, não a acreditar"*. Um `grep` por
"comando/hora" achava quatro linhas, **todas em prosa**: não havia script, alerta nem recurso de
monitoramento.

`scripts/redis_rate.py` mede o **banco inteiro**, por `INFO stats`/`total_commands_processed`, e
não o nosso processo. É a única forma honesta: a conta do Upstash é por comando do banco, e o
banco tem mais produtores do que o worker do portal. Se o servidor recusar `INFO` — ele publica um
subconjunto de comandos —, o relatório declara a ausência e **não inventa um número**: `skipped`
não é `clean` (ADR 0017).

**E a aritmética da ADR 0045 estava incompleta.** Os ~17 mil comandos/dia supõem um comando por
ciclo por instância, e deixam de fora o gossip/mingle/heartbeat do Celery (que o worker não
desliga), o result backend — que é o mesmo Redis —, os tiques do beat com a fila vazia, e o
`biahflow-scheduler` do outro produto, que aponta para o mesmo Upstash sem nenhuma ADR ter
contabilizado os comandos dele. Medido contra o compose ocioso, o total saiu **da ordem de quinze
vezes** o previsto.

Aquele número é do ensaio e não vale para HML — ali há duas sondas de healthcheck que HML não tem
—, e o relatório nomeia as duas justamente para ninguém dividir por um fator qualquer e citar o
resultado como estimativa. É a regra do `loadtest.py`: um número sem a condição em que foi obtido
é pior que nenhum, porque alguém o cita depois.

### Um portão de Terraform sem credencial

`fmt -check`, `init -backend=false` e `validate` no `ci.yml`. O `-backend=false` instala os
providers sem tocar no bucket de estado, que é o que torna isto possível antes de existir
`WIF_PROVIDER`. O `infra-hml.yml` **fica** e não se sobrepõe: lá se planeja contra o projeto real,
aqui se prova que o HCL parseia e tipa — a mesma distinção que o `dependency-audit` e o
`dependency-review` têm entre si (ADR 0023).

## Consequências

- **O primeiro apply da borda tem uma janela de erro do Google.** Propagação de IAM leva até cerca
  de um minuto, e a de um balanceador global de segundos a alguns minutos: nesse intervalo
  `app.<base>/api/...` responde 403 ou 404 **sem nada no log do Django**. Está no
  `hml-gcp.md`, porque começar a depuração na aplicação aqui é repetir o defeito 9 da ADR 0046.
- **O apply vai em dois**, `-target=module.servicos` primeiro. O ingress novo é superconjunto do
  antigo e aplicá-lo sozinho não muda nada observável; o `url_map` apontando para um serviço que
  ainda é `INTERNAL_ONLY` responde 404 até o outro recurso existir.
- **O backend service novo tem `log_config`.** O nginx registrava uma linha por requisição com o
  `req=<id>`; o GFE não gera `X-Request-ID`. A correlação *dentro* do Django sobrevive — ele gera
  o seu quando o header falta (ADR 0018) —, mas a linha que prova "chegou na borda" num 502 ou
  timeout é justamente a do caso em que a aplicação não tem log nenhum.
- **`docs/runbooks/hml-gcp.md` existe.** Ele era citado por quatro lugares, cada um esperando
  coisa diferente, e carrega nove passos manuais que não tinham dono textual — inclusive rodar o
  `roles.sql` contra o Neon, para o qual **não há Cloud Run Job** e cujas senhas de papel não estão
  entre os 26 segredos. Fica como passo de pessoa, uma vez, e não como infra nova.
- **Fica aberto: o `terraform apply`, a leitura do painel do Upstash e o restore real contra o
  Neon.** É a mesma fronteira da ADR 0046 — código, runbook e instrumento deste lado; credencial
  de pessoa do outro.
- **Fica aberto: Cloud Armor no `hml-biahflow-api`**, que é a segunda barreira honesta. Enquanto
  não existir, o que protege aquele serviço é o ingress mais o acerto dos `path_rule`, e um
  `path_rule` mal escrito abre tudo.
- **Fica aberto: as três frentes públicas continuam com a `run.app` alcançável da internet.**
  Fechá-las é uma linha cada, mas durante a emissão do primeiro certificado a `run.app` é a única
  forma de alcançar qualquer coisa — inclusive de depurar o `imagem_bootstrap`.
- **Fica aberto: não há equivalente Python do `serviceIdentity.ts`.** Hoje é irrelevante, porque o
  IAM da `biahflow-api` está aberto. Se ela voltar a `interno`, aquele caminho quebra de novo e
  em silêncio — e foi assim que ele chegou até aqui.
