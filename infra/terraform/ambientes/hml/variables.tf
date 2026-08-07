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

variable "zona" {
  description = "Zona da VM de fila. Precisa pertencer a `regiao`."
  type        = string
  default     = "us-east1-b"
}

variable "dominio" {
  description = <<-TXT
    Domínio de HML, sem subdomínio. Vazio faz tudo cair em `nip.io` sobre o IP de
    saída, que dá nome estável ao OIDC — o Keycloak precisa que o `issuer` não mude
    a cada deploy.

    Trocar depois é mudar esta variável e aplicar. O que **não** vem de graça: o
    realm do Keycloak guarda `redirectUris` e o `issuer`, e isso é passo de runbook,
    não de Terraform.
  TXT
  type        = string
  default     = ""
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

variable "tag_imagem" {
  description = <<-TXT
    A tag das imagens a implantar. **SHA do commit, nunca `latest`**: é o que
    permite voltar apontando a revisão anterior, e o que faz duas revisões
    diferentes serem distinguíveis.
  TXT
  type        = string
}

variable "nomes_de_segredo" {
  description = <<-TXT
    Os segredos que o Terraform **cria vazios** no Secret Manager. Os valores entram
    por fora (`gcloud secrets versions add`) e nunca por aqui — o repositório
    documenta os nomes e jamais os valores (ADR 0011 do Biahflow).
  TXT
  type        = list(string)
  default = [
    "AUTH_SECRET", "KEYCLOAK_CLIENT_SECRET",
    "DATABASE_URL", "DATABASE_SYSTEM_URL", "DATABASE_ADMIN_URL", "DATABASE_MIGRATION_URL",
    "BIAHFLOW_READ_TOKEN", "BIAHFLOW_WEBHOOK_SECRET",
    "AGENT_KEY_PEPPER", "DRIVE_TOKEN_ENCRYPTION_KEY",
    "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY",
    "KC_DB_URL", "KC_DB_USERNAME", "KC_DB_PASSWORD", "KC_BOOTSTRAP_ADMIN_PASSWORD",
    "DJANGO_SECRET_KEY", "PORTAL_READ_TOKEN", "PORTAL_WEBHOOK_SECRET", "REDIS_URL",
    "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN",
    "ANTHROPIC_API_KEY", "VOYAGE_API_KEY",
  ]
}

variable "maquina_fila" {
  description = "Tipo da VM que hospeda Redis, worker e beat."
  type        = string
  default     = "e2-small"
}
