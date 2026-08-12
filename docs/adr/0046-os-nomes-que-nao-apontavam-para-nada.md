# ADR 0046 — Os nomes que não apontavam para nada

**Status:** aceito
**Data:** 08/08/2026
**Corrige:** as ADRs 0044 e 0045, e o Terraform de HML que nenhuma das duas chegou a aplicar

## Contexto

O Terraform de HML e os dois workflows existiam como código e **nunca haviam rodado**: o CI
falhava em `google-github-actions/auth` por não haver `WIF_PROVIDER`, e não havia `WIF_PROVIDER`
porque não havia projeto GCP. Um bloqueio de ação humana, na primeira linha do primeiro job, é o
que mantinha o resto sem execução — e portanto sem medição.

Ao levantar o que faltava do lado humano, apareceram sete defeitos no próprio código, e nenhum
deles é do tipo "falta rodar". Cinco impediriam a subida; nenhum deixava nada vermelho antes.

**1. Não havia ordem válida entre os dois workflows.** `ambientes/hml/main.tf` montava
`"${registro}/${nome}:${tag_imagem}"`, e `infra-hml.yml` passava
`tag_imagem=ignorado-pelo-lifecycle` com o comentário de que o `lifecycle.ignore_changes` do
módulo tornava o valor irrelevante. Ele não torna: `ignore_changes` age em *update* e não em
*create*, então o primeiro apply criava serviços apontando para uma tag que não existe em
registro nenhum — revisão recusada. E `deploy-hml.yml` só faz `gcloud run services update`, que
exige o serviço já criado. Cada workflow esperava o outro.

**2. A conta que rodava o Terraform não podia rodar o Terraform.** `hml-deploy` tem
`run.admin`, `artifactregistry.writer`, `iam.serviceAccountUser` e
`secretmanager.secretVersionManager`. O `infra-hml.yml` aplicava com ela, e nenhuma daquelas
quatro cria sub-rede, conta de serviço ou pool de WIF — nem dá acesso de objeto ao bucket do
estado, de modo que o `terraform init` do CI falharia antes de planejar.

**3. Os nomes não apontavam para nada, e o IP era o errado.** `servicos.tf` declarava uma chave
`dominio` por serviço; `main.tf` **nunca a lia**, e não havia recurso de mapeamento em lugar
nenhum. Pior: o `nip.io` era montado sobre `module.fundacao.ip_saida`, o endereço do Cloud NAT —
por onde o Cloud Run *fala* com o Neon e o Upstash, e onde serviço nenhum escuta. `KEYCLOAK_ISSUER`
e `PORTAL_WEB_URL` continham nomes que resolviam para um endereço mudo, então o login OIDC não
fechava. O README afirmava o contrário, por extenso: "o `terraform apply` refaz os mapeamentos".

**4. A `portal-api` não subiria.** O `preflight.py` varre todo campo string de `Settings` em
busca de `localhost`, `127.0.0.1`, `local_only` e `changeme`, e recusa o processo (ADR 0022). O
`servicos.tf` não definia sete variáveis, que caíam no default local. Medido antes de corrigir,
com o ambiente que o Terraform entregava: **nove problemas**, entre eles
`KEYCLOAK_ADMIN_CLIENT_SECRET` vazio — que está em `_REQUIRED_SECRETS` e não existia em
`nomes_de_segredo` — e `DATABASE_MIGRATION_URL`, que a API **não usa** e cujo default carrega
`local_only`: o processo reprovava por uma credencial que só o job de migração exerce.

**5. Dois segredos criados que ninguém lia, e um lido com o nome errado.**
`ANTHROPIC_API_KEY` e `VOYAGE_API_KEY` eram criadas no Secret Manager e não entravam na lista de
segredo de serviço nenhum: o respondedor cairia no modo offline e o índice no projetor
determinístico, com o chat continuando a responder — o silêncio que a ADR 0022 existe para
impedir. Na direção oposta, `KEYCLOAK_CLIENT_SECRET` era injetado na `portal-web`, e `auth.ts:58`
lê `AUTH_KEYCLOAK_SECRET`: o BFF subiria com `clientSecret` vazio e todo login morreria na troca
do código. Faltavam também `AUTH_URL`, que decide o prefixo `__Secure-` do cookie, e
`AUTH_KEYCLOAK_ID`, que funcionava por o default do `auth.ts` ser, por coincidência, o valor certo.

**6. O realm tinha um quarto nome.** `servicos.tf` dizia `/realms/portal`, `config.py` tem
`portal-local` e o runbook manda criar `portal-homolog`. Os dois primeiros não são divergência —
`portal-local` é o realm **local** e está certo como default. `/realms/portal` não era o nome de
nada, e um `issuer` que não casa com o `iss` do token faz a API recusar todo acesso com uma
mensagem sobre assinatura.

