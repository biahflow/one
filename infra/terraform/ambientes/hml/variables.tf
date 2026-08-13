variable "projeto" {
  description = "Project ID da GCP."
  type        = string
  default     = "biahflow-hml"
}

variable "regiao" {
  description = "Região dos recursos regionais (Cloud Run, VM, bucket)."
  type        = string
  default     = "us-east1"
}

variable "dominio" {
  description = <<-TXT
    Domínio de HML, sem subdomínio. Vazio faz tudo cair em `nip.io` sobre o IP de
    **entrada** do balanceador, que dá nome estável ao OIDC — o Keycloak precisa
    que o `issuer` não mude a cada deploy.

    Uma versão anterior montava o `nip.io` sobre o IP de *saída* do Cloud NAT, que
    é endereço que serviço nenhum escuta: o nome resolvia e não respondia.

    Trocar depois é mudar esta variável e aplicar. O que **não** vem de graça: o
    realm do Keycloak guarda `redirectUris` e o `issuer`, e isso é passo de runbook,
    não de Terraform.
  TXT
  type        = string
  default     = ""
}

variable "borda_ligada" {
  description = <<-TXT
    Se a borda serve requisições. `false` destrói as duas regras de encaminhamento e
    **só** elas — é o único item de HML que cobra por hora estando parado, ~US$ 18/mês,
    e a ADR 0046 já o registrava como "o único custo fixo de HML".

    Num ambiente com um usuário só, deixar isso ligado 730 horas por mês para usar
    algumas dezenas é o desperdício óbvio. Desligado, o resto da borda continua de pé
    (NEG, backend service, url map, proxies, certificado) e não custa nada: religar é
    um apply de segundos, sem tocar em DNS nem reemitir certificado.

    O que **não** sobrevive a um sono longo é a renovação do certificado gerenciado,
    que chega pela porta 80 — ver o comentário em `modulos/borda/main.tf` e o runbook.

    O IP de entrada permanece reservado de propósito. Solto, ele custaria US$ 0,01/h
    (o dobro da tarifa de "em uso"), e liberá-lo mudaria os hostnames `nip.io`, que
    contêm o IP — forçando reemissão de certificado a cada religada. Isso só deixa de
    valer quando `var.dominio` estiver preenchida.
  TXT
  type        = bool
  default     = true
}

variable "bucket_estado" {
  description = <<-TXT
    O bucket do estado remoto, criado **à mão** antes de tudo (o comando está em
    `backend.tf`). Aparece aqui como variável porque o Terraform precisa conceder
    acesso a ele à conta que roda o próprio Terraform, e um recurso não pode
    referenciar o bucket que guarda o estado dele.

    Precisa bater com o `bucket` do `backend.tf`, que não aceita variável —
    `terraform init` acontece antes de haver valores.
  TXT
  type        = string
  default     = "biahflow-hml-tfstate"
}

variable "repositorios_github" {
  description = <<-TXT
    Os repositórios que podem se autenticar por Workload Identity Federation, no
    formato `dono/repo`. **Sem chave de conta de serviço** — é a mesma postura que a
    ADR 0016 do Biahflow adotou por política da organização.
  TXT
  type        = list(string)
  # `biahflow-site` entrou em 13/08/2026: o site de marketing passou a ter backend
  # próprio no Cloud Run (`biahflow-site-api-hml`), e o workflow que publica a imagem
  # dele precisa da mesma federação — sem chave, como os outros dois. O Terraform
  # daquele produto mora no repo dele, então ele **não** entra em `repositorio_infra`:
  # federa só a conta de deploy.
  default = [
    "dcamppos83/biahflow-portal-cliente",
    "dcamppos83/biahflow-portal",
    "dcamppos83/biahflow-site",
  ]
}

variable "repositorio_infra" {
  description = <<-TXT
    O único repositório autorizado a rodar `terraform apply` — o que **contém** o
    Terraform. Os dois repos publicam imagem e por isso ambos federam a conta de
    deploy; só um muda a forma da infraestrutura, e conceder ao outro a conta que
    recria a rede seria poder sem uso e sem motivo.

    Precisa estar contido em `repositorios_github`, senão a condição do provedor
    de WIF recusa o token antes de a federação ser consultada.
  TXT
  type        = string
  default     = "dcamppos83/biahflow-portal-cliente"
}

