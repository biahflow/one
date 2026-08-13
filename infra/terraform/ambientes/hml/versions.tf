terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    # A borda deixou de ser um recurso da GCP em 13/08/2026. Mesma faixa de versão que
    # o `biahflow-site` já usa — os dois states escrevem na mesma zona, e divergir de
    # major entre eles seria descobrir a incompatibilidade num apply, não aqui.
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.projeto
  region  = var.regiao
}

# O token vem por `CLOUDFLARE_API_TOKEN` no ambiente e **não** por variável: variável
# aparece em plano, em state e em log de CI. O account id, esse, é identificador e
# não segredo — está em `variables.tf`, como no repo do site.
provider "cloudflare" {}