**7. O agendador do Biahflow não tinha casa.** `docker-compose.prod.yml` de lá roda
`python manage.py run_scheduler` (digest diário, sincronia de calendário, **alerta de backup
velho**), e `processos_longos` só tinha `portal-worker` e `portal-beat`. Um alerta de backup que
não roda é pior que nenhum: faz o silêncio parecer boa notícia. A herança dos worker pools também
era fixa na `portal-api`, então não havia como declarar um processo longo do outro produto sem lhe
dar o ambiente errado.

**8. O endereço interno era um nome que não existe.** `API_BASE_URL = "http://portal-api"` e
`API_UPSTREAM = "http://biahflow-api"` supunham um DNS de nome curto entre serviços. O Cloud Run
não tem: não é Kubernetes, e não existe `portal-api.internal`. A chamada morreria na resolução, e
o `INGRESS_TRAFFIC_INTERNAL_ONLY` que o desenho inteiro protege nem chegaria a ser exercido.

**9. A segunda barreira não era atravessada por ninguém.** O módulo do Cloud Run diz que um
serviço interno tem duas — ingress e identidade — e que a segunda "é a que sobrevive a alguém
trocar o ingress por engano". Mas nenhum chamador apresentava identidade ao Cloud Run: o BFF manda
o token do Keycloak, que diz quem é a *pessoa* e não diz nada ao provedor. Toda chamada interna
levaria 403 **antes** da aplicação — e um 403 do Cloud Run não aparece em log nosso, então a
depuração começaria na API, que nunca teria sido chamada.

## Decisão

**`tag_imagem` vazia significa `imagem_bootstrap`.** O `hello` da Google é imagem que existe e
sobe; ela ocupa o serviço pelo intervalo entre o primeiro apply e o primeiro deploy, e o
`ignore_changes` que já existia impede que qualquer apply posterior a traga de volta por cima da
imagem real. O `infra-hml.yml` deixou de passar `-var tag_imagem`, e a ausência é o conserto.

**Duas contas de serviço, na divisão que os dois workflows já argumentavam.** `hml-deploy` mantém
as quatro permissões de deploy; `hml-infra` recebe as de `apply` — que são quase o projeto
inteiro — mais acesso de objeto ao bucket do estado. Só o repositório que **contém** o Terraform
federa a `hml-infra`: dar ao outro a conta que recria a rede seria poder sem uso e sem motivo.
Separar os workflows sem separar as credenciais deixava o argumento pela metade.

**`modulos/borda/`: balanceador HTTPS externo com NEGs sem servidor.** E não
`google_cloud_run_domain_mapping`, que exige verificação de posse no Search Console — `nip.io`
não é nosso. O caminho que funciona com domínio de terceiro é o certificado gerenciado do
balanceador, cuja validação é **resolução DNS até o IP do balanceador**, e
`<qualquer-coisa>.<ip>.nip.io` resolve para `<ip>` por construção. É essa coincidência que torna o
`nip.io` viável, e ela deixa de ser necessária no dia em que houver domínio: mesma variável, mesmo
módulo. O endereço de entrada nasce na **fundação** e não na borda, por um ciclo: o nome contém o
IP e o certificado precisa dos nomes.

O preço é uma regra de encaminhamento global, **único item de custo fixo de HML**. A alternativa
de custo zero — usar as URLs `*.run.app`, que já são estáveis e HTTPS — foi considerada e recusada
porque o `issuer` do Keycloak passaria a conter o nome de um serviço do Cloud Run, e trocar de
provedor deixaria de ser reescrever `modulos/`, que é a promessa que a separação em duas camadas
existe para sustentar.

**As sete variáveis entram, e `DATABASE_MIGRATION_URL` é entregue a quem não a usa.** A
alternativa era abrir exceção no `preflight` para aquele campo, e isso custa mais do que parece:
o portão deixaria de olhar uma DSN. **`SMTP_HOST` e `CLAMAV_HOST` ficam vazios**, e o vazio é a
forma de dizer que não há SMTP nem antivírus em HML — o `mailer.py:42` já trata host vazio como
desligado, e o `preflight` salta valor vazio, de modo que a ausência não precisa de um host falso
para passar o portão. Um host inventado passaria igual e mentiria.

**O realm num lugar só**, `local.realm = "portal-homolog"`, com `issuer` e `jwks_url` derivados
dele. `config.py` **não muda**: `portal-local` é o realm local e está certo.

**`processos_longos` ganhou a chave `servico`**, a mesma que `trabalhos` já usava, e
`biahflow-scheduler` entrou.

