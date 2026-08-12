# ADR 0050 — O primeiro apply, e as três coisas que só ele podia dizer

**Status:** aceito
**Data:** 12/08/2026
**Fecha:** o "fica aberto: o `terraform apply`" da ADR 0048, e a primeira execução do
`docs/runbooks/hml-gcp.md`
**Relacionadas:** ADR 0044 (bootstrap em Postgres gerenciado), ADR 0045 (worker no Cloud Run),
ADR 0046 (o Terraform de HML), ADR 0048 (a barreira que o navegador não atravessa)

## Contexto

A ADR 0046 escreveu a HML como código, a ADR 0048 fechou as lacunas dela e as duas terminaram na
mesma fronteira, com as mesmas palavras: *"código, runbook e instrumento deste lado; credencial de
pessoa do outro"*. O `hml-gcp.md` dizia de si mesmo, na última seção, que **nada ali tinha sido
percorrido de ponta a ponta contra a GCP**.

Percorrer aquilo achou três defeitos, e os três são da família que este repositório já nomeou
tantas vezes: **nenhum deixava nada vermelho antes de alguém aplicar**. Os dois primeiros
reprovam o `apply`; o terceiro reprova o boot, e só apareceu porque o `apply` passou.

**1. Os 26 segredos existiam sem versão, e a revisão do Cloud Run é recusada na criação.** O
`modulos/fundacao/main.tf` cria `google_secret_manager_secret` e mais nada — não há
`google_secret_manager_secret_version` em lugar nenhum, e é deliberado (*"um valor passado pelo
Terraform ficaria no estado, que é um arquivo num bucket"*). Só que todo serviço monta o segredo
com `version = "latest"`, e `latest` de um segredo sem versão **não existe**: a revisão é recusada
na hora de criar, não no boot. O passo 3 do runbook manda aplicar tudo e explica que *"os serviços
sobem quebrados, e isso é esperado"* — a frase é sobre segredo **vazio**, e o que o Terraform
produz é segredo **inexistente**. São coisas diferentes e o texto tratava as duas como uma.

O aviso do passo 5 dizia a metade certa: *"um segredo esquecido não reprova no apply — os portões
olham nome, não valor"*. Os portões, de fato, não olham valor. Mas o Cloud Run olha a existência
da versão, e é ele quem reprova.

**2. A organização recusa `allUsers`, e é a configuração padrão de um Workspace.** A org
`biahflow.ai` nasce com `constraints/iam.allowedPolicyMemberDomains` restrita ao seu customer ID —
Domain Restricted Sharing ligado por padrão em toda organização criada por Workspace. As quatro
ligações `invocacao_aberta` do `servico-cloudrun` falham com *"One or more users named in the
policy do not belong to a permitted customer"*.

Isso não é contornável do lado do desenho, e a ADR 0048 já tinha escrito por quê: **um NEG sem
servidor não cunha ID token**, então o serviço atrás dele precisa aceitar chamada não autenticada,
e a barreira é o ingress. Sem a exceção, a HML sobe inteira e responde 403 a tudo — com a
aplicação de pé e nada no log dela, que é o modo de falha que aquela ADR mandou não depurar pelo
Django. O `hml-gcp.md` não mencionava a política em lugar nenhum, e ela é **pré-requisito**, não
tropeço.

**3. O `check --deploy` reprovava o boot da `biahflow-api` por `NUM_PROXIES`.** O `servicos.tf`
injeta `TRUST_X_FORWARDED_PROTO = "true"` e declarava, logo abaixo, quatro variáveis com a
justificativa escrita: elas existem porque o `entrypoint.sh` do outro repositório roda
`check --deploy --fail-level WARNING --tag security` antes do gunicorn. O comentário nomeava
`SECURE_SSL_REDIRECT` e `SECURE_HSTS_SECONDS` — e o mesmo check tem um `biahflow.E002` que cobra o
**par** `TRUST_X_FORWARDED_PROTO` + `NUM_PROXIES`, que ninguém declarou. Resultado: `SystemCheckError`,
`Container called exit(1)`, sonda de inicialização reprovando toda revisão, e o deploy morrendo em
`gcloud run services update`.

A forma é exatamente a do defeito que a ADR 0046 consertou no nginx — uma variável que o outro
lado cobra e este lado não entrega —, com o agravante de que aqui **o comentário certo já estava
escrito** e cobria só quatro dos cinco casos que o check tem.

## Decisão

### O primeiro apply vai em dois, e a razão não é preferência

```bash
terraform apply -target=module.fundacao   # rede, registro, SAs, WIF e os 26 segredos, vazios
<preencher as 26 versões>
terraform apply                            # serviços, jobs, workers, borda
```

**A correção não é código, e isso é deliberado.** Acrescentar `google_secret_manager_secret_version`
ao módulo resolveria o sintoma pondo o valor no estado, que é precisamente o que a ADR 0046 recusou
ao criar os segredos vazios. O que estava errado era a **ordem**, e ordem mora no runbook.

Isso não contradiz o `apply → deploy → apply` que a ADR 0048 fixou: desdobra o primeiro dos três.

### A exceção de política é pré-requisito de pessoa, e fica escopada ao projeto

```yaml
name: projects/biahflow-hml/policies/iam.allowedPolicyMemberDomains
spec:
  rules:
    - allowAll: true
```

**Escopo de projeto, e não de organização:** a política da org fica intacta e todo projeto novo
continua nascendo restrito.

**`allowAll` e não o valor estreito, e isso foi medido.** A documentação do Google descreve
`principalSet://goog/public:all` como o jeito de liberar acesso público mantendo o resto restrito;
a constraint **recusa esse valor** (`INVALID_GOOGLE_MANAGED_CONSTRAINT`). Não há meio-termo
disponível, então o que se escolhe é o escopo, e o escopo é um projeto de homologação.

**Não vira Terraform.** A `hml-infra` tem `resourcemanager.projectIamAdmin` e nada de
`orgpolicy`; conceder-lhe permissão de política de organização daria ao CI de um projeto o poder
de afrouxar a postura da org — que é maior do que tudo o que ele existe para fazer. Fica onde
estão os outros passos de pessoa: o `roles.sql`, o realm e as allowlists.

O papel `roles/orgpolicy.policyAdmin` **só é concedível em organização ou pasta** — tentar
concedê-lo no projeto responde `Role ... is not supported for this resource`. Quem executa este
passo precisa dele na org, e pode devolvê-lo depois: a política sobrevive à remoção do papel.

### `NUM_PROXIES = "2"` no `servicos.tf`, e o comentário passa a dizer cinco

O valor é a posição, contada do fim, de onde o DRF tira o IP do cliente no `X-Forwarded-For`. A
cadeia aqui é cliente → balanceador → Cloud Run, contra o único salto de nginx do compose — daí
`2` e não `1`. Errar para baixo produz exatamente o que o E002 descreve, todo mundo atrás do mesmo
proxy dividindo um balde só; errar para cima faz o DRF ler a ponta esquerda do header, que o
cliente pode forjar.

**O valor é raciocínio e não medição, e está escrito assim no código.**

## Consequências

- **`hml-gcp.md` ganhou um passo novo e mudou a ordem de dois.** A política da org entra antes do
  bucket; o preenchimento dos segredos sobe para antes do apply completo. Os passos seguintes
  foram renumerados, e as referências cruzadas internas acompanharam.
- **O certificado gerenciado ficou `ACTIVE` em minutos, não em 15 a 60.** A faixa continua no
  runbook porque é o pior caso do Google e a seção existe para impedir que alguém depure a rota
  achando que é erro de rota; mas a medição foi anotada, para ninguém esperar uma hora à toa.
- **O `biahflow-migrate` rodou contra o Neon na primeira tentativa.** É a prova de que a saída pelo
  Cloud NAT alcança o provedor gerenciado — o passo das allowlists não foi exercido, porque o
  plano gratuito do Neon não tem restrição de IP. Quem estiver num plano que tenha vai precisar
  dele, e ele continua no runbook.
- **Fica aberto: medir o `X-Forwarded-For` como ele chega ao contêiner.** Enquanto não for medido,
  `NUM_PROXIES` é uma hipótese defensável e não um fato, e o que está em jogo é o teto de
  requisição valer por cliente ou por balanceador.
- **O deploy fechou, e a `biahflow-web` teve sua primeira revisão real em Cloud Run.** Com o
  defeito 3 corrigido, `Publica as revisões` passou: `https://app.<base>/` serve o SPA de
  verdade, `/api/v1/auth/csrf/` responde token pela borda, `/admin/` redireciona para o login e
  `/media/` continua 404 — o `nginx.conf.template` da ADR 0046 funcionando fora do compose pela
  primeira vez.
- **Os dois passos finais do `deploy-hml.yml` daquele repositório estão quebrados, e um deles
  estava desligado desde sempre.** `Atualiza o agendador` usa `gcloud beta`, componente que o
  runner não traz, e o prompt de instalação é lido **antes** das flags — o `--quiet` que o
  comando já tinha não é considerado. E `Sonda as integrações` executava o `biahflow-check`
  **sem nunca atualizar a imagem dele**: o job seguia na `imagem_bootstrap`, falhava com
  `Application exec likely failed`, e como o passo é `continue-on-error` isso nunca deixou nada
  vermelho. O veredito que aquele passo promete deixar no log **nunca existiu**. Os dois foram
  corrigidos lá e exercitados aqui à mão; a sonda, rodando de verdade, reprova `email`
  (`Connection refused` — não há SMTP em HML) e `enrichment` (403 da BrasilAPI), e confirma
  `payments` no caminho sem provedor.
- **Fica aberto: nada disto foi commitado ainda**, e o `WIF_PROVIDER` foi posto só no
  `biahflow-portal`. Enquanto o do `biahflow-portal-cliente` não existir, o `infra-hml.yml` não
  roda e todo apply continua saindo de uma máquina.
- **Fica aberto: as três frentes públicas continuam com a `run.app` alcançável**, e agora com um
  motivo a mais para revisitar — a exceção de política é ampla no projeto, então fechar o que não
  precisa ser público deixou de ser só higiene.