variable "segredos" {
  description = <<-TXT
    Os segredos que o Terraform **cria vazios** no Secret Manager, e de que produto é
    cada um. Os valores entram por fora (`gcloud secrets versions add`) e nunca por
    aqui — o repositório documenta os nomes e jamais os valores.

    **A chave é o nome do segredo; o valor é o produto dono.** O dono existe porque os
    dois portões de leitor moram nos states de produto desde a ADR 0051: cada um cobra
    que todo segredo atribuído a ele seja lido por algum serviço seu. Sem o dono
    declarado aqui, um segredo poderia nascer sem que portão nenhum perguntasse se ele
    chega a alguém — que é exatamente como `ANTHROPIC_API_KEY` e `VOYAGE_API_KEY`
    passaram meses no cofre sem leitor.

    Na maioria dos casos o nome do segredo é o nome da variável de ambiente que a
    aplicação lê. A exceção são as quatro DSNs: quando dois produtos leem a mesma
    variável e precisam de valores diferentes, o segredo ganha o prefixo do dono e o
    mapa `segredos` de cada produto faz a ligação.
  TXT
  type        = map(string)
  default = {
    # --- Portal do cliente ---------------------------------------------------
    AUTH_SECRET                  = "portal"
    AUTH_KEYCLOAK_SECRET         = "portal"
    KEYCLOAK_ADMIN_CLIENT_SECRET = "portal"
    PORTAL_DATABASE_URL          = "portal"
    PORTAL_REDIS_URL             = "portal"
    DATABASE_SYSTEM_URL          = "portal"
    DATABASE_ADMIN_URL           = "portal"
    DATABASE_MIGRATION_URL       = "portal"
    BIAHFLOW_READ_TOKEN          = "portal"
    BIAHFLOW_WEBHOOK_SECRET      = "portal"
    AGENT_KEY_PEPPER             = "portal"
    DRIVE_TOKEN_ENCRYPTION_KEY   = "portal"
    STORAGE_ACCESS_KEY           = "portal"
    STORAGE_SECRET_KEY           = "portal"
    ANTHROPIC_API_KEY            = "portal"
    VOYAGE_API_KEY               = "portal"
    KC_DB_URL                    = "portal"
    KC_DB_USERNAME               = "portal"
    KC_DB_PASSWORD               = "portal"
    KC_BOOTSTRAP_ADMIN_PASSWORD  = "portal"

    # --- Biahflow ------------------------------------------------------------
    DJANGO_SECRET_KEY          = "biahflow"
    BIAHFLOW_DATABASE_URL      = "biahflow"
    BIAHFLOW_REDIS_URL         = "biahflow"
    PORTAL_READ_TOKEN          = "biahflow"
    PORTAL_WEBHOOK_SECRET      = "biahflow"
    GOOGLE_OAUTH_CLIENT_ID     = "biahflow"
    GOOGLE_OAUTH_CLIENT_SECRET = "biahflow"
    GOOGLE_OAUTH_REFRESH_TOKEN = "biahflow"
    EMAIL_HOST_PASSWORD        = "biahflow"
    # Token compartilhado da captação de leads: quem o apresenta em `X-Intake-Token`
    # pode postar em `/api/v1/leads/intake/`. O leitor é a `biahflow-api`; o emissor
    # é o relay do site de marketing (repo `biahflow-site`), que o guarda do lado
    # servidor para ele nunca chegar ao navegador.
    #
    # Sem ele o intake não fica aberto — fica **fechado**: `_valid_intake_token`
    # exige `bool(expected)` antes de comparar, então token vazio recusa todo lead
    # com 401 e o visitante vê erro. É o mesmo segredo que o site guarda em
    # `site-crm-intake-token-hml`, e os dois valores têm de ser idênticos.
    LEAD_INTAKE_TOKEN = "biahflow"
  }
}