**A URL do serviço, e não o nome dele.** Derivada do formato determinístico
(`<serviço>-<número do projeto>.<região>.run.app`) e não lida de `module.servicos[...].url`, por
ciclo: aquela saída nasce deste mapa. O número vem de um data source, que não depende de recurso
nosso.

**A identidade de serviço entra em `authorizationHeader()`**, que o `CLAUDE.md` já nomeia como o
ponto de costura por onde toda chamada nova ao servidor sai — do mesmo jeito que o `trace_id`
entrou ali na ADR 0018. Pôr o header em cada `fetch` faria a próxima rota nascer com 403. Vai em
`X-Serverless-Authorization` e **não** em `Authorization`: o Cloud Run consome o header próprio e
não o repassa, então o token da pessoa chega intacto — trocar um pelo outro, que é o erro fácil
porque o Cloud Run também aceita ID token em `Authorization`, faria a API perder o principal e
responder 401 a uma chamada autorizada. Fora do Cloud Run (`K_SERVICE` ausente) o módulo devolve
`null` em vez de levantar: rodar o portal na sua máquina não pode virar erro de servidor por falta
de servidor de metadados. O token é guardado até cinco minutos antes de vencer, porque o caminho
quente é toda renderização.

**E os dois portões**, que são a parte que sobrevive a esta fatia. `ambientes/hml/main.tf`
reprova o plano quando um segredo é referenciado e não criado, e quando um segredo é criado e
nenhum serviço o lê. São `precondition` e não `check`: medido, `check` emite *warning*, o
`terraform plan` sai 0 e o job fica verde — a forma exata do `dependency-review` da ADR 0023. Com
`precondition`, um segredo órfão injetado faz o plano sair 1.

## Consequências

- O primeiro apply é **local, com credencial de pessoa**, e isso não é preferência: o pool de WIF
  que o CI usaria é criado por este Terraform. `docs/runbooks/hml-gcp.md` traz a ordem.
- A primeira emissão do certificado gerenciado leva de quinze minutos a uma hora. Nesse intervalo
  o HTTPS responde erro de certificado, e não erro de rota — quem não souber disso vai depurar a
  coisa errada.
- Uma regra de encaminhamento global passa a custar ~US$ 18/mês. É o único custo que não escala a
  zero em HML.
- O `nip.io` depende de um serviço de terceiro para resolver DNS. Aceitável em homologação, e o
  argumento de que é temporário está no `var.dominio`.
- **Fica aberto, e é o item mais importante desta lista: a `biahflow-api` continua com uma
  barreira só.** A `portal-web` é servidor e pode guardar uma identidade de serviço; a
  `biahflow-web` é nginx servindo um SPA, e quem chama a API ali é **o navegador**, com o nginx
  como passagem. nginx não emite ID token, e — o que pesa mais — um componente ao lado dele que
  emitisse cunharia token para qualquer requisição que o alcançasse: a barreira voltaria a ser a
  rede, com uma peça a mais para manter e a aparência de duas. **Para um serviço cujo cliente é o
  navegador, IAM invoker não é a segunda barreira.** O equivalente de força comparável é trocar o
  ingress para `INTERNAL_LOAD_BALANCER` e rotear `/api|/admin|/static` do host `app.<base>` pelo
  balanceador, tirando o proxy do nginx do caminho: o `run.app` deixa de ser alcançável de fora e
  a borda passa a ser nossa. Isso muda o desenho de roteamento e não foi feito aqui.
  *(**Feito na ADR 0048**, com duas retificações a este parágrafo. Os caminhos são **sete** e não
  três — `/healthz` e `/readyz` precisam entrar, com e sem barra no fim, senão a sonda cai no
  `try_files` do SPA e um balanceador lê `index.html` com 200 como "saudável". E o que a fatia
  entrega são ingress **mais roteamento**, não duas barreiras: um NEG sem servidor não cunha ID
  token, então atrás do balanceador o IAM fica aberto de propósito. A frase acima já dizia isso ao
  recusar o IAM invoker; a ADR 0048 a mantém e nomeia o que faltaria — Cloud Armor.)*
- **Fica aberto:** a medição de comando/hora do Upstash com fila vazia, que a ADR 0045 escreveu
  como condição para HML ser declarada pronta. Ela continua sendo, e agora há onde medir.
  *(A ADR 0048 entregou o **instrumento** — `scripts/redis_rate.py` — e mostrou que a aritmética
  daquela ADR estava incompleta. A leitura contra o Upstash continua aberta, e continua sendo a
  condição.)*
- **Fica aberto:** `dependency-review` não roda em repositório privado sem GitHub Advanced
  Security, e o `e2e` tem dois testes vermelhos que não têm relação com GCP. Os dois barram o
  merge e não são desta fatia.
