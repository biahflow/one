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
  default     = ["dcamppos83/biahflow-portal-cliente", "dcamppos83/biahflow-portal"]
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

variable "tag_imagem" {
  description = <<-TXT
    A tag das imagens a implantar. **SHA do commit, nunca `latest`**: é o que
    permite voltar apontando a revisão anterior, e o que faz duas revisões
    diferentes serem distinguíveis.

    Vazio é o caso do **primeiro apply**, e significa `imagem_bootstrap`. Ver lá
    por que o default não pode ser uma tag do nosso próprio registro.
  TXT
  type        = string
  default     = ""
}

variable "imagem_bootstrap" {
  description = <<-TXT
    A imagem com que um serviço **nasce**, antes de o primeiro deploy existir.

    O `lifecycle.ignore_changes` dos módulos protege a tag do último deploy de um
    apply de infraestrutura — mas `ignore_changes` só vale em *update*, nunca em
    *create*. No primeiro apply o Cloud Run recebe a imagem literal, tenta baixá-la
    de um Artifact Registry ainda vazio e recusa a revisão; e o `deploy-hml.yml` só
    sabe fazer `gcloud run services update`, que exige o serviço já criado. Sem esta
    variável não existe ordem válida entre os dois workflows: cada um espera o outro.

    O `hello` da Google serve porque só precisa existir e subir. Ele fica no ar pelo
    intervalo entre o apply e o primeiro deploy, e o `ignore_changes` garante que
    nenhum apply posterior o traga de volta por cima da imagem real.
  TXT
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "nomes_de_segredo" {
  description = <<-TXT
    Os segredos que o Terraform **cria vazios** no Secret Manager. Os valores entram
    por fora (`gcloud secrets versions add`) e nunca por aqui — o repositório
    documenta os nomes e jamais os valores (ADR 0011 do Biahflow).

    O nome de cada um é **o nome da variável de ambiente que a aplicação lê**: o
    módulo do Cloud Run usa a mesma string dos dois lados (`secret_key_ref`), então
    um segredo cujo nome não bate com o que o código procura é um segredo que existe,
    tem valor, é montado e não chega em ninguém.
  TXT
  type        = list(string)
  default = [
    # `AUTH_KEYCLOAK_SECRET` e não `KEYCLOAK_CLIENT_SECRET`: quem lê é o `auth.ts`,
    # e o nome dele vem do Auth.js. Enquanto era o outro, o BFF subia com o
    # `clientSecret` vazio e todo login morria na troca do código.
    "AUTH_SECRET", "AUTH_KEYCLOAK_SECRET",
    # O par do `portal-admin`, que é outro client e outro segredo. Está em
    # `_REQUIRED_SECRETS` do `preflight.py`, então a API **recusa subir** sem ele.
    "KEYCLOAK_ADMIN_CLIENT_SECRET",
    "DATABASE_URL", "DATABASE_SYSTEM_URL", "DATABASE_ADMIN_URL", "DATABASE_MIGRATION_URL",
    "BIAHFLOW_READ_TOKEN", "BIAHFLOW_WEBHOOK_SECRET",
    "AGENT_KEY_PEPPER", "DRIVE_TOKEN_ENCRYPTION_KEY",
    "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY",
    "KC_DB_URL", "KC_DB_USERNAME", "KC_DB_PASSWORD", "KC_BOOTSTRAP_ADMIN_PASSWORD",
    "DJANGO_SECRET_KEY", "PORTAL_READ_TOKEN", "PORTAL_WEBHOOK_SECRET", "REDIS_URL",
    "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN",
    # A senha de app do Gmail. É a única credencial de e-mail: o resto (host, porta,
    # TLS, usuário, remetente) é variável comum, porque nenhum deles é segredo e
    # todos aparecem em `gcloud run services describe` sem prejuízo.
    "EMAIL_HOST_PASSWORD",
    "ANTHROPIC_API_KEY", "VOYAGE_API_KEY",
  ]
}
